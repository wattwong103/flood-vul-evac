"""API contract tests.

Every test builds its own synthetic run directory, so the suite never reads or
writes the real ``runs/`` tree and can run while a pipeline is producing one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.app import create_app

# ---------------------------------------------------------------------------
# Contract section 4 key sets, spelled out so a missing or renamed field fails.
# ---------------------------------------------------------------------------

STATS_TOP_LEVEL = {
    "run_id",
    "validation_status",
    "created_at",
    "geography",
    "population",
    "flood",
    "evacuation",
    "stages",
    "warnings",
    "sources",
}
STATS_GEOGRAPHY = {"aoi_id", "name", "area_km2", "analysis_crs"}
STATS_POPULATION = {
    "residents_weighted",
    "people_present",
    "people_exposed",
    "exposed_share_of_present",
    "population_version",
    "time_profile",
}
STATS_FLOOD = {
    "max_depth_m",
    "flooded_area_km2",
    "edges_closed",
    "edges_total",
    "road_capacity_loss_share",
    "source_role",
    "model",
}
STATS_EVACUATION = {
    "cohort_weighted",
    "arrived_weighted",
    "unserved_weighted",
    "clearance_time_minutes",
    "top_bottleneck_edges",
}
STATS_CLEARANCE = {"p5", "median", "p95"}
STATS_MODEL = {"name", "version"}


def _manifest(run_id: str, created_at: str = "2026-01-01T00:00:00+00:00") -> dict:
    return {
        "run_id": run_id,
        "created_at": created_at,
        "validation_status": "demonstration",
        "geography": {
            "country": "Thailand",
            "aoi_id": "khlong-san-district",
            "aoi_version": "v1",
            "storage_crs": "OGC:CRS84",
            "analysis_crs": "EPSG:32647",
        },
        "source_versions": [
            {
                "source_id": "osm-thailand-geofabrik",
                "retrieved_at": created_at,
                "content_sha256": "a" * 64,
                "licence_snapshot": "ODbL 1.0",
            }
        ],
        "population_model": {
            "population_version": "synth-2026-01",
            "method": "weighted-persons",
            "time_profile": {"status": "illustrative"},
        },
        "flood_scenario": {
            "model_name": "synthetic-bma",
            "model_version": "0.1",
            "time_step_seconds": 300,
        },
        "outputs": [],
        "warnings": [],
    }


def _run_state(stage: str = "completed") -> dict:
    return {
        "stage": stage,
        "progress": 1.0,
        "warnings": [],
        "stages": [{"stage": "population", "status": stage, "seconds": 1.5, "rows": 3}],
    }


def _write_run(root: Path, run_id: str, **kwargs) -> Path:
    """Create a run directory, optionally with tables and side artefacts."""
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = kwargs.pop("manifest", None) or _manifest(run_id)
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    if kwargs.pop("run_state", True):
        (run_dir / "run_state.json").write_text(
            json.dumps(_run_state(), ensure_ascii=False), encoding="utf-8"
        )
    for name, payload in kwargs.pop("tables", {}).items():
        payload.to_parquet(run_dir / f"{name}.parquet", index=False)
    for name, payload in kwargs.pop("json_files", {}).items():
        (run_dir / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    return run_dir


@pytest.fixture
def runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    monkeypatch.setenv("BKKFLOW_RUNS_DIR", str(root))
    return root


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Service endpoints
# ---------------------------------------------------------------------------


def test_health_returns_200(client: TestClient, runs_dir: Path) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["contract_version"] == "bkkflow-run-v0.1"
    assert body["runs_dir_exists"] is True
    assert body["run_count"] == 0


@pytest.mark.parametrize("endpoint,table", [("observed-water/cells", "observed_water_cells"),
                                            ("destinations", "destinations")])
def test_city_layers_use_only_the_selected_runs_snapshot(client, runs_dir, tmp_path, monkeypatch, endpoint, table):
    shared = tmp_path / "data" / "curated" / "city"
    shared.mkdir(parents=True)
    monkeypatch.setenv("BKKFLOW_DATA_DIR", str(tmp_path / "data"))
    def rows(label):
        return pd.DataFrame([{"cell_id": label, "year": 2020, "water_share": 0.5,
            "water_km2": 0.5, "lon": 100.5, "lat": 13.7, "destination_id": label,
            "destination_class": "education", "verified": False}])
    rows("shared-other-run").to_parquet(shared / f"{table}.parquet", index=False)
    _write_run(runs_dir, "snapshot", tables={table: rows("selected-run")})
    _write_run(runs_dir, "legacy-no-snapshot")
    result = client.get(f"/v1/runs/snapshot/{endpoint}")
    assert result.status_code == 200
    assert "selected-run" in result.text and "shared-other-run" not in result.text
    old = client.get(f"/v1/runs/legacy-no-snapshot/{endpoint}").json()
    assert old["available"] is False


def test_health_reports_missing_runs_directory(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BKKFLOW_RUNS_DIR", str(tmp_path / "absent"))
    body = client.get("/v1/health").json()
    assert body["runs_dir_exists"] is False


def test_sources_are_served(client: TestClient) -> None:
    response = client.get("/v1/sources")
    assert response.status_code == 200
    body = response.json()
    assert body["sources"]
    first = body["sources"][0]
    assert {"source_id", "agency", "dataset", "licence", "status"} <= set(first)


def test_config_reports_pilot_area(client: TestClient) -> None:
    body = client.get("/v1/config").json()
    assert body["aoi"]["aoi_id"]
    assert body["analysis_crs"]
    assert "aggregation_grid" in body
    assert "scenario" in body


def test_bangkok_study_area_serves_the_full_city_boundary(client: TestClient) -> None:
    response = client.get("/v1/areas/bangkok")

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert body["area_id"] == "bangkok-bma"
    assert body["area_name"] == "Bangkok"
    assert body["area_km2"] == pytest.approx(1643.5357)
    assert body["bbox_wgs84"] == pytest.approx([100.3279, 13.2191, 100.9386, 13.9552])
    assert body["features"]
    assert body["features"][0]["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    assert body["features"][0]["properties"]["scope"] == "study_area"


# ---------------------------------------------------------------------------
# Run lookup errors
# ---------------------------------------------------------------------------


def test_unknown_run_returns_404_with_error_body(
    client: TestClient, runs_dir: Path
) -> None:
    response = client.get("/v1/runs/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]
    assert body["run_id"] == "does-not-exist"


def test_unknown_run_404_on_every_run_scoped_endpoint(
    client: TestClient, runs_dir: Path
) -> None:
    for path in (
        "/v1/runs/nope",
        "/v1/runs/nope/stats",
        "/v1/runs/nope/mesh",
        "/v1/runs/nope/flood",
        "/v1/runs/nope/links",
        "/v1/runs/nope/buildings",
        "/v1/runs/nope/evacuation",
        "/v1/runs/nope/routes",
        "/v1/runs/nope/validation",
        "/v1/runs/nope/export",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json()["run_id"] == "nope", path


def test_path_traversal_run_id_is_refused(
    client: TestClient, runs_dir: Path
) -> None:
    response = client.get("/v1/runs/..%2F..%2Fetc")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Run listing and discovery resilience
# ---------------------------------------------------------------------------


def test_runs_are_listed_newest_first(client: TestClient, runs_dir: Path) -> None:
    _write_run(runs_dir, "old", manifest=_manifest("old", "2026-01-01T00:00:00+00:00"))
    _write_run(runs_dir, "new", manifest=_manifest("new", "2026-06-01T00:00:00+00:00"))
    _write_run(runs_dir, "mid", manifest=_manifest("mid", "2026-03-01T00:00:00+00:00"))

    body = client.get("/v1/runs").json()
    assert body["count"] == 3
    assert [run["run_id"] for run in body["runs"]] == ["new", "mid", "old"]
    assert body["runs"][0]["validation_status"] == "demonstration"
    assert body["runs"][0]["stage"] == "completed"
    assert body["runs"][0]["population_version"] == "synth-2026-01"


def test_run_state_falls_back_to_overall_state(client: TestClient, runs_dir: Path) -> None:
    """A run_state may record only an overall state. ``stage`` still reports
    something useful, and ``state`` is exposed separately rather than conflated."""
    run_dir = _write_run(runs_dir, "stately", run_state=False)
    (run_dir / "run_state.json").write_text(
        json.dumps({"run_id": "stately", "state": "failed_validation", "warnings": []}),
        encoding="utf-8",
    )
    summary = client.get("/v1/runs").json()["runs"][0]
    assert summary["state"] == "failed_validation"
    assert summary["stage"] == "failed_validation"


def test_corrupt_manifest_is_skipped_not_fatal(client: TestClient, runs_dir: Path) -> None:
    _write_run(runs_dir, "good", manifest=_manifest("good", "2026-06-01T00:00:00+00:00"))
    broken = runs_dir / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("{ this is not json", encoding="utf-8")

    response = client.get("/v1/runs")
    assert response.status_code == 200
    body = response.json()
    assert [run["run_id"] for run in body["runs"]] == ["good"]
    assert "broken" in body["skipped"]
    assert any(warning["code"] == "skipped_run" for warning in body["warnings"])


def test_corrupt_manifest_run_id_is_404_not_500(
    client: TestClient, runs_dir: Path
) -> None:
    broken = runs_dir / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("not json at all", encoding="utf-8")

    response = client.get("/v1/runs/broken/stats")
    assert response.status_code == 404
    assert response.json()["run_id"] == "broken"


def test_directory_without_manifest_is_ignored(client: TestClient, runs_dir: Path) -> None:
    (runs_dir / "not-a-run").mkdir()
    _write_run(runs_dir, "real")
    body = client.get("/v1/runs").json()
    assert [run["run_id"] for run in body["runs"]] == ["real"]
    assert body["skipped"] == []


def test_run_with_unreadable_run_state_is_still_listed(
    client: TestClient, runs_dir: Path
) -> None:
    run_dir = _write_run(runs_dir, "partial", run_state=False)
    (run_dir / "run_state.json").write_text("{ truncated", encoding="utf-8")

    body = client.get("/v1/runs").json()
    assert [run["run_id"] for run in body["runs"]] == ["partial"]
    assert body["runs"][0]["stage"] is None


def test_unreadable_parquet_is_a_warning_not_a_crash(
    client: TestClient, runs_dir: Path
) -> None:
    run_dir = _write_run(runs_dir, "torn")
    (run_dir / "mesh_volume.parquet").write_bytes(b"PAR1 truncated garbage")

    response = client.get("/v1/runs/torn/mesh?time=0")
    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == []
    assert any(
        warning["code"] == "unreadable_artefact" for warning in body["warnings"]
    )


# ---------------------------------------------------------------------------
# Stats payload
# ---------------------------------------------------------------------------


def test_stats_payload_has_the_exact_contract_keys(
    client: TestClient, runs_dir: Path
) -> None:
    _write_run(runs_dir, "run-a", manifest=_manifest("run-a"))
    body = client.get("/v1/runs/run-a/stats").json()

    assert set(body) == STATS_TOP_LEVEL
    assert set(body["geography"]) == STATS_GEOGRAPHY
    assert set(body["population"]) == STATS_POPULATION
    assert set(body["flood"]) == STATS_FLOOD
    assert set(body["flood"]["model"]) == STATS_MODEL
    assert set(body["evacuation"]) == STATS_EVACUATION
    assert set(body["evacuation"]["clearance_time_minutes"]) == STATS_CLEARANCE
    assert body["run_id"] == "run-a"
    assert body["validation_status"] == "demonstration"


def test_missing_stats_json_yields_nulls_not_zeros(
    client: TestClient, runs_dir: Path
) -> None:
    _write_run(runs_dir, "bare", manifest=_manifest("bare"))
    body = client.get("/v1/runs/bare/stats").json()

    assert set(body) == STATS_TOP_LEVEL
    # A value that could not be computed is null. Zero would claim a measurement.
    assert body["population"]["residents_weighted"] is None
    assert body["population"]["people_present"] is None
    assert body["population"]["people_exposed"] is None
    assert body["population"]["exposed_share_of_present"] is None
    assert body["flood"]["max_depth_m"] is None
    assert body["flood"]["edges_total"] is None
    assert body["evacuation"]["cohort_weighted"] is None
    assert body["evacuation"]["clearance_time_minutes"] == {
        "p5": None,
        "median": None,
        "p95": None,
    }
    # Manifest-derived values are copied, not recomputed.
    assert body["population"]["population_version"] == "synth-2026-01"
    assert body["geography"]["aoi_id"] == "khlong-san-district"
    assert body["geography"]["analysis_crs"] == "EPSG:32647"
    assert body["flood"]["model"] == {"name": "synthetic-bma", "version": "0.1"}


def test_stats_json_is_served_verbatim_when_present(
    client: TestClient, runs_dir: Path
) -> None:
    authored = {
        "run_id": "authored",
        "validation_status": "research",
        "created_at": "2026-02-02T00:00:00+00:00",
        "geography": {
            "aoi_id": "khlong-san-district",
            "name": "authored",
            "area_km2": 1.25,
            "analysis_crs": "EPSG:32647",
        },
        "population": {
            "residents_weighted": 1000.0,
            "people_present": 800.0,
            "people_exposed": 120.0,
            "exposed_share_of_present": 0.15,
            "population_version": "synth-2026-02",
            "time_profile": "evening",
        },
        "flood": {
            "max_depth_m": 0.9,
            "flooded_area_km2": 0.4,
            "edges_closed": 3,
            "edges_total": 40,
            "road_capacity_loss_share": 0.2,
            "source_role": "scenario",
            "model": {"name": "synthetic-bma", "version": "0.1"},
        },
        "evacuation": {
            "cohort_weighted": 120.0,
            "arrived_weighted": 100.0,
            "unserved_weighted": 20.0,
            "clearance_time_minutes": {"p5": 4.0, "median": 11.0, "p95": 30.0},
            "top_bottleneck_edges": [],
        },
        "stages": [],
        "warnings": [],
        "sources": [],
        "field_added_after_contract_freeze": "kept",
    }
    _write_run(runs_dir, "authored", manifest=_manifest("authored"), json_files={"stats": authored})

    body = client.get("/v1/runs/authored/stats").json()
    assert body == authored
    # Passthrough must not be trimmed to the frozen key set.
    assert body["field_added_after_contract_freeze"] == "kept"


def test_routes_serves_aggregate_evacuation_bottlenecks_not_person_paths(
    client: TestClient, runs_dir: Path
) -> None:
    stats = {
        "run_id": "route-map",
        "validation_status": "demonstration",
        "evacuation": {
            "top_bottleneck_edges": [
                {"edge_id": "edge-2", "traversal_weight": 42.5},
                {"edge_id": "edge-1", "traversal_weight": 20.0},
            ]
        },
    }
    edges = pd.DataFrame(
        {
            "edge_id": ["edge-1", "edge-2"],
            "u": [1, 2],
            "v": [2, 3],
            "length_m": [100.0, 150.0],
            "geometry_wkt": [
                "LINESTRING (662000 1520000, 662100 1520000)",
                "LINESTRING (662100 1520000, 662250 1520000)",
            ],
        }
    )
    _write_run(
        runs_dir,
        "route-map",
        manifest=_manifest("route-map"),
        tables={"network_edges": edges},
        json_files={"stats": stats},
    )

    body = client.get("/v1/runs/route-map/routes").json()

    assert body["type"] == "FeatureCollection"
    assert body["available"] is True
    assert body["returned"] == 2
    assert body["features"][0]["properties"] == {
        "edge_id": "edge-2",
        "traversal_weight": 42.5,
        "route_quantity": "aggregate_evacuation_bottleneck",
    }
    assert body["features"][0]["geometry"]["type"] == "LineString"
    assert "person_id" not in body["features"][0]["properties"]


def test_people_present_and_people_exposed_stay_separate(
    client: TestClient, runs_dir: Path
) -> None:
    persons = pd.DataFrame(
        {
            "person_id": ["p1", "p2", "p3"],
            "weight": [2.0, 3.0, 5.0],
            "lon": [100.5, 100.5, 100.5],
            "lat": [13.7, 13.7, 13.7],
        }
    )
    activities = pd.DataFrame(
        {
            "person_id": ["p1", "p2", "p3"],
            "gcode": ["10101", "10102", "10102"],
            "lon": [100.5, 100.5, 100.5],
            "lat": [13.7, 13.7, 13.7],
        }
    )
    slices = pd.DataFrame(
        {"cell_id": ["10102"], "depth_m": [0.4], "time_s": [0], "source_role": ["scenario"]}
    )
    _write_run(
        runs_dir,
        "split",
        manifest=_manifest("split"),
        tables={"persons": persons, "activities": activities, "flood_slices": slices},
    )

    population = client.get("/v1/runs/split/stats").json()["population"]
    assert population["residents_weighted"] == 10.0
    assert population["people_present"] == 10.0
    assert population["people_exposed"] == 8.0
    assert population["exposed_share_of_present"] == pytest.approx(0.8)
    assert population["people_present"] != population["people_exposed"]


def test_stats_clearance_percentiles_are_in_minutes(
    client: TestClient, runs_dir: Path
) -> None:
    """Event times are seconds; the contract field is minutes. A 60x error here
    would be printed by the site as a fact, so it is asserted directly."""
    states = pd.DataFrame(
        {
            "person_id": ["p1", "p2", "p3"],
            "state": ["arrived", "arrived", "arrived"],
            "event_time_s": [600.0, 1200.0, 1800.0],
            "weight": [1.0, 1.0, 1.0],
        }
    )
    _write_run(
        runs_dir, "ct", manifest=_manifest("ct"), tables={"evacuation_states": states}
    )
    clearance = client.get("/v1/runs/ct/stats").json()["evacuation"][
        "clearance_time_minutes"
    ]
    assert clearance["p5"] == pytest.approx(11.0)
    assert clearance["median"] == pytest.approx(20.0)
    assert clearance["p95"] == pytest.approx(29.0)


def test_stats_caches_by_mtime(client: TestClient, runs_dir: Path) -> None:
    _write_run(runs_dir, "cached", manifest=_manifest("cached"))
    first = client.get("/v1/runs/cached/stats").json()
    second = client.get("/v1/runs/cached/stats").json()
    assert first == second


# ---------------------------------------------------------------------------
# Mesh
# ---------------------------------------------------------------------------


def _mesh_frame(rows: int = 10) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "run_id": ["r"] * rows,
            "gcode": [f"1010{i}" for i in range(rows)],
            "mesh_size_m": [500] * rows,
            "time_s": [3600] * rows,
            "stationary_pop": [float(i) for i in range(rows)],
            "travelling_pop": [float(i) + 0.5 for i in range(rows)],
            "total_pop": [float(i) * 2 + 0.5 for i in range(rows)],
        }
    )


def test_mesh_returns_rows_for_a_time_slice(
    client: TestClient, runs_dir: Path
) -> None:
    _write_run(
        runs_dir, "mesh-run", manifest=_manifest("mesh-run"), tables={"mesh_volume": _mesh_frame()}
    )
    body = client.get("/v1/runs/mesh-run/mesh?time=3600").json()
    assert body["time_s"] == 3600
    assert body["returned"] == 10
    assert body["truncated"] is False
    row = body["rows"][0]
    assert {"gcode", "lat", "lon", "time_s", "stationary_pop", "travelling_pop", "total_pop"} == set(row)
    # No cell-centre artefact exists, so coordinates are null rather than invented.
    assert row["lat"] is None and row["lon"] is None
    assert body["type"] == "FeatureCollection"
    assert body["features"] == []
    assert any(warning["code"] == "missing_geometry" for warning in body["warnings"])


def test_mesh_filters_to_the_requested_time(client: TestClient, runs_dir: Path) -> None:
    frame = _mesh_frame(6)
    frame["time_s"] = [3600, 3600, 3600, 7200, 7200, 7200]
    _write_run(runs_dir, "sliced", manifest=_manifest("sliced"), tables={"mesh_volume": frame})

    body = client.get("/v1/runs/sliced/mesh?time=7200").json()
    assert body["returned"] == 3
    assert body["available_times"] == [3600, 7200]
    assert {row["time_s"] for row in body["rows"]} == {7200}


def test_mesh_honours_its_row_cap_and_sets_truncated(
    client: TestClient, runs_dir: Path
) -> None:
    _write_run(
        runs_dir, "capped", manifest=_manifest("capped"), tables={"mesh_volume": _mesh_frame(50)}
    )
    body = client.get("/v1/runs/capped/mesh?time=3600&limit=5").json()
    assert body["returned"] == 5
    assert body["matched_rows"] == 50
    assert body["truncated"] is True
    assert body["limit"] == 5
    assert any(warning["code"] == "truncated" for warning in body["warnings"])


def test_mesh_uses_coordinates_when_a_centre_table_exists(
    client: TestClient, runs_dir: Path
) -> None:
    centres = pd.DataFrame({"gcode": ["10100"], "lat": [13.71], "lon": [100.50]})
    _write_run(
        runs_dir,
        "geo",
        manifest=_manifest("geo"),
        tables={"mesh_volume": _mesh_frame(1), "mesh_cells": centres},
    )
    body = client.get("/v1/runs/geo/mesh?time=3600").json()
    assert body["rows"][0]["lat"] == 13.71
    assert body["rows"][0]["lon"] == 100.50
    assert body["features"][0]["geometry"]["coordinates"] == [100.50, 13.71]
    assert body["features"][0]["properties"]["total_pop"] == 0.5
    assert body["features"][0]["properties"]["population_quantity"] == "people_present"


def test_population_grid_is_geojson_with_a_resident_quantity(
    client: TestClient, runs_dir: Path
) -> None:
    grid = pd.DataFrame(
        {
            "gx": [1],
            "gy": [2],
            "pop": [1234.5],
            "x": [662000.0],
            "y": [1520000.0],
            "geometry_wkt": ["POINT (100.5 13.7)"],
        }
    )
    _write_run(
        runs_dir,
        "city-grid",
        manifest=_manifest("city-grid"),
        tables={"population_grid_1km": grid},
    )

    body = client.get("/v1/runs/city-grid/population-grid").json()

    assert body["type"] == "FeatureCollection"
    assert body["quantity"] == "resident_baseline"
    assert body["features"][0]["geometry"]["coordinates"] == [100.5, 13.7]
    assert body["features"][0]["properties"]["total_pop"] == 1234.5


def test_network_is_a_geojson_feature_collection(
    client: TestClient, runs_dir: Path
) -> None:
    edges = pd.DataFrame(
        {
            "edge_id": ["e1"],
            "length_m": [10.0],
            "highway": ["residential"],
            "walk_allowed": [True],
            "vehicle_allowed": [True],
            "geometry_wkt": ["LINESTRING (100.5 13.7, 100.6 13.8)"],
        }
    )
    _write_run(
        runs_dir,
        "city-network",
        manifest=_manifest("city-network"),
        tables={"network_edges": edges},
    )

    body = client.get("/v1/runs/city-network/network").json()

    assert body["type"] == "FeatureCollection"
    assert body["features"][0]["geometry"]["type"] == "LineString"


def test_flood_serves_one_time_slice_as_wgs84_points(
    client: TestClient, runs_dir: Path
) -> None:
    slices = pd.DataFrame(
        {
            "cell_id": ["a", "b", "a", "b"],
            "x": [662000.0, 663000.0, 662000.0, 663000.0],
            "y": [1520000.0, 1520000.0, 1520000.0, 1520000.0],
            "time_s": [0, 0, 300, 300],
            "depth_m": [0.1, 0.2, 0.3, 0.4],
            "peak_depth_m": [0.3, 0.4, 0.3, 0.4],
            "source_role": ["scenario"] * 4,
            "confidence": ["illustrative"] * 4,
        }
    )
    _write_run(
        runs_dir,
        "flood-run",
        manifest=_manifest("flood-run"),
        tables={"flood_slices": slices},
    )

    body = client.get("/v1/runs/flood-run/flood?time=300").json()

    assert body["type"] == "FeatureCollection"
    assert body["time_s"] == 300
    assert body["available_times"] == [0, 300]
    assert body["peak_time_s"] == 300
    assert body["matched_rows"] == 2
    assert body["returned"] == 2
    assert {feature["properties"]["depth_m"] for feature in body["features"]} == {
        0.3,
        0.4,
    }
    lon, lat = body["features"][0]["geometry"]["coordinates"]
    assert 99.0 < lon < 102.0
    assert 12.0 < lat < 15.0


def test_flood_sampling_preserves_spatial_coverage(
    client: TestClient, runs_dir: Path
) -> None:
    slices = pd.DataFrame(
        {
            "cell_id": [str(index) for index in range(10)],
            "x": [662000.0 + index * 100.0 for index in range(10)],
            "y": [1520000.0] * 10,
            "time_s": [0] * 10,
            "depth_m": [0.05 + float(index) / 10 for index in range(10)],
            "source_role": ["scenario"] * 10,
        }
    )
    _write_run(
        runs_dir,
        "sampled-flood",
        manifest=_manifest("sampled-flood"),
        tables={"flood_slices": slices},
    )

    body = client.get("/v1/runs/sampled-flood/flood?limit=3").json()

    assert body["matched_rows"] == 10
    assert body["returned"] == 3
    assert body["truncated"] is True
    assert body["sample_is_spatial_subset"] is True
    # Coverage sampling spans the ordered cells; it is not a deepest-only ranking.
    assert [feature["properties"]["cell_id"] for feature in body["features"]] == [
        "0",
        "4",
        "9",
    ]


def test_mesh_without_the_table_warns(client: TestClient, runs_dir: Path) -> None:
    _write_run(runs_dir, "nomesh", manifest=_manifest("nomesh"))
    body = client.get("/v1/runs/nomesh/mesh?time=3600").json()
    assert body["rows"] == []
    assert any(warning["artefact"] == "mesh_volume.parquet" for warning in body["warnings"])


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


def _network_tables() -> dict[str, pd.DataFrame]:
    edges = pd.DataFrame(
        {
            "edge_id": ["e1", "e2", "e3"],
            "u": [1, 2, 3],
            "v": [2, 3, 4],
            "length_m": [100.0, 150.0, 200.0],
            "highway": ["residential", "primary", "footway"],
            "walk_allowed": [True, True, True],
            "vehicle_allowed": [True, True, False],
            "geometry_wkt": [
                "LINESTRING (100.5 13.70, 100.51 13.71)",
                "LINESTRING (100.51 13.71, 100.52 13.72)",
                "LINESTRING (100.52 13.72, 100.53 13.73)",
            ],
        }
    )
    states = pd.DataFrame(
        {
            "edge_id": ["e1", "e2", "e3", "e1"],
            "time_s": [3600, 3600, 3600, 7200],
            "mode": [0, 0, 0, 0],
            "depth_m": [0.0, 0.5, 0.0, 0.0],
            "speed_multiplier": [1.0, 0.4, 1.0, 1.0],
            "capacity_multiplier": [1.0, 0.2, 1.0, 1.0],
            "closed": [False, True, False, False],
            "threshold_set_version": ["v1"] * 4,
            "reason_code": ["", "depth", "", ""],
        }
    )
    volume = pd.DataFrame(
        {
            "edge_id": ["e1", "e2", "e3"],
            "hour": [1, 1, 1],
            "volume": [10.0, 20.0, 30.0],
            "mode": [0, 0, 0],
            "distance_m": [100.0, 150.0, 200.0],
        }
    )
    return {"network_edges": edges, "edge_states": states, "link_volume": volume}


def test_links_return_a_geojson_feature_collection(
    client: TestClient, runs_dir: Path
) -> None:
    _write_run(runs_dir, "links", manifest=_manifest("links"), tables=_network_tables())
    body = client.get("/v1/runs/links/links?time=3600").json()
    assert body["type"] == "FeatureCollection"
    assert body["meta"]["returned"] == 3
    feature = body["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "LineString"
    assert feature["properties"]["edge_id"] in {"e1", "e2", "e3"}
    assert body["meta"]["geometry_available"] is True


def test_links_filter_by_mode(client: TestClient, runs_dir: Path) -> None:
    tables = _network_tables()
    tables["edge_states"]["mode"] = [0, 3, 0, 0]
    _write_run(runs_dir, "modes", manifest=_manifest("modes"), tables=tables)
    body = client.get("/v1/runs/modes/links?time=3600&mode=car").json()
    assert body["meta"]["returned"] == 1
    assert body["features"][0]["properties"]["edge_id"] == "e2"
    # Both the PFLOW code and the name select the same rows.
    by_code = client.get("/v1/runs/modes/links?time=3600&mode=3").json()
    assert by_code["meta"]["returned"] == 1


def test_links_cap_at_5000_features_with_a_truncated_flag(
    client: TestClient, runs_dir: Path
) -> None:
    tables = _network_tables()
    big_edges = pd.DataFrame(
        {
            "edge_id": [f"e{i}" for i in range(6000)],
            "u": [0] * 6000,
            "v": [1] * 6000,
            "length_m": [10.0] * 6000,
            "highway": ["residential"] * 6000,
            "walk_allowed": [True] * 6000,
            "vehicle_allowed": [True] * 6000,
            "geometry_wkt": ["LINESTRING (100.5 13.7, 100.6 13.8)"] * 6000,
        }
    )
    tables["network_edges"] = big_edges
    tables["edge_states"] = pd.DataFrame(
        {
            "edge_id": [f"e{i}" for i in range(6000)],
            "time_s": [3600] * 6000,
            "mode": [0] * 6000,
            "depth_m": [0.0] * 6000,
            "speed_multiplier": [1.0] * 6000,
            "capacity_multiplier": [1.0] * 6000,
            "closed": [False] * 6000,
        }
    )
    _write_run(runs_dir, "big", manifest=_manifest("big"), tables=tables)

    body = client.get("/v1/runs/big/links?time=3600").json()
    assert body["meta"]["returned"] == 5000
    assert body["meta"]["matched_features"] == 6000
    assert body["meta"]["truncated"] is True
    assert len(body["features"]) == 5000
    assert any(warning["code"] == "truncated" for warning in body["meta"]["warnings"])


def test_links_without_geometry_warn_but_return_attributes(
    client: TestClient, runs_dir: Path
) -> None:
    tables = {"edge_states": _network_tables()["edge_states"]}
    _write_run(runs_dir, "nogeom", manifest=_manifest("nogeom"), tables=tables)
    body = client.get("/v1/runs/nogeom/links?time=3600").json()
    assert body["meta"]["returned"] == 3
    assert body["meta"]["geometry_available"] is False
    assert all(feature["geometry"] is None for feature in body["features"])
    assert any(
        warning["artefact"] == "network_edges.parquet"
        for warning in body["meta"]["warnings"]
    )


# ---------------------------------------------------------------------------
# Buildings
# ---------------------------------------------------------------------------


def test_buildings_return_aggregates_and_omit_person_fields(
    client: TestClient, runs_dir: Path
) -> None:
    buildings = pd.DataFrame(
        {
            "building_id": ["b1", "b2"],
            "geometry_wkt": [
                "POLYGON ((100.5 13.7, 100.51 13.7, 100.51 13.71, 100.5 13.7))",
                "POLYGON ((100.52 13.7, 100.53 13.7, 100.53 13.71, 100.52 13.7))",
            ],
            "exposed_people": [4.0, 0.0],
            "ground_floor_area_m2": [80.0, 120.0],
            # A pipeline that wrongly carried a person key must not leak it.
            "person_id": ["p1", "p2"],
            "weight": [1.0, 1.0],
        }
    )
    _write_run(runs_dir, "bld", manifest=_manifest("bld"), tables={"buildings": buildings})

    body = client.get("/v1/runs/bld/buildings").json()
    assert body["meta"]["returned"] == 2
    assert body["meta"]["geometry_available"] is True
    assert set(body["meta"]["omitted_columns"]) == {"person_id", "weight"}
    for feature in body["features"]:
        assert "person_id" not in feature["properties"]
        assert "weight" not in feature["properties"]
        assert feature["properties"]["exposed_people"] in (4.0, 0.0)
        assert feature["geometry"]["type"] == "Polygon"
    assert any(warning["code"] == "columns_omitted" for warning in body["meta"]["warnings"])


def test_buildings_cap_rows(client: TestClient, runs_dir: Path) -> None:
    buildings = pd.DataFrame(
        {
            "building_id": [f"b{i}" for i in range(30)],
            "lon": [100.5] * 30,
            "lat": [13.7] * 30,
            "exposed_people": [1.0] * 30,
        }
    )
    _write_run(runs_dir, "manyb", manifest=_manifest("manyb"), tables={"buildings": buildings})
    body = client.get("/v1/runs/manyb/buildings?limit=10").json()
    assert body["meta"]["returned"] == 10
    assert body["meta"]["matched_rows"] == 30
    assert body["meta"]["truncated"] is True
    assert body["features"][0]["geometry"]["type"] == "Point"


def test_buildings_without_the_table_warn(client: TestClient, runs_dir: Path) -> None:
    _write_run(runs_dir, "nobld", manifest=_manifest("nobld"))
    body = client.get("/v1/runs/nobld/buildings").json()
    assert body["features"] == []
    assert any(warning["artefact"] == "buildings.parquet" for warning in body["meta"]["warnings"])


# ---------------------------------------------------------------------------
# Evacuation
# ---------------------------------------------------------------------------


def test_evacuation_reports_states_percentiles_and_unserved(
    client: TestClient, runs_dir: Path
) -> None:
    states = pd.DataFrame(
        {
            "person_id": [f"p{i}" for i in range(6)],
            "state": ["arrived", "arrived", "stranded", "did_not_depart", "not_eligible", "arrived"],
            "reason": ["", "", "flooded", "no_info", "", ""],
            "event_time_s": [600.0, 1200.0, 3000.0, 2400.0, 0.0, 1800.0],
            "weight": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            "dest_id": ["r1", "r1", "", "", "", "r2"],
        }
    )
    _write_run(runs_dir, "evac", manifest=_manifest("evac"), tables={"evacuation_states": states})

    body = client.get("/v1/runs/evac/evacuation").json()
    assert body["available"] is True
    distribution = {row["state"]: row for row in body["state_distribution"]}
    assert distribution["arrived"]["count"] == 3
    assert distribution["arrived"]["weight"] == 3.0
    assert distribution["stranded"]["weight"] == 1.0

    clearance = body["clearance_time_minutes"]
    # Arrival at 600, 1200 and 1800 seconds is 10, 20 and 30 minutes. Percentiles
    # interpolate linearly between the sorted values, so p5 sits a tenth of the
    # way from 10 to 20 and p95 a tenth short of 30.
    assert clearance["p5"] == pytest.approx(11.0)
    assert clearance["median"] == pytest.approx(20.0)
    assert clearance["p95"] == pytest.approx(29.0)

    totals = body["totals"]
    assert totals["cohort_weighted"] == 5.0  # everyone but the ineligible record
    assert totals["arrived_weighted"] == 3.0
    assert totals["unserved_weighted"] == 2.0  # stranded + did_not_depart
    assert totals["stranded_weighted"] == 1.0


def test_evacuation_without_the_table_returns_nulls(
    client: TestClient, runs_dir: Path
) -> None:
    _write_run(runs_dir, "noevac", manifest=_manifest("noevac"))
    body = client.get("/v1/runs/noevac/evacuation").json()
    assert body["available"] is False
    assert body["state_distribution"] == []
    assert body["clearance_time_minutes"] == {"p5": None, "median": None, "p95": None}
    assert body["totals"]["cohort_weighted"] is None
    assert any(warning["artefact"] == "evacuation_states.parquet" for warning in body["warnings"])


def test_evacuation_never_returns_person_ids(
    client: TestClient, runs_dir: Path
) -> None:
    states = pd.DataFrame(
        {
            "person_id": ["secret-1"],
            "state": ["arrived"],
            "event_time_s": [600.0],
            "weight": [1.0],
            "dest_id": ["r1"],
        }
    )
    _write_run(runs_dir, "nopii", manifest=_manifest("nopii"), tables={"evacuation_states": states})
    body = client.get("/v1/runs/nopii/evacuation").json()
    assert "secret-1" not in json.dumps(body)


# ---------------------------------------------------------------------------
# Validation and export
# ---------------------------------------------------------------------------


def test_evacuation_empty_table_is_distinct_from_a_missing_one(
    client: TestClient, runs_dir: Path
) -> None:
    """A readable but empty table means "no result was produced", which is a
    different finding from "the artefact is absent"."""
    states = pd.DataFrame(
        {
            "person_id": pd.Series(dtype="object"),
            "state": pd.Series(dtype="object"),
            "event_time_s": pd.Series(dtype="float64"),
            "weight": pd.Series(dtype="float64"),
        }
    )
    _write_run(
        runs_dir, "evacempty", manifest=_manifest("evacempty"), tables={"evacuation_states": states}
    )
    body = client.get("/v1/runs/evacempty/evacuation").json()
    assert body["available"] is False
    assert any(warning["code"] == "empty_table" for warning in body["warnings"])


def test_links_warn_when_the_requested_time_is_outside_the_run_range(
    client: TestClient, runs_dir: Path
) -> None:
    _write_run(runs_dir, "clock", manifest=_manifest("clock"), tables=_network_tables())
    # The fixture's slices start at 3600s; a model clock need not start at zero.
    body = client.get("/v1/runs/clock/links?time=0").json()
    assert body["meta"]["returned"] == 0
    assert any(warning["code"] == "no_rows" for warning in body["meta"]["warnings"])


def test_links_default_to_the_latest_slice(client: TestClient, runs_dir: Path) -> None:
    _write_run(runs_dir, "latest", manifest=_manifest("latest"), tables=_network_tables())
    body = client.get("/v1/runs/latest/links").json()
    assert body["meta"]["time_s"] == 7200
    assert body["meta"]["time_defaulted"] is True
    assert body["meta"]["returned"] == 1


def test_validation_is_served_verbatim(client: TestClient, runs_dir: Path) -> None:
    authored = {
        "run_id": "val",
        "checks": [
            {"name": "population_total", "threshold": 1000, "result": 1010, "passed": True}
        ],
    }
    _write_run(runs_dir, "val", manifest=_manifest("val"), json_files={"validation": authored})
    body = client.get("/v1/runs/val/validation").json()
    assert body["available"] is True
    assert body["validation"] == authored


def test_validation_missing_warns(client: TestClient, runs_dir: Path) -> None:
    _write_run(runs_dir, "noval", manifest=_manifest("noval"))
    body = client.get("/v1/runs/noval/validation").json()
    assert body["available"] is False
    assert body["validation"] is None
    assert any(warning["artefact"] == "validation.json" for warning in body["warnings"])


def test_export_lists_artefacts_with_sizes_and_sidecar_hashes(
    client: TestClient, runs_dir: Path
) -> None:
    run_dir = _write_run(runs_dir, "exp", manifest=_manifest("exp"))
    (run_dir / "stats.json").write_text(json.dumps({"run_id": "exp"}), encoding="utf-8")
    (run_dir / "stats.json.sha256").write_text("b" * 64 + "  stats.json", encoding="utf-8")
    (run_dir / "report").mkdir()
    (run_dir / "report" / "summary.md").write_text("# summary", encoding="utf-8")

    body = client.get("/v1/runs/exp/export").json()
    assert body["run_id"] == "exp"
    assert body["validation_status"] == "demonstration"
    assert body["manifest"]["run_id"] == "exp"
    assert body["total_bytes"] > 0

    by_path = {entry["path"]: entry for entry in body["artefacts"]}
    assert "manifest.json" in by_path
    assert "report/summary.md" in by_path
    assert by_path["stats.json"]["sha256"] == "b" * 64
    assert by_path["stats.json"]["sha256_source"] == "sidecar"
    assert by_path["stats.json"]["size_bytes"] > 0
    # No artefact body is streamed, only its metadata.
    assert "no_hash_for_this_one" not in json.dumps(body)
    assert by_path["manifest.json"]["sha256"] is None


def test_export_does_not_hash_large_files(
    client: TestClient, runs_dir: Path
) -> None:
    run_dir = _write_run(runs_dir, "big", manifest=_manifest("big"))
    (run_dir / "persons.parquet").write_bytes(b"0" * 5_000)
    body = client.get("/v1/runs/big/export").json()
    by_path = {entry["path"]: entry for entry in body["artefacts"]}
    # Computing a digest here would mean reading hundreds of megabytes.
    assert by_path["persons.parquet"]["sha256"] is None
    assert by_path["persons.parquet"]["size_bytes"] == 5000


@pytest.mark.parametrize("empty", [False, True])
def test_water_cells_never_substitute_an_unavailable_year(client, runs_dir, empty):
    rows = pd.DataFrame([{"cell_id": "old-water", "year": 2010, "water_share": .5,
        "water_km2": .5, "lon": 100.5, "lat": 13.7}])
    _write_run(runs_dir, "water-years", tables={"observed_water_cells": rows.iloc[:0] if empty else rows})
    response = client.get("/v1/runs/water-years/observed-water/cells?year=2020")
    assert response.status_code == 200
    assert response.json()["features"] == []
    assert response.json()["available"] is False
