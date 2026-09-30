"""Tests for the city-layer endpoints.

These cover the four data layers a city run produces that a pilot run does not,
plus the honesty invariants a client is entitled to rely on: an observed layer
must be flagged as an observation and must state it is not depth, and no
destination may emerge verified.
"""

from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from api.app import app  # noqa: E402


def _city_run_id() -> str | None:
    matches = glob.glob(str(REPO_ROOT / "runs" / "*" / "observed_water.json"))
    if not matches:
        return None
    return os.path.basename(os.path.dirname(max(matches, key=os.path.getmtime)))


RUN_ID = _city_run_id()
needs_run = pytest.mark.skipif(RUN_ID is None, reason="no city run with an observed layer")


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@needs_run
def test_population_grid_reports_a_resident_baseline(client: TestClient) -> None:
    response = client.get(f"/v1/runs/{RUN_ID}/population-grid")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    # A grid of residents must never be presented as a time-of-day population.
    assert body["quantity"] == "resident_baseline"
    assert "not a time-of-day" in body["quantity_note"]
    assert body["matched_rows"] > 0


@needs_run
def test_observed_water_is_flagged_as_observation_and_not_depth(client: TestClient) -> None:
    body = client.get(f"/v1/runs/{RUN_ID}/observed-water").json()
    assert body["available"] is True
    assert body["is_observation"] is True
    assert body["source_id"] == "jrc-global-surface-water-v1.4"
    # The distinction between extent and depth must survive to the client.
    assert "NOT depth" in body["measures"]
    assert [entry["year"] for entry in body["years"]]


@needs_run
def test_observed_water_records_the_missing_2011_signal(client: TestClient) -> None:
    """The absence of the 2011 flood is a finding, not a gap to hide."""
    body = client.get(f"/v1/runs/{RUN_ID}/observed-water").json()
    notes = " ".join(body.get("interpretation_notes", [])).lower()
    assert "2011" in notes
    assert "lower bound" in notes


@needs_run
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


@needs_run
def test_observed_water_cells_fall_back_when_a_year_is_absent(client: TestClient) -> None:
    body = client.get(
        f"/v1/runs/{RUN_ID}/observed-water/cells", params={"year": 1999, "limit": 50}
    ).json()
    assert body["year"] in body["available_years"]
    assert any(warning.get("code") == "year_not_available" for warning in body["warnings"])


@needs_run
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


@needs_run
def test_destinations_can_be_filtered_by_class(client: TestClient) -> None:
    body = client.get(
        f"/v1/runs/{RUN_ID}/destinations",
        params={"destination_class": "health_care", "limit": 5},
    ).json()
    assert body["matched_rows"] > 0
    assert list(body["by_class"]) == ["health_care"]
    for row in body["rows"]:
        assert row["destination_class"] == "health_care"


@needs_run
def test_network_returns_a_deterministic_sample_not_the_whole_city(client: TestClient) -> None:
    first = client.get(f"/v1/runs/{RUN_ID}/network", params={"limit": 40}).json()
    second = client.get(f"/v1/runs/{RUN_ID}/network", params={"limit": 40}).json()
    assert first["sample_is_spatial_subset"] is True
    assert [f["properties"]["edge_id"] for f in first["features"]] == [
        f["properties"]["edge_id"] for f in second["features"]
    ]
    assert first["summary"]["edges"] > first["returned"]
    assert any(warning.get("code") == "sampled" for warning in first["warnings"])


@needs_run
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


@needs_run
@pytest.mark.parametrize(
    "path",
    [
        "/observed-water/cells?limit=5",
        "/network?limit=5",
        "/buildings?limit=5",
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

