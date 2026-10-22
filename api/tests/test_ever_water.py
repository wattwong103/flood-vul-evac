"""Contract tests for ``GET /v1/runs/{id}/observed-water/ever`` (BKK-055c).

The 1984-2021 JRC Maximum Water Extent is served only for the exact tile the
run recorded: the staged bytes must hash to the run's ``max_extent`` SHA-256.
A missing or different tile is reported with a reason, never as zero water.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import create_app

WEST, NORTH, STEP = 100.5, 13.7, 0.00025
TILE = "extent-0000240000-0001120000.tif"


def _write_tile(path: Path, rows: list[list[int]]) -> tuple[float, float, float, float]:
    import rasterio
    from rasterio.transform import from_origin

    array = np.array(rows, dtype="uint8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=array.shape[1], height=array.shape[0],
                       count=1, dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(WEST, NORTH, STEP, STEP)) as dst:
        dst.write(array, 1)
    return (WEST, NORTH - array.shape[0] * STEP, WEST + array.shape[1] * STEP, NORTH)


def _write_aoi(data_dir: Path, aoi_id: str, bounds) -> None:
    west, south, east, north = bounds
    polygon = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    aoi = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"aoi_id": aoi_id},
           "geometry": {"type": "Polygon", "coordinates": [polygon]}}]}
    target = data_dir / "curated" / "aoi" / f"{aoi_id}.geojson"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(aoi), encoding="utf-8")


def _write_run(runs_dir: Path, run_id: str, *, aoi_id: str, observed: dict | None) -> None:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "created_at": "2026-10-19T21:30:14+00:00",
        "validation_status": "demonstration",
        "geography": {"aoi_id": aoi_id, "analysis_crs": "EPSG:32647"},
        "outputs": [],
        "warnings": [],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "run_state.json").write_text(
        json.dumps({"stage": "completed", "progress": 1.0, "warnings": [], "stages": []}),
        encoding="utf-8",
    )
    if observed is not None:
        (run_dir / "observed_water.json").write_text(json.dumps(observed), encoding="utf-8")


def _observed(sha: str | None, *, status: str = "ok", aoi_pixels: int | None = 8) -> dict:
    # The run's own yearly count binds the boundary: the 2x4 fixture is 8 pixels.
    years = [] if aoi_pixels is None else [{"year": 2020, "aoi_pixels": aoi_pixels}]
    record = {"status": "ok", "aoi_id": "bangkok-bma", "years": years}
    if sha is not None:
        record["max_extent"] = {
            "source_id": "jrc-global-surface-water-max-extent-v1.4",
            "status": status,
            "tile_name": TILE,
            "content_sha256": sha,
        }
    return record


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    runs_dir, data_dir = tmp_path / "runs", tmp_path / "data"
    runs_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.setenv("BKKFLOW_RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("BKKFLOW_DATA_DIR", str(data_dir))
    return runs_dir, data_dir


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _staged(data_dir: Path) -> tuple[str, tuple[float, float, float, float]]:
    tile = data_dir / "staged" / "gsw" / TILE
    bounds = _write_tile(tile, [[1, 1, 0, 255], [0, 1, 0, 0]])
    _write_aoi(data_dir, "bangkok-bma", bounds)
    return hashlib.sha256(tile.read_bytes()).hexdigest(), bounds


def _pixel_km2(bounds) -> float:
    return (STEP * 111.32) ** 2 * float(np.cos(np.radians((bounds[1] + bounds[3]) / 2)))


def test_ever_water_reports_area_and_cells_for_the_recorded_tile(client, dirs) -> None:
    runs_dir, data_dir = dirs
    sha, bounds = _staged(data_dir)
    _write_run(runs_dir, "city", aoi_id="bangkok-bma", observed=_observed(sha))

    body = client.get("/v1/runs/city/observed-water/ever?min_share=0").json()

    assert body["available"] is True
    assert body["verified"] is True
    assert body["content_sha256"] == sha
    assert body["is_observation"] is True
    assert "1984" in body["measures"]
    assert body["ever_water_km2"] == pytest.approx(3 * _pixel_km2(bounds))
    assert body["no_data_km2"] == pytest.approx(1 * _pixel_km2(bounds))
    assert body["ever_water_share_of_observed"] == pytest.approx(3 / 7)
    assert body["type"] == "FeatureCollection"
    assert body["features"]
    properties = body["features"][0]["properties"]
    assert properties["source_role"] == "observed"
    assert properties["water_share"] is not None


def test_a_tile_whose_bytes_differ_from_the_runs_record_is_refused(client, dirs) -> None:
    runs_dir, data_dir = dirs
    _staged(data_dir)
    _write_run(runs_dir, "city", aoi_id="bangkok-bma", observed=_observed("0" * 64))

    body = client.get("/v1/runs/city/observed-water/ever").json()

    assert body["available"] is False
    assert body["ever_water_km2"] is None
    assert body["features"] == []
    assert any(warning["code"] == "source_mismatch" for warning in body["warnings"])


def test_a_tile_that_is_not_staged_is_reported_not_zero(client, dirs) -> None:
    runs_dir, data_dir = dirs
    _write_run(runs_dir, "city", aoi_id="bangkok-bma", observed=_observed("a" * 64))

    body = client.get("/v1/runs/city/observed-water/ever").json()

    assert body["available"] is False
    assert body["ever_water_km2"] is None
    assert "not staged" in body["reason"]


@pytest.mark.parametrize("observed", [None, _observed(None), _observed("a" * 64, status="not_staged")])
def test_a_run_without_a_recorded_extent_is_unavailable(client, dirs, observed) -> None:
    runs_dir, _ = dirs
    _write_run(runs_dir, "run", aoi_id="bangkok-bma", observed=observed)

    body = client.get("/v1/runs/run/observed-water/ever").json()

    assert body["available"] is False
    assert body["ever_water_km2"] is None
    assert body["reason"]


def test_min_share_filters_the_cells_but_not_the_totals(client, dirs) -> None:
    runs_dir, data_dir = dirs
    sha, _ = _staged(data_dir)
    _write_run(runs_dir, "city", aoi_id="bangkok-bma", observed=_observed(sha))

    everything = client.get("/v1/runs/city/observed-water/ever?min_share=0").json()
    none = client.get("/v1/runs/city/observed-water/ever?min_share=1").json()

    assert everything["features"] and none["features"] == []
    assert none["ever_water_km2"] == everything["ever_water_km2"]


def test_the_run_list_names_each_runs_area(client, dirs) -> None:
    runs_dir, _ = dirs
    _write_run(runs_dir, "city", aoi_id="bangkok-bma", observed=None)

    runs = client.get("/v1/runs").json()["runs"]

    assert runs[0]["aoi_id"] == "bangkok-bma"



# ---------------------------------------------------------------------------
# Review regressions: unusable inputs give a reason, never a 500 or a false
# "verified".
# ---------------------------------------------------------------------------


def _codes(body: dict) -> set[str]:
    return {warning["code"] for warning in body["warnings"]}


def test_an_unreadable_boundary_gives_a_reason_not_a_500(client, dirs) -> None:
    runs_dir, data_dir = dirs
    sha, _ = _staged(data_dir)
    (data_dir / "curated" / "aoi" / "bangkok-bma.geojson").write_text("{not json", encoding="utf-8")
    _write_run(runs_dir, "city", aoi_id="bangkok-bma", observed=_observed(sha))

    response = client.get("/v1/runs/city/observed-water/ever")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "unreadable_artefact" in _codes(body)
    assert str(data_dir) not in body["reason"]


def test_a_locked_tile_gives_a_reason_not_a_500(client, dirs, monkeypatch) -> None:
    runs_dir, data_dir = dirs
    sha, _ = _staged(data_dir)
    _write_run(runs_dir, "city", aoi_id="bangkok-bma", observed=_observed(sha))

    def locked(self):
        raise PermissionError(f"[Errno 13] Permission denied: '{self}'")

    monkeypatch.setattr(Path, "read_bytes", locked)
    response = client.get("/v1/runs/city/observed-water/ever")

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert str(data_dir) not in response.json()["reason"]


def test_a_same_size_swap_is_never_served_as_verified(client, dirs) -> None:
    import os

    runs_dir, data_dir = dirs
    sha, _ = _staged(data_dir)
    _write_run(runs_dir, "city", aoi_id="bangkok-bma", observed=_observed(sha))
    assert client.get("/v1/runs/city/observed-water/ever").json()["verified"] is True

    tile = data_dir / "staged" / "gsw" / TILE
    stat = tile.stat()
    _write_tile(tile, [[0, 0, 0, 0], [0, 0, 0, 0]])  # same shape, same size
    os.utime(tile, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    body = client.get("/v1/runs/city/observed-water/ever").json()

    assert body["verified"] is False
    assert "source_mismatch" in _codes(body)


def test_a_boundary_that_does_not_match_the_run_is_not_verified(client, dirs) -> None:
    runs_dir, data_dir = dirs
    sha, _ = _staged(data_dir)
    _write_run(runs_dir, "city", aoi_id="bangkok-bma", observed=_observed(sha, aoi_pixels=99))

    body = client.get("/v1/runs/city/observed-water/ever").json()

    assert body["available"] is False
    assert body["verified"] is False
    assert "aoi_mismatch" in _codes(body)


def test_an_area_id_that_disagrees_with_the_manifest_is_refused(client, dirs) -> None:
    runs_dir, data_dir = dirs
    sha, _ = _staged(data_dir)
    _write_run(runs_dir, "city", aoi_id="sai-mai-district", observed=_observed(sha))

    body = client.get("/v1/runs/city/observed-water/ever").json()

    assert body["available"] is False
    assert "manifest" in body["reason"]


@pytest.mark.parametrize("tile_name", ["../extent.tif", "extent.tif\n", "C:extent.tif"])
def test_a_tile_name_that_is_not_a_plain_file_name_is_refused(client, dirs, tile_name) -> None:
    runs_dir, _ = dirs
    observed = _observed("a" * 64)
    observed["max_extent"]["tile_name"] = tile_name
    _write_run(runs_dir, "city", aoi_id="bangkok-bma", observed=observed)

    body = client.get("/v1/runs/city/observed-water/ever").json()

    assert body["available"] is False
    assert "plain file name" in body["reason"]


def test_the_limit_keeps_the_wettest_cells_and_says_so(client, dirs) -> None:
    runs_dir, data_dir = dirs
    tile = data_dir / "staged" / "gsw" / TILE
    # 48 x 48 pixels (about 1.3 km) spans several 1 km cells.
    rows = [[1 if (r + c) % 3 else 0 for c in range(48)] for r in range(48)]
    bounds = _write_tile(tile, rows)
    _write_aoi(data_dir, "bangkok-bma", bounds)
    sha = hashlib.sha256(tile.read_bytes()).hexdigest()
    _write_run(runs_dir, "city", aoi_id="bangkok-bma", observed=_observed(sha, aoi_pixels=48 * 48))

    body = client.get("/v1/runs/city/observed-water/ever?min_share=0&limit=1").json()

    assert body["matched_cells"] > 1
    assert body["returned"] == 1 and body["truncated"] is True
    assert "truncated" in _codes(body)



def test_an_area_mismatch_reason_never_echoes_the_record(client, dirs) -> None:
    runs_dir, data_dir = dirs
    sha, _ = _staged(data_dir)
    observed = _observed(sha)
    observed["aoi_id"] = "C:\\secret\\boundary.geojson"
    _write_run(runs_dir, "city", aoi_id="bangkok-bma", observed=observed)

    body = client.get("/v1/runs/city/observed-water/ever").json()

    assert body["available"] is False
    assert "secret" not in body["reason"]
    assert all("secret" not in warning["message"] for warning in body["warnings"])
