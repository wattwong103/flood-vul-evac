"""A real publication must survive its own Parquet/manifest readback.

Every other API fixture hand-writes a run directory, which proves the shape of
a response but not that the pipeline's real artefacts survive the round-trip
both clearance routes perform: ``/stats`` reconstructs clearance through
``reconcile_stats_clearance`` and ``/evacuation`` through ``_clearance_times``.

Arrival times are ``float`` seconds, so a reader that coerced the column to a
whole number, divided on truncated values, or reported absolute event time
instead of time since the warning would pass every existing fixture while
returning quietly wrong quantiles. This test publishes a genuine run, then
reads only what was written to disk and recomputes the weighted-clearance
definition independently.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from pipeline.bkkflow.evacuation import validate_denominator_contract

# The staging fixture that builds a complete, publishable pilot lives with the
# pilot tests. Reusing it keeps this round-trip test honest about running the
# real pipeline rather than a hand-built directory.
_PIPELINE_PKG = Path(__file__).resolve().parents[2] / "pipeline"
_PIPELINE_TESTS = _PIPELINE_PKG / "tests"
for _extra in (_PIPELINE_PKG, _PIPELINE_TESTS):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

# The fixture redirects the runner's staged-input directories by patching this
# top-level module object. Importing ``pipeline.bkkflow.runner`` instead would
# build a second, unpatched copy and silently read the real ``data/curated``.
from bkkflow import runner  # noqa: E402
from test_pilot_publication import pilot_inputs  # noqa: E402,F401

QUANTILES = (("p5", 0.05), ("median", 0.50), ("p95", 0.95))

#: A coarse sanity ceiling only. The warning sits at 64,800 s (1080 minutes), so
#: absolute event time would land just under this bound; the load-bearing
#: warning-relative assertion is the explicit comparison further down.
MAX_PLAUSIBLE_CLEARANCE_MINUTES = 24 * 60

FATAL_WARNING_CODES = {
    "missing_artefact",
    "unreadable_artefact",
    "schema_mismatch",
    "empty_table",
    "invalid_denominator_contract",
    "missing_warning_time",
    "invalid_clearance_data",
}


def _independent_clearance_minutes(
    states: pd.DataFrame, warning_time_s: float
) -> dict[str, float]:
    """The documented inverse weighted-ECDF, recomputed from saved rows only.

    Deliberately does not call the pipeline's helper: a shared implementation
    would agree with itself and prove nothing. For each quantile the answer is
    the first observed clearance whose cumulative weight reaches ``q`` of the
    arrived weight, with no replication, rounding or interpolation.
    """
    arrived = states.loc[states["state"] == "arrived"]
    assert not arrived.empty, "the published run must contain arrived rows"
    ordered = sorted(
        (float(row.event_time_s) - warning_time_s, float(row.weight))
        for row in arrived.itertuples()
    )
    assert all(weight > 0 for _, weight in ordered)
    total = math.fsum(weight for _, weight in ordered)

    result: dict[str, float] = {}
    for label, quantile in QUANTILES:
        cumulative = 0.0
        for clearance, weight in ordered:
            cumulative += weight
            if cumulative >= quantile * total:
                result[label] = clearance / 60.0
                break
        assert label in result, f"no clearance reached quantile {label}"
    return result


def _service_warning_codes(body: dict) -> set[str]:
    """Codes of the warnings the service itself raised.

    ``/stats`` passes the pipeline's own saved warnings through verbatim as
    strings and appends its own as objects, so only the object form identifies
    a degradation this service introduced.
    """
    codes = set()
    for warning in body.get("warnings", []):
        if isinstance(warning, dict):
            codes.add(str(warning.get("code")))
    return codes


@pytest.fixture
def published_run(pilot_inputs, monkeypatch):  # noqa: F811
    """Publish a real run and point the service at the directory holding it."""
    result = runner.execute_run(
        run_id="roundtrip",
        pilot_id="khlong-san-district",
        flood_enabled=True,
        max_agents=10,
    )
    run_dir = Path(result["run_dir"])
    assert result["validation_passed"]
    assert json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))[
        "state"
    ] == "published"
    monkeypatch.setenv("BKKFLOW_RUNS_DIR", str(run_dir.parent))
    return run_dir


def test_published_fractional_seconds_survive_both_clearance_routes(published_run):
    """Both routes reproduce the pipeline's own clearance from saved artefacts."""
    states = pd.read_parquet(published_run / "evacuation_states.parquet")
    manifest = json.loads((published_run / "manifest.json").read_text(encoding="utf-8"))
    saved_stats = json.loads((published_run / "stats.json").read_text(encoding="utf-8"))
    warning_time_s = manifest["evacuation_scenario"]["departure_model"]["warning_time_s"]

    # Anti-vacuity: the fixture must really exercise fractional seconds, and the
    # resulting minutes must not be whole numbers a truncation bug could fake.
    arrived_events = states.loc[states["state"] == "arrived", "event_time_s"]
    assert len(arrived_events) >= 2
    assert (arrived_events % 1 != 0).all(), (
        "expected genuinely fractional arrival seconds in a published run"
    )

    expected = _independent_clearance_minutes(states, float(warning_time_s))
    assert all(
        abs(value - round(value)) > 1e-9 for value in expected.values()
    ), "clearance minutes must not be whole numbers"

    # Measured against absolute event time these same rows are 1080 minutes
    # larger, which would still clear a coarse magnitude bound. Assert the two
    # readings are genuinely distinct rather than trusting a plausibility
    # ceiling to separate them.
    absolute = _independent_clearance_minutes(states, 0.0)
    assert all(
        abs(expected[label] - absolute[label]) > 1.0 for label, _ in QUANTILES
    ), "clearance must be measured from the warning, not from absolute event time"
    assert max(expected.values()) < MAX_PLAUSIBLE_CLEARANCE_MINUTES

    client = TestClient(create_app())
    stats_response = client.get("/v1/runs/roundtrip/stats")
    evacuation_response = client.get("/v1/runs/roundtrip/evacuation")
    assert stats_response.status_code == 200
    assert evacuation_response.status_code == 200
    stats_body = stats_response.json()
    evacuation_body = evacuation_response.json()

    pipeline_clearance = saved_stats["evacuation"]["clearance_time_minutes"]
    stats_clearance = stats_body["evacuation"]["clearance_time_minutes"]
    evacuation_clearance = evacuation_body["clearance_time_minutes"]

    for label, _ in QUANTILES:
        assert pipeline_clearance[label] == pytest.approx(expected[label], abs=1e-6)
        assert stats_clearance[label] == pytest.approx(expected[label], abs=1e-6)
        assert evacuation_clearance[label] == pytest.approx(expected[label], abs=1e-6)

    # One definition, one answer: the two routes must not disagree with each other.
    assert stats_clearance == evacuation_clearance

    for body, label in ((stats_body, "stats"), (evacuation_body, "evacuation")):
        raised = _service_warning_codes(body) & FATAL_WARNING_CODES
        assert not raised, (
            f"{label} degraded a readable published run: {sorted(raised)}"
        )


def test_published_run_serves_the_canonical_non_null_denominator_contract(published_run):
    """The contract is read from the publication, never reconstructed or nulled."""
    saved_stats = json.loads((published_run / "stats.json").read_text(encoding="utf-8"))
    saved_contract = saved_stats["denominators"]
    assert saved_contract is not None, "a published run must save its contract"

    client = TestClient(create_app())
    stats_contract = client.get("/v1/runs/roundtrip/stats").json()["denominators"]
    evacuation_body = client.get("/v1/runs/roundtrip/evacuation").json()
    evacuation_contract = evacuation_body["denominators"]

    canonical = validate_denominator_contract(saved_contract)
    assert stats_contract == canonical
    assert evacuation_contract == canonical
    assert stats_contract["scope"]["reweighting_to_full_population"] is False

    quantities = canonical["quantities"]
    assert quantities["cohort"]["weight"] > 0
    arrived_weight = quantities["terminal_states"]["arrived"]["weight"]
    assert arrived_weight > 0, "the contract must report the arrived weight it uses"

    # The same arrived weight must back the clearance quantiles both routes report.
    assert evacuation_body["totals"]["arrived_weighted"] == pytest.approx(
        arrived_weight, abs=1e-6
    )