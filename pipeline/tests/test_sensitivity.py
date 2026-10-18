"""One-at-a-time sensitivity cases stay inside the demonstration contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import evacuation, replay_audit, runner
from bkkflow.sensitivity import (
    build_sensitivity_ensemble,
    ensemble_cases,
    load_sensitivity_table,
    resolve_sensitivity_case,
    select_run_case,
)
from bkkflow.util import read_json, write_json
from test_pilot_publication import pilot_inputs  # noqa: F401
from test_pipeline import _cohort, _destinations


CONFIG = Path(__file__).resolve().parents[2] / "config" / "scenario.json"
CASE_IDS = (
    "baseline",
    "flood-dry",
    "flood-low",
    "flood-high",
    "compliance-0.60",
    "compliance-0.90",
    "warning-reach-0.70",
    "warning-reach-1.00",
    "delay-mean-300",
    "delay-mean-1800",
)


def _table():
    return load_sensitivity_table(json.loads(CONFIG.read_text(encoding="utf-8")))


def _flags(**overrides):
    values = {
        "case_id": None,
        "dry_requested": False,
        "flood_severity": None,
        "compliance": None,
        "warning_reach": None,
        "preparation_delay_mean_s": None,
        "threshold_set_version": None,
    }
    values.update(overrides)
    return values


def test_shipped_scenario_freezes_ten_one_factor_cases():
    cases = ensemble_cases(_table())

    assert [case.case_id for case in cases] == list(CASE_IDS)
    assert cases[0].factor is None
    assert cases[0].compliance == pytest.approx(0.78)
    assert cases[0].warning_reach == pytest.approx(0.92)
    assert cases[0].preparation_delay_mean_s == pytest.approx(900)
    assert {case.factor for case in cases if case.factor} == {
        "flood", "compliance", "warning_reach", "preparation_delay_mean_s",
    }
    assert all(case.threshold_set_version == "bkk-demo-thresholds-v0.1" for case in cases)


def test_case_table_rejects_mixed_unknown_and_extra_threshold_levels():
    table = _table()
    scenario = json.loads(CONFIG.read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="more than one factor"):
        resolve_sensitivity_case(table, flood_severity="low", compliance=0.6)
    with pytest.raises(ValueError, match="more than one factor"):
        resolve_sensitivity_case(table, flood_enabled=False, compliance=0.6)
    with pytest.raises(ValueError, match="unknown compliance"):
        resolve_sensitivity_case(table, compliance=0.5)
    with pytest.raises(ValueError, match="unknown flood severity"):
        resolve_sensitivity_case(table, flood_severity="extreme")
    with pytest.raises(ValueError, match="one threshold set"):
        resolve_sensitivity_case(table, threshold_set_version="bkk-demo-thresholds-v0.2")

    scenario["sensitivity"]["threshold_set_version"] = [
        "bkk-demo-thresholds-v0.1",
        "bkk-demo-thresholds-v0.2",
    ]
    with pytest.raises(ValueError, match="one threshold set"):
        load_sensitivity_table(scenario)

    assert select_run_case(table, **_flags(dry_requested=True)) is None


def test_predraw_delay_does_not_depend_on_compliance():
    def delays(compliance: float) -> dict[str, float]:
        scenario = evacuation.EvacuationScenario(
            scenario_id="t",
            warning_time_s=1000,
            warning_reach=1.0,
            compliance=compliance,
            preparation_delay_mean_s=900,
            preparation_delay_sd_s=600,
        )
        states, _ = evacuation.simulate_evacuation(
            _cohort(40),
            destinations=_destinations(),
            route_lookup=lambda *_args: (0.0, 1.0, []),
            scenario=scenario,
            seed=7,
        )
        return {
            row.person_id: float(row.event_time_s) - 1000
            for row in states.itertuples()
            if row.reason != "not_compliant"
        }

    low, high = delays(0.6), delays(0.9)
    shared = set(low) & set(high)
    assert shared
    assert set(high) - set(low)
    for person_id in shared:
        assert low[person_id] == pytest.approx(high[person_id])


def test_replay_predraw_matches_the_simulation_streams():
    left = evacuation.predraw_departure_streams(29092026, 20, 900.0, 600.0)
    right = replay_audit._predraw_departure(29092026, 20, 900.0, 600.0)
    for actual, expected in zip(left, right, strict=True):
        assert np.array_equal(actual, expected)


def _write_case(root: Path, case_id: str, *, cohort: str, compliance: float = 0.78,
                severity: str = "moderate", state: str = "moderate",
                warning: float = 0.92, delay: float = 900.0,
                aoi: str = "khlong-san-district",
                not_warned: float = 10.0, not_compliant: float = 20.0,
                route_failed: float = 5.0, shelter_full: float = 15.0,
                stranded: float = 0.0, arrived: float = 50.0,
                p50: float | None = 12.0, p90: float | None = 20.0) -> Path:
    run_dir = root / case_id
    run_dir.mkdir(parents=True)
    did_not_depart = not_warned + not_compliant
    write_json(run_dir / "manifest.json", {
        "geography": {"aoi_id": aoi},
        "active_scenario": {
            "state": state,
            "configured_scenario_id": "scenario",
            "case_id": case_id,
        },
        "flood_scenario": {"parameters": {"severity": severity, "scenario_id": "scenario"}},
        "evacuation_scenario": {
            "departure_model": {
                "compliance": compliance,
                "warning_reach": warning,
                "preparation_delay_mean_s": delay,
                "preparation_delay_sd_s": 600,
                "rng": "predraw-v1",
            },
            "mode_thresholds": {"version": "bkk-demo-thresholds-v0.1"},
        },
    })
    write_json(run_dir / "stats.json", {
        "run_id": case_id,
        "geography": {"aoi_id": aoi},
        "denominators": {
            "quantities": {"cohort": {"rows": 10, "weight": 100.0}},
            "pairing": {"common_identity": {"cohort_digest": cohort}},
            "clearance_denominator": {"weight": arrived},
        },
        "evacuation": {
            "state_distribution": {
                "did_not_depart": did_not_depart,
                "route_failed": route_failed,
                "shelter_full": shelter_full,
                "stranded": stranded,
                "arrived": arrived,
            },
            "reason_weights": {
                "not_warned": not_warned,
                "not_compliant": not_compliant,
            },
            "clearance_time_minutes": {"p5": 1.0, "median": p50, "p95": 30.0},
            "clearance_sensitivity_minutes": {
                "p50": p50,
                "p90": p90,
                "arrived_weight": arrived,
            },
        },
    })
    return run_dir


def test_ensemble_report_publishes_demonstration_shares(tmp_path):
    cohort = "a" * 64
    baseline = _write_case(tmp_path, "baseline", cohort=cohort)
    other = _write_case(
        tmp_path, "compliance-0.60", cohort=cohort, compliance=0.6,
        not_compliant=40.0, arrived=30.0,
    )
    report = build_sensitivity_ensemble([baseline, other])

    assert report["status"] == "demonstration"
    assert report["design"] == "one_at_a_time"
    assert report["compared_with"] == "ensemble_baseline"
    assert report["aoi_id"] == "khlong-san-district"
    assert report["citywide"] is False
    assert report["cohort_id"] == cohort
    assert any("uncalibrated" in item for item in report["limitations"])
    compliance = next(row for row in report["cases"] if row["case_id"] == "compliance-0.60")
    assert compliance["factor"] == "compliance"
    assert compliance["shares"]["not_compliant"] == pytest.approx(0.4)
    assert compliance["shares"]["did_not_depart"] == pytest.approx(0.5)
    assert compliance["shares"]["stranded"] == pytest.approx(0.0)
    assert compliance["clearance_minutes"]["p50"] == pytest.approx(12.0)
    assert compliance["clearance_minutes"]["p90"] == pytest.approx(20.0)
    assert compliance["clearance_minutes"]["arrived_weight"] == pytest.approx(30.0)
    assert compliance["sample_denominator"] == {"rows": 10, "weight": 100.0}
    assert "2026-10-11" not in json.dumps(report)


def test_ensemble_report_rejects_a_mismatched_cohort_or_two_factors(tmp_path):
    cohort = "b" * 64
    baseline = _write_case(tmp_path, "baseline", cohort=cohort)
    other = _write_case(tmp_path, "compliance-0.60", cohort="c" * 64, compliance=0.6)
    with pytest.raises(ValueError, match="cohort id"):
        build_sensitivity_ensemble([baseline, other])

    mixed = _write_case(
        tmp_path / "mixed", "flood-high", cohort=cohort, severity="high", state="high", compliance=0.6,
    )
    with pytest.raises(ValueError, match="more than one factor"):
        build_sensitivity_ensemble([baseline, mixed])


def test_ensemble_report_rejects_a_citywide_area(tmp_path):
    run_dir = _write_case(tmp_path, "baseline", cohort="d" * 64, aoi="bangkok-bma")
    with pytest.raises(ValueError, match="not a Bangkok result"):
        build_sensitivity_ensemble([run_dir])


def test_execute_run_rejects_sensitivity_overrides_before_a_run_directory():
    with pytest.raises(ValueError, match="unknown compliance"):
        runner.execute_run(pilot_id="khlong-san-district", compliance=0.5)
    with pytest.raises(ValueError, match="more than one factor"):
        runner.execute_run(
            pilot_id="khlong-san-district", flood_severity="low", compliance=0.6,
        )


def test_sensitivity_case_is_published_and_replayed(pilot_inputs):  # noqa: F811
    result = runner.execute_run(
        run_id="sensitivity-compliance",
        pilot_id="khlong-san-district",
        max_agents=4,
        sensitivity_case="compliance-0.60",
    )
    manifest = read_json(Path(result["run_dir"]) / "manifest.json")
    stats = read_json(Path(result["run_dir"]) / "stats.json")

    assert result["validation_passed"]
    assert manifest["active_scenario"]["case_id"] == "compliance-0.60"
    assert manifest["active_scenario"]["state"] == "moderate"
    assert manifest["evacuation_scenario"]["departure_model"]["rng"] == "predraw-v1"
    assert manifest["evacuation_scenario"]["departure_model"]["compliance"] == pytest.approx(0.6)
    assert "reason_weights" in stats["evacuation"]
    assert "p90" in stats["evacuation"]["clearance_sensitivity_minutes"]
    bundle = replay_audit.load_audit_bundle(Path(result["run_dir"]))
    replay_audit.replay_evacuation(bundle)
