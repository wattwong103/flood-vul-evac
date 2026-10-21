"""Contract tests for ``GET /v1/runs/{id}/flood-summary`` (BKK-055b).

The summary answers three questions for one model time: how big the flood is,
how deep it is, and whether roads are still usable on foot and by car. Every
test builds its own synthetic run directory, as ``test_api.py`` does.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.app import create_app

THRESHOLDS = "bkk-demo-thresholds-v0.1"
CELL_KM2 = 0.05 * 0.05  # one 50 m flood cell


def _manifest(run_id: str, *, peak_depth_m: float | None = 0.55) -> dict:
    flood_scenario: dict = {
        "model_name": "bkk-scenario-depth-decay",
        "model_version": "0.1.0",
        "time_step_seconds": 300,
    }
    if peak_depth_m is not None:
        flood_scenario["parameters"] = {
            "severity": "moderate",
            "source_role": "scenario",
            "peak_depth_m": peak_depth_m,
        }
    return {
        "run_id": run_id,
        "created_at": "2026-01-01T00:00:00+00:00",
        "validation_status": "demonstration",
        "geography": {"aoi_id": "khlong-san-district", "analysis_crs": "EPSG:32647"},
        "flood_scenario": flood_scenario,
        "outputs": [],
        "warnings": [],
    }


def _write_run(
    root: Path,
    run_id: str,
    *,
    manifest: dict | None = None,
    tables: dict[str, pd.DataFrame] | None = None,
    stats: dict | None = None,
) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest or _manifest(run_id)), encoding="utf-8"
    )
    (run_dir / "run_state.json").write_text(
        json.dumps({"stage": "completed", "progress": 1.0, "warnings": [], "stages": []}),
        encoding="utf-8",
    )
    for name, frame in (tables or {}).items():
        frame.to_parquet(run_dir / f"{name}.parquet", index=False)
    if stats is not None:
        (run_dir / "stats.json").write_text(json.dumps(stats), encoding="utf-8")


def _flood_slices() -> pd.DataFrame:
    """Four 50 m cells; the deepest moment is t=300."""
    xs = [662000.0, 662050.0, 662100.0, 662150.0]
    return pd.DataFrame(
        {
            "cell_id": ["c1", "c2", "c3", "c4"] * 2,
            "x": xs * 2,
            "y": [1520000.0] * 8,
            "time_s": [0] * 4 + [300] * 4,
            "depth_m": [0.05, 0.10, 0.20, 0.30, 0.10, 0.20, 0.40, 0.60],
            "source_role": ["scenario"] * 8,
            "confidence": [0.0] * 8,
        }
    )


def _network_edges() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "edge_id": ["e1", "e2", "e3"],
            "length_m": [100.0, 200.0, 300.0],
            "walk_allowed": [True, True, True],
            "vehicle_allowed": [True, True, False],
        }
    )


def _edge_states(version: str = THRESHOLDS) -> pd.DataFrame:
    """At t=300 walking sees open/slowed/closed; cars see slowed/closed."""
    rows = [
        # edge, time, mode, speed, closed
        ("e1", 0, 0, 1.0, False),
        ("e2", 0, 0, 1.0, False),
        ("e3", 0, 0, 1.0, False),
        ("e1", 0, 3, 1.0, False),
        ("e2", 0, 3, 1.0, False),
        ("e3", 0, 3, 1.0, False),
        ("e1", 300, 0, 1.0, False),
        ("e2", 300, 0, 0.5, False),
        ("e3", 300, 0, 0.0, True),
        ("e1", 300, 3, 0.5, False),
        ("e2", 300, 3, 0.0, True),
        ("e3", 300, 3, 0.0, True),  # not vehicle-allowed: must not count
    ]
    edge_id, time_s, mode, speed, closed = zip(*rows)
    return pd.DataFrame(
        {
            "edge_id": edge_id,
            "time_s": time_s,
            "mode": mode,
            "depth_m": [0.0] * len(rows),
            "speed_multiplier": speed,
            "capacity_multiplier": speed,
            "closed": closed,
            "threshold_set_version": [version] * len(rows),
            "reason_code": [None] * len(rows),
        }
    )


def _what_if_tables() -> dict[str, pd.DataFrame]:
    return {
        "flood_slices": _flood_slices(),
        "network_edges": _network_edges(),
        "edge_states": _edge_states(),
    }


AOI_STATS = {"geography": {"area_km2": 0.01}}


@pytest.fixture
def runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    monkeypatch.setenv("BKKFLOW_RUNS_DIR", str(root))
    return root


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _mode(body: dict, name: str) -> dict:
    return next(entry for entry in body["movement"]["modes"] if entry["mode_name"] == name)


def test_what_if_summary_reports_size_depth_and_movement(client, runs_dir) -> None:
    _write_run(runs_dir, "wi", tables=_what_if_tables(), stats=AOI_STATS)

    body = client.get("/v1/runs/wi/flood-summary?time=300").json()

    assert body["validation_status"] == "demonstration"
    assert body["source_role"] == "scenario"
    assert body["threshold_set_version"] == THRESHOLDS
    assert body["time_s"] == 300 and body["time_defaulted"] is False
    # How big: three cells reach 0.15 m; the 0.10 m cell does not.
    assert body["flood_area_threshold_m"] == 0.15
    big = body["how_big"]
    assert big["cell_size_m"] == pytest.approx(50.0)
    assert big["flooded_area_km2"] == pytest.approx(3 * CELL_KM2)
    assert big["share_of_aoi"] == pytest.approx(0.75)
    assert big["reason"] is None
    # How deep: walking stops at 0.50 m (one cell), cars at 0.30 m (two cells).
    deep = body["how_deep"]
    assert deep["max_depth_m"] == pytest.approx(0.60)
    stops = {entry["mode_name"]: entry for entry in deep["at_or_above_closing_depth"]}
    assert stops["walk"]["closed_depth_m"] == pytest.approx(0.50)
    assert stops["walk"]["area_km2"] == pytest.approx(1 * CELL_KM2)
    assert stops["car"]["closed_depth_m"] == pytest.approx(0.30)
    assert stops["car"]["area_km2"] == pytest.approx(2 * CELL_KM2)
    # Can people move: road length by state, for roads that mode may use.
    walk, car = _mode(body, "walk"), _mode(body, "car")
    assert walk["total_km"] == pytest.approx(0.6)
    assert (walk["open_km"], walk["slowed_km"], walk["closed_km"]) == pytest.approx(
        (0.1, 0.2, 0.3)
    )
    assert walk["closed_share"] == pytest.approx(0.5)
    assert car["total_km"] == pytest.approx(0.3)
    assert (car["open_km"], car["slowed_km"], car["closed_km"]) == pytest.approx(
        (0.0, 0.1, 0.2)
    )


def test_default_time_is_the_peak_and_says_so(client, runs_dir) -> None:
    _write_run(runs_dir, "wi", tables=_what_if_tables(), stats=AOI_STATS)

    body = client.get("/v1/runs/wi/flood-summary").json()

    assert body["time_s"] == 300
    assert body["peak_time_s"] == 300
    assert body["time_defaulted"] is True
    assert body["available_times"] == [0, 300]


def test_dry_run_reports_zero_as_a_declared_scenario_value(client, runs_dir) -> None:
    tables = _what_if_tables()
    tables["flood_slices"] = _flood_slices().iloc[0:0]
    tables["edge_states"] = _edge_states().assign(speed_multiplier=1.0, closed=False)
    _write_run(
        runs_dir, "dry", manifest=_manifest("dry", peak_depth_m=0.0), tables=tables,
        stats=AOI_STATS,
    )

    body = client.get("/v1/runs/dry/flood-summary?time=300").json()

    assert body["how_big"]["flooded_area_km2"] == 0.0
    assert body["how_big"]["share_of_aoi"] == 0.0
    assert body["how_big"]["reason"] == "declared dry scenario"
    assert body["how_deep"]["max_depth_m"] == 0.0
    assert _mode(body, "walk")["closed_km"] == 0.0


def test_run_without_a_flood_layer_returns_nulls_with_reasons(client, runs_dir) -> None:
    reason = "No city-scale flood layer in this run."
    _write_run(
        runs_dir,
        "city",
        manifest=_manifest("city", peak_depth_m=None),
        tables={"network_edges": _network_edges()},
        stats={"flood": {"depth_reason": reason}},
    )

    body = client.get("/v1/runs/city/flood-summary").json()

    assert body["available"] is False
    assert body["how_big"]["flooded_area_km2"] is None
    assert body["how_big"]["reason"] == reason
    assert body["how_deep"]["max_depth_m"] is None
    assert body["how_deep"]["reason"] == reason
    assert body["movement"]["modes"] == []
    assert body["movement"]["reason"]


def test_time_without_model_state_is_null_not_zero(client, runs_dir) -> None:
    _write_run(runs_dir, "wi", tables=_what_if_tables(), stats=AOI_STATS)

    body = client.get("/v1/runs/wi/flood-summary?time=900").json()

    assert body["how_big"]["flooded_area_km2"] is None
    assert "900" in body["how_big"]["reason"]
    assert body["movement"]["modes"] == []
    assert any(warning["code"] == "time_not_available" for warning in body["warnings"])


def test_unknown_threshold_set_leaves_closing_depth_null(client, runs_dir) -> None:
    tables = _what_if_tables()
    tables["edge_states"] = _edge_states(version="v-unknown")
    _write_run(runs_dir, "wi", tables=tables, stats=AOI_STATS)

    body = client.get("/v1/runs/wi/flood-summary?time=300").json()

    stops = {entry["mode_name"]: entry for entry in body["how_deep"]["at_or_above_closing_depth"]}
    assert stops["walk"]["closed_depth_m"] is None
    assert stops["walk"]["area_km2"] is None
    # Road states still come from the stored closed flag, not the thresholds.
    assert _mode(body, "walk")["closed_km"] == pytest.approx(0.3)
    assert any(warning["code"] == "unknown_threshold_set" for warning in body["warnings"])


def test_edges_without_a_state_are_unknown_not_open(client, runs_dir) -> None:
    tables = _what_if_tables()
    tables["network_edges"] = pd.concat(
        [
            _network_edges(),
            pd.DataFrame(
                {"edge_id": ["e4"], "length_m": [400.0], "walk_allowed": [True],
                 "vehicle_allowed": [True]}
            ),
        ],
        ignore_index=True,
    )
    _write_run(runs_dir, "wi", tables=tables, stats=AOI_STATS)

    walk = _mode(client.get("/v1/runs/wi/flood-summary?time=300").json(), "walk")

    assert walk["total_km"] == pytest.approx(1.0)
    assert walk["open_km"] == pytest.approx(0.1)
    assert walk["unknown_km"] == pytest.approx(0.4)


def test_area_is_null_when_the_cell_size_cannot_be_inferred(client, runs_dir) -> None:
    tables = _what_if_tables()
    tables["flood_slices"] = _flood_slices().iloc[[7]]  # one cell, one time
    _write_run(runs_dir, "wi", tables=tables, stats=AOI_STATS)

    body = client.get("/v1/runs/wi/flood-summary?time=300").json()

    assert body["how_big"]["flooded_area_km2"] is None
    assert "cell size" in body["how_big"]["reason"]
    assert body["how_deep"]["max_depth_m"] == pytest.approx(0.60)


def test_share_is_null_when_the_aoi_area_is_not_recorded(client, runs_dir) -> None:
    _write_run(runs_dir, "wi", tables=_what_if_tables())

    big = client.get("/v1/runs/wi/flood-summary?time=300").json()["how_big"]

    assert big["flooded_area_km2"] == pytest.approx(3 * CELL_KM2)
    assert big["share_of_aoi"] is None
    assert big["aoi_area_km2"] is None


def test_unknown_run_is_404(client, runs_dir) -> None:
    response = client.get("/v1/runs/nope/flood-summary")

    assert response.status_code == 404
    assert response.json()["run_id"] == "nope"
