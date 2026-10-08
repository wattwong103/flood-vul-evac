"""Checked dry/moderate comparison-report contract."""

from __future__ import annotations

import hashlib
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import report
from bkkflow import replay_audit, runner
from bkkflow.util import read_json, write_json
from test_pilot_publication import pilot_inputs  # noqa: F401


@pytest.fixture
def published_pair(pilot_inputs: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:  # noqa: F811
    monkeypatch.setattr(report, "RUNS_DIR", pilot_inputs)
    runner.execute_run(
        run_id="pair-dry", pilot_id="khlong-san-district",
        flood_enabled=False, max_agents=3,
    )
    runner.execute_run(
        run_id="pair-moderate", pilot_id="khlong-san-district",
        flood_enabled=True, max_agents=3, cohort_from_run="pair-dry",
    )
    return "pair-dry", "pair-moderate"


def test_load_checked_pair_accepts_one_audited_dry_moderate_pair(
    published_pair: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audited: list[str] = []
    audit_saved_run = replay_audit.audit_saved_run

    def record_audit(path: Path) -> dict[str, Any]:
        audited.append(Path(path).name)
        return audit_saved_run(path)

    monkeypatch.setattr(report.replay_audit, "audit_saved_run", record_audit)
    pair = report.load_checked_pair(*reversed(published_pair))

    assert pair.aoi_id == "khlong-san-district"
    assert pair.aoi_label == "Khlong San"
    assert (pair.dry.run_id, pair.moderate.run_id) == published_pair
    assert pair.audit_status == "PASS"
    assert sorted(audited) == sorted(published_pair)


def _registered_json(
    run_id: str, role: str, mutate: Callable[[dict[str, Any]], None]
) -> dict[str, Any]:
    run_dir = report.RUNS_DIR / run_id
    manifest = read_json(run_dir / "manifest.json")
    entry = next(item for item in manifest["outputs"] if item["role"] == role)
    path = run_dir / entry["uri"]
    payload = read_json(path)
    mutate(payload)
    write_json(path, payload)
    entry["content_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(run_dir / "manifest.json", manifest)
    return payload


def _as_aoi(run: report.CheckedRun, aoi_id: str, label: str) -> report.CheckedRun:
    bundle = run.bundle
    manifest, stats = deepcopy(bundle.manifest), deepcopy(bundle.stats)
    metadata, denominators = deepcopy(bundle.cohort_metadata), deepcopy(bundle.denominators)
    manifest["geography"]["aoi_id"] = aoi_id
    stats["geography"].update(aoi_id=aoi_id, name=label)
    metadata["aoi_id"] = aoi_id
    denominators["pairing"]["common_identity"]["aoi_id"] = aoi_id
    stats["denominators"] = denominators
    bundle = replace(
        bundle, aoi_id=aoi_id, manifest=manifest, stats=stats,
        cohort_metadata=metadata, denominators=denominators,
    )
    return replace(run, bundle=bundle)


def test_load_checked_pair_is_area_generic(
    published_pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    audited_run = report._audited_run
    monkeypatch.setattr(
        report, "_audited_run",
        lambda run_id: _as_aoi(audited_run(run_id), "bang-rak-district", "Bang Rak"),
    )

    pair = report.load_checked_pair(*published_pair)

    assert (pair.aoi_id, pair.aoi_label) == ("bang-rak-district", "Bang Rak")


def test_load_checked_pair_rejects_duplicate_state_and_broken_reference(
    published_pair: tuple[str, str],
) -> None:
    dry_id, moderate_id = published_pair
    moderate_dir = report.RUNS_DIR / moderate_id
    manifest_path, state_path = (
        moderate_dir / "manifest.json",
        moderate_dir / "run_state.json",
    )
    manifest, state = read_json(manifest_path), read_json(state_path)
    manifest["active_scenario"]["state"] = "dry"
    state["active_scenario"]["state"] = "dry"
    write_json(manifest_path, manifest)
    write_json(state_path, state)
    with pytest.raises(ValueError, match="exactly one dry and one moderate"):
        report.load_checked_pair(dry_id, moderate_id)

    manifest["active_scenario"]["state"] = "moderate"
    state["active_scenario"]["state"] = "moderate"
    write_json(manifest_path, manifest)
    write_json(state_path, state)
    _registered_json(
        moderate_id,
        "cohort_metadata",
        lambda value: value.update(reference_run_id="unrelated-run"),
    )
    with pytest.raises(ValueError, match="moderate cohort must reference dry run"):
        report.load_checked_pair(dry_id, moderate_id)


def test_load_checked_pair_rejects_common_identity_and_assumption_mismatches(
    published_pair: tuple[str, str],
) -> None:
    dry_id, moderate_id = published_pair
    moderate_dir = report.RUNS_DIR / moderate_id
    manifest_path, stats_path = moderate_dir / "manifest.json", moderate_dir / "stats.json"
    original_manifest, original_stats = read_json(manifest_path), read_json(stats_path)
    cases: list[tuple[str, Callable[[dict[str, Any], dict[str, Any]], None]]] = [
        ("AOI label", lambda _manifest, stats: stats["geography"].update(name="Other")),
        ("source/code identity", lambda manifest, _stats: manifest["code_identity"].update(git_tree="0" * 40)),
        ("population assumptions", lambda manifest, _stats: manifest["population_model"].update(population_version="other")),
        ("PFLOW assumptions", lambda manifest, _stats: manifest["pflow_contract"]["aggregation"].update(version="other")),
        ("evacuation assumptions", lambda manifest, _stats: manifest["evacuation_scenario"]["destinations"][0].update(operator="other")),
    ]
    for message, mutate in cases:
        manifest = read_json(manifest_path)
        stats = read_json(stats_path)
        mutate(manifest, stats)
        write_json(manifest_path, manifest)
        write_json(stats_path, stats)
        with pytest.raises(ValueError, match=message):
            report.load_checked_pair(dry_id, moderate_id)
        write_json(manifest_path, original_manifest)
        write_json(stats_path, original_stats)


def test_load_checked_pair_rejects_cross_aoi_and_failed_audit(
    published_pair: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dry_id, moderate_id = published_pair
    audited_run = report._audited_run
    monkeypatch.setattr(
        report, "_audited_run",
        lambda run_id: _as_aoi(audited_run(run_id), "bang-rak-district", "Bang Rak")
        if run_id == moderate_id else audited_run(run_id),
    )
    with pytest.raises(ValueError, match="AOI identity"):
        report.load_checked_pair(dry_id, moderate_id)

    denominators = _registered_json(
        dry_id, "denominators",
        lambda value: value["quantities"]["sample"].update(weight=1.0),
    )
    stats = read_json(report.RUNS_DIR / dry_id / "stats.json")
    stats["denominators"] = denominators
    write_json(report.RUNS_DIR / dry_id / "stats.json", stats)
    with pytest.raises(ValueError, match="audit failed"):
        report.load_checked_pair(dry_id, moderate_id)
