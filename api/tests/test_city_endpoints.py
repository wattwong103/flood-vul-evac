"""Tests for the city-layer endpoints.

These cover the four data layers a city run produces that a pilot run does not,
plus the two screening indices layered on top of them, plus the honesty
invariants a client is entitled to rely on: an observed layer must be flagged as
an observation and must state it is not depth, no destination may emerge
verified, connectivity screening is not an evacuation simulation, and the
drainage index is not a flood depth.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402


RUN_ID = "synthetic-city-contract"


def _write_json(run_dir: Path, name: str, payload: dict) -> None:
    (run_dir / name).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _write_city_run(root: Path) -> Path:
    """Write the smallest complete city snapshot needed by this contract suite."""
    run_dir = root / RUN_ID
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir,
        "manifest.json",
        {
            "run_id": RUN_ID,
            "created_at": "2026-01-01T00:00:00+00:00",
            "validation_status": "demonstration",
            "code_identity": {
                "git_commit": "1" * 40,
                "git_tree": "2" * 40,
                "git_status": "clean",
                "source_sha256": "3" * 64,
                "source_files": 1,
                "scope": ["pipeline", "api", "config", "schemas"],
                "verification": "matched_before_publication",
            },
            "geography": {
                "aoi_id": "bangkok-bma",
                "storage_crs": "OGC:CRS84",
                "analysis_crs": "EPSG:32647",
            },
            "source_versions": [],
            "warnings": [],
        },
    )
    _write_json(
        run_dir,
        "stats.json",
        {
            "run_id": RUN_ID,
            "scale": "city",
            "validation_status": "demonstration",
            "created_at": "2026-01-01T00:00:00+00:00",
            "flood": {
                "depth_status": "unavailable",
                "depth_reason": "No hydraulic depth surface is available.",
                "max_depth_m": None,
                "edges_closed": None,
                "observed_extent": {"is_observation": True},
            },
            "network": {"edges": 60, "nodes": 61, "length_km": 6.0},
            "warnings": [],
        },
    )
    stages = [
        {"stage": "sources", "status": "completed", "seconds": 1.0, "rows": 4},
        {"stage": "network", "status": "completed", "seconds": 2.0, "rows": 60},
        {"stage": "map_index", "status": "completed", "seconds": 1.0, "rows": 60},
    ]
    _write_json(
        run_dir,
        "run_state.json",
        {
            "run_id": RUN_ID,
            "state": "published",
            "scale": "city",
            "started_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:04+00:00",
            "stage_count": len(stages),
            "stages": stages,
            "warnings": [],
            "error": None,
        },
    )
    _write_json(
        run_dir,
        "observed_water.json",
        {
            "status": "ok",
            "source_id": "jrc-global-surface-water-v1.4",
            "licence": "Copernicus free and open use",
            "product": "annual water classification",
            "measures": "annual observed water extent, NOT depth",
            "baseline_year": 2010,
            "years": [{"year": 2010}, {"year": 2012}],
            "unavailable_years": [],
            "interpretation_notes": [
                "Annual water classes are not event-flood extent or flood peaks.",
                "No observations is not dry land.",
            ],
        },
    )

    severity = (
        "Not an evacuation simulation: the annual observation has no depth, "
        "duration, flow direction or timing."
    )
    screened_years = {}
    for year, closed_share in ((2010, 0.1), (2012, 0.2)):
        screened_years[str(year)] = {
            "year": year,
            "source_role": "screening_index",
            "hazard_role": "observed",
            "is_evacuation_simulation": False,
            "severity_note": severity,
            "closed_edge_share": closed_share,
            "reachable_share_of_exposed": 0.75,
            "designated_destinations": 2,
        }
    _write_json(
        run_dir,
        "connectivity_screening.json",
        {
            "source_role": "screening_index",
            "hazard_role": "observed",
            "measures": "network connectivity under observed annual water",
            "years": screened_years,
        },
    )

    risk_bands = [
        "moderate", "very_high", "low", "high",
        "low", "very_high", "moderate", "high",
    ]
    drainage = pd.DataFrame(
        {
            "cell_id": [f"drainage-{index}" for index in range(8)],
            "gx": list(range(8)),
            "gy": [0] * 8,
            "x": [662176.0 + index * 10 for index in range(8)],
            "y": [1520582.0 + index * 10 for index in range(8)],
            "lon": [100.5 + index * 0.001 for index in range(8)],
            "lat": [13.75 + index * 0.001 for index in range(8)],
            "drainage_m": [100.0] * 8,
            "drainage_km_per_km2": [0.1] * 8,
            "distance_to_drainage_m": [50.0] * 8,
            "in_overflow_path": [False] * 8,
            "basin_id": ["basin-1"] * 8,
            "basin_drainage_density": [0.2] * 8,
            "susceptible_village": [False] * 8,
            "index_components": ["synthetic-contract-fixture"] * 8,
            "risk_index": [0.55, 0.95, 0.25, 0.75, 0.35, 0.85, 0.45, 0.65],
            "risk_band": risk_bands,
            "index_inputs_complete": [True] * 8,
            "source_role": ["screening_index"] * 8,
        }
    )
    drainage.to_parquet(run_dir / "drainage_index.parquet", index=False)
    band_counts = {band: risk_bands.count(band) for band in sorted(set(risk_bands))}
    _write_json(
        run_dir,
        "drainage_index.json",
        {
            "index_version": "synthetic-contract-v1",
            "status": "ok",
            "source_role": "screening_index",
            "measures": "relative drainage-discharge screening index",
            "is_flood_depth": False,
            "component_weights": {"distance_to_drainage": 1.0},
            "bands": sorted(band_counts),
            "summary": {"bands": band_counts},
            "limitations": [
                "This is not a hydraulic model and not a flood depth.",
                "It omits rainfall, river stage, tides, and pump and gate operation.",
            ],
        },
    )

    pd.DataFrame(
        {
            "cell_id": ["water-2010", "water-2012"],
            "year": [2010, 2012],
            "water_share": [0.2, 0.4],
            "water_km2": [0.2, 0.4],
            "lon": [100.5, 100.51],
            "lat": [13.75, 13.76],
        }
    ).to_parquet(run_dir / "observed_water_cells.parquet", index=False)
    pd.DataFrame(
        {
            "destination_id": ["school-1", "clinic-1"],
            "destination_class": ["education", "health_care"],
            "verified": [False, False],
            "status": ["osm_tagged_candidate_unverified"] * 2,
            "capacity": [None, None],
            "operator": [None, None],
        }
    ).to_parquet(run_dir / "destinations.parquet", index=False)
    pd.DataFrame(
        {
            "edge_id": [f"edge-{index:03d}" for index in range(60)],
            "length_m": [100.0] * 60,
            "highway": ["residential"] * 60,
            "walk_allowed": [True] * 60,
            "vehicle_allowed": [True] * 60,
            "geometry_wkt": [
                f"LINESTRING ({662176 + index * 10} 1520582, "
                f"{662276 + index * 10} 1520582)"
                for index in range(60)
            ],
        }
    ).to_parquet(run_dir / "network_edges.parquet", index=False)
    pd.DataFrame(
        {
            "building_id": ["building-1"],
            "height_m": [9.0],
            "lon": [100.5],
            "lat": [13.75],
        }
    ).to_parquet(run_dir / "buildings.parquet", index=False)
    pd.DataFrame(
        {
            "cell_id": ["population-1"],
            "pop": [1000.0],
            "geometry_wkt": [
                "POLYGON ((100.49 13.74, 100.51 13.74, 100.51 13.76, "
                "100.49 13.76, 100.49 13.74))"
            ],
        }
    ).to_parquet(run_dir / "population_grid_1km.parquet", index=False)
    return run_dir


@pytest.fixture(scope="module")
def city_run_dir(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("city-runs")
    previous = os.environ.get("BKKFLOW_RUNS_DIR")
    os.environ["BKKFLOW_RUNS_DIR"] = str(root)
    try:
        yield _write_city_run(root)
    finally:
        if previous is None:
            os.environ.pop("BKKFLOW_RUNS_DIR", None)
        else:
            os.environ["BKKFLOW_RUNS_DIR"] = previous


@pytest.fixture(scope="module")
def client(city_run_dir: Path) -> TestClient:
    return TestClient(create_app())


def test_population_grid_reports_a_resident_baseline(client: TestClient) -> None:
    response = client.get(f"/v1/runs/{RUN_ID}/population-grid")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    # A grid of residents must never be presented as a time-of-day population.
    assert body["quantity"] == "resident_baseline"
    assert "not a time-of-day" in body["quantity_note"]
    assert body["matched_rows"] > 0


def test_observed_water_is_flagged_as_observation_and_not_depth(client: TestClient) -> None:
    body = client.get(f"/v1/runs/{RUN_ID}/observed-water").json()
    assert body["available"] is True
    assert body["is_observation"] is True
    assert body["source_id"] == "jrc-global-surface-water-v1.4"
    # The distinction between extent and depth must survive to the client.
    assert "NOT depth" in body["measures"]
    assert [entry["year"] for entry in body["years"]]


def test_observed_water_states_annual_observation_limits(client: TestClient) -> None:
    """Annual water classes cannot establish whether an event was absent."""
    body = client.get(f"/v1/runs/{RUN_ID}/observed-water").json()
    notes = " ".join(body.get("interpretation_notes", [])).lower()
    assert "annual water classes" in notes
    assert "no observations is not dry land" in notes


def test_observed_water_cells_are_geojson_with_extent_only_properties(client: TestClient) -> None:
    body = client.get(
        f"/v1/runs/{RUN_ID}/observed-water/cells", params={"year": 2012, "limit": 400}
    ).json()
    assert body["type"] == "FeatureCollection"
    assert body["is_observation"] is True
    assert body["year"] == 2012
    assert 2012 in body["available_years"]
    features = body["features"]
    assert features, "expected at least one observed-water cell"
    properties = features[0]["properties"]
    assert properties["source_role"] == "observed"
    assert properties["measures"] == "extent_only"
    assert "depth" not in properties
    assert features[0]["geometry"]["type"] == "Point"


def test_observed_water_cells_do_not_substitute_an_absent_year(client: TestClient) -> None:
    body = client.get(
        f"/v1/runs/{RUN_ID}/observed-water/cells", params={"year": 1999, "limit": 50}
    ).json()
    assert body["year"] == 1999
    assert body["available"] is False
    assert body["features"] == []
    assert any(warning.get("code") == "year_not_available" for warning in body["warnings"])


def test_no_destination_is_ever_verified(client: TestClient) -> None:
    body = client.get(f"/v1/runs/{RUN_ID}/destinations", params={"limit": 5}).json()
    assert body["available"] is True
    assert body["verified_count"] == 0
    assert "may be presented as a refuge" in body["verified_note"]
    for row in body["rows"]:
        assert row["verified"] is False
        assert row["status"] == "osm_tagged_candidate_unverified"
        assert row["capacity"] is None
        assert row["operator"] is None


def test_destinations_can_be_filtered_by_class(client: TestClient) -> None:
    body = client.get(
        f"/v1/runs/{RUN_ID}/destinations",
        params={"destination_class": "health_care", "limit": 5},
    ).json()
    assert body["matched_rows"] > 0
    assert list(body["by_class"]) == ["health_care"]
    for row in body["rows"]:
        assert row["destination_class"] == "health_care"


def test_city_fixture_is_source_tracked_and_published(client: TestClient) -> None:
    detail = client.get(f"/v1/runs/{RUN_ID}").json()
    stats = client.get(f"/v1/runs/{RUN_ID}/stats").json()

    assert detail["manifest"]["code_identity"]["verification"] == (
        "matched_before_publication"
    )
    assert detail["run_state"]["state"] == "published"
    assert detail["run_state"]["scale"] == "city"
    assert stats["scale"] == "city"


def test_network_returns_a_deterministic_sample_not_the_whole_city(
    client: TestClient, city_run_dir: Path
) -> None:
    stored = pd.read_parquet(city_run_dir / "network_edges.parquet")
    assert stored["geometry_wkt"].nunique() == len(stored)

    first = client.get(f"/v1/runs/{RUN_ID}/network", params={"limit": 10}).json()
    second = client.get(f"/v1/runs/{RUN_ID}/network", params={"limit": 10}).json()
    assert first["sample_is_spatial_subset"] is True
    assert [f["properties"]["edge_id"] for f in first["features"]] == [
        f["properties"]["edge_id"] for f in second["features"]
    ]
    assert [f["properties"]["edge_id"] for f in first["features"]] == [
        f"edge-{index:03d}" for index in range(0, 60, 6)
    ]
    assert first["summary"]["edges"] > first["returned"]
    assert any(warning.get("code") == "sampled" for warning in first["warnings"])


def test_city_run_reports_null_depth_rather_than_zero(client: TestClient) -> None:
    """A zero would read as 'no flooding', which is a different claim."""
    stats = client.get(f"/v1/runs/{RUN_ID}/stats").json()
    flood = stats["flood"]
    assert flood["depth_status"] != "ok"
    assert flood["max_depth_m"] is None
    assert flood["edges_closed"] is None
    assert "depth" in flood["depth_reason"].lower()
    # The observed layer must still be present and separately flagged.
    assert flood["observed_extent"]["is_observation"] is True


def _iter_coords(geometry: dict, depth: int = 0):
    """Yield every coordinate pair in a GeoJSON geometry."""
    if depth > 6:
        return
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
        yield float(coords[0]), float(coords[1])
    elif kind == "LineString":
        for position in coords or []:
            if len(position) >= 2:
                yield float(position[0]), float(position[1])
    elif kind in {"Polygon", "MultiLineString", "MultiPoint"}:
        for part in coords or []:
            for position in part or []:
                if len(position) >= 2:
                    yield float(position[0]), float(position[1])
    elif kind == "MultiPolygon":
        for polygon in coords or []:
            for ring in polygon or []:
                for position in ring or []:
                    if len(position) >= 2:
                        yield float(position[0]), float(position[1])
    elif kind == "GeometryCollection":
        for sub in geometry.get("geometries") or []:
            yield from _iter_coords(sub, depth + 1)


@pytest.mark.parametrize(
    "path",
    [
        "/observed-water/cells?limit=5",
        "/network?limit=5",
        "/buildings?limit=5",
        "/drainage/cells?limit=5",
    ],
)
def test_served_geojson_is_wgs84_not_projected(client: TestClient, path: str) -> None:
    """GeoJSON is WGS84 by RFC 7946; serving UTM metres misplaces every layer.

    The pipeline stores geometry in EPSG:32647 for metric work. If the API ever
    stops reprojecting, features land hundreds of kilometres away and still
    render, which is why this asserts the coordinate range rather than trusting
    the response shape.
    """
    body = client.get(f"/v1/runs/{RUN_ID}{path}").json()
    features = body.get("features") or []
    assert features, f"{path} returned no features"
    for item in features:
        for lon, lat in _iter_coords(item["geometry"]):
            # Bangkok and its metropolitan area.
            assert 100.2 < lon < 101.1, f"{path}: longitude {lon} is not Bangkok WGS84"
            assert 13.1 < lat < 14.1, f"{path}: latitude {lat} is not Bangkok WGS84"


# -------------------------------------------------------------------------- #
# Connectivity screening under observed water
# -------------------------------------------------------------------------- #


def test_connectivity_states_that_it_is_not_an_evacuation_simulation(
    client: TestClient,
) -> None:
    """The headline number is a screening index; the flag must reach the client.

    An annual Landsat classification carries no depth, duration, direction or
    timing, so "71% of the exposed population can get out" would be a claim the
    artefact cannot support. The flag and the note are payload-level so a client
    cannot keep the number and drop the framing.
    """
    response = client.get(f"/v1/runs/{RUN_ID}/connectivity")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["is_evacuation_simulation"] is False
    assert body["is_simulation"] is False
    assert body["source_role"] == "screening_index"
    # Verbatim, not paraphrased.
    note = body["severity_note"]
    assert isinstance(note, str) and "Not an evacuation simulation" in note
    assert "no depth, duration, flow direction or timing" in note
    # The destination count is a modelling choice, not a fact about the city.
    assert "scenario choice" in body["destination_note"]


def test_connectivity_carries_the_flag_on_every_screened_year(client: TestClient) -> None:
    body = client.get(f"/v1/runs/{RUN_ID}/connectivity").json()
    years = body["years"]
    assert len(years) >= 2, "expected the screening to cover more than one year"
    assert [entry["year"] for entry in years] == sorted(entry["year"] for entry in years)
    for entry in years:
        assert entry["is_evacuation_simulation"] is False
        assert entry["severity_note"]
        assert entry["source_role"] == "screening_index"
        assert entry["hazard_role"] == "observed"
        # Water is impassable at any depth, so the closed share is a property of
        # the rule and not of a depth the run does not have.
        assert 0.0 <= entry["closed_edge_share"] <= 1.0
        assert 0.0 <= entry["reachable_share_of_exposed"] <= 1.0
        assert entry["designated_destinations"] > 0


def test_connectivity_can_be_read_for_a_single_year(client: TestClient) -> None:
    body = client.get(f"/v1/runs/{RUN_ID}/connectivity", params={"year": 2012}).json()
    assert body["year"] == 2012
    assert [entry["year"] for entry in body["years"]] == [2012]
    assert body["years"][0]["is_evacuation_simulation"] is False


def test_connectivity_does_not_substitute_a_year_that_was_never_screened(
    client: TestClient,
) -> None:
    """A different year under the cursor is a different event, not a fallback."""
    body = client.get(f"/v1/runs/{RUN_ID}/connectivity", params={"year": 1999}).json()
    assert body["years"] == []
    assert any(warning.get("code") == "year_not_available" for warning in body["warnings"])


# -------------------------------------------------------------------------- #
# Drainage-discharge screening index
# -------------------------------------------------------------------------- #


def test_drainage_reports_a_screening_index_and_not_a_flood_depth(
    client: TestClient,
) -> None:
    """The index is a relative susceptibility score, so no client may read it as
    metres of water. ``is_flood_depth`` and the limitations list are the guard."""
    response = client.get(f"/v1/runs/{RUN_ID}/drainage")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["is_flood_depth"] is False
    assert body["is_simulation"] is False
    assert body["is_observation"] is False
    assert body["source_role"] == "screening_index"
    assert "screening index" in body["measures"]
    # Surfaced, not summarised away: the artefacts the index ignores are the
    # ones that dominate real Bangkok flooding.
    limitations = " ".join(body["limitations"]).lower()
    assert "not a hydraulic model" in limitations
    assert "not a flood depth" in limitations
    for ignored in ("rainfall", "river stage", "tides", "pump and gate"):
        assert ignored in limitations
    assert body["component_weights"]
    assert body["bands"]
    assert body["summary"]["bands"]


def test_drainage_cells_flag_every_feature_as_an_index_and_not_a_depth(
    client: TestClient, city_run_dir: Path
) -> None:
    stored = pd.read_parquet(city_run_dir / "drainage_index.parquet")
    assert not stored["risk_index"].is_monotonic_decreasing

    body = client.get(
        f"/v1/runs/{RUN_ID}/drainage/cells", params={"limit": 50}
    ).json()
    assert body["type"] == "FeatureCollection"
    assert body["is_flood_depth"] is False
    assert body["source_role"] == "screening_index"
    features = body["features"]
    assert features, "expected screening cells"
    risks = []
    for item in features:
        properties = item["properties"]
        assert properties["source_role"] == "screening_index"
        assert properties["is_flood_depth"] is False
        # A field named depth must not exist at all on this layer.
        assert "depth" not in properties
        assert properties["risk_band"] in body["available_bands"]
        risks.append(properties["risk_index"])
    # Highest risk first, so the row cap keeps the cells that matter.
    assert risks == sorted(risks, reverse=True)


def test_drainage_cells_can_be_narrowed_by_band_and_risk(client: TestClient) -> None:
    summary = client.get(f"/v1/runs/{RUN_ID}/drainage").json()["summary"]["bands"]
    body = client.get(
        f"/v1/runs/{RUN_ID}/drainage/cells", params={"band": "very_high", "limit": 500}
    ).json()
    assert body["band"] == "very_high"
    # The cells route and the summary must count the same cells.
    assert body["matched_rows"] == summary["very_high"]
    for item in body["features"]:
        assert item["properties"]["risk_band"] == "very_high"
        assert 0.0 <= item["properties"]["risk_index"] <= 1.0

    missing = client.get(
        f"/v1/runs/{RUN_ID}/drainage/cells", params={"band": "extreme"}
    ).json()
    assert missing["features"] == []
    assert any(warning.get("code") == "band_not_available" for warning in missing["warnings"])


def test_drainage_cells_report_truncation_rather_than_silently_shortening(
    client: TestClient,
) -> None:
    body = client.get(f"/v1/runs/{RUN_ID}/drainage/cells", params={"limit": 5}).json()
    assert body["truncated"] is True
    assert body["returned"] == 5
    assert body["matched_rows"] > 5
    assert any(warning.get("code") == "truncated" for warning in body["warnings"])


@pytest.mark.parametrize(
    "path", ["/connectivity", "/connectivity?year=2012", "/drainage", "/drainage/cells"]
)
def test_a_run_without_the_screening_artefacts_reports_an_absence_not_an_error(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """A pilot run carries neither screening index. The routes must say so and
    return 200 with a warning, never raise and never answer with a zero."""
    runs = tmp_path / "runs"
    run_dir = runs / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "created_at": "2026-01-01T00:00:00+00:00",
                "validation_status": "demonstration",
                "geography": {"aoi_id": "khlong-san", "analysis_crs": "EPSG:32647"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BKKFLOW_RUNS_DIR", str(runs))

    response = client.get(f"/v1/runs/{run_dir.name}{path}")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["warnings"], "an absent layer must carry a warning saying so"
    assert any(
        warning.get("artefact", "").startswith(("connectivity_", "drainage_"))
        for warning in body["warnings"]
    )
    if path == "/connectivity":
        # The framing survives the absence: an absent index is still not a
        # simulation, and no year is invented.
        assert body["is_evacuation_simulation"] is False
        assert body["years"] == []
    if path == "/drainage":
        assert body["is_flood_depth"] is False
        assert body["limitations"] == []
    if path == "/drainage/cells":
        assert body["is_flood_depth"] is False
        assert body["features"] == []
        assert body["matched_rows"] == 0

