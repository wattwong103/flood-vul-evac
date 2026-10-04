"""Exercise the complete pilot path through its separate publication helper."""
import sys
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bkkflow import runner
from bkkflow.util import read_json, write_json
from test_pipeline import _roads


@pytest.fixture
def pilot_inputs(tmp_path, monkeypatch):
    curated = tmp_path / "curated"
    for directory in ("population", "osm"):
        (curated / directory).mkdir(parents=True)
    area = gpd.GeoDataFrame(geometry=[box(100.4995, 13.7195, 100.5025, 13.7215)], crs=4326)
    cells = gpd.GeoDataFrame({
        "cell_id": ["one", "two"], "population_version": ["test"] * 2,
        "pop_count": [100.0, 200.0], "area_m2": [10000.0] * 2,
        "pop_density_per_m2": [0.01, 0.02],
        "lon": [100.500, 100.501], "lat": [13.720, 13.721],
    }, geometry=[box(100.4999, 13.7199, 100.5001, 13.7201),
                 box(100.5009, 13.7209, 100.5011, 13.7211)], crs=4326)
    cells.to_parquet(curated / "population/population_cells.parquet")
    _roads().to_parquet(curated / "osm/roads.parquet")
    buildings = gpd.GeoDataFrame({
        "osm_id": [101, 102, 103], "building": ["house"] * 3,
        "height": [10.0] * 3, "building:levels": [None] * 3,
    }, geometry=[box(x, 13.7201, x + .0001, 13.7202)
                 for x in (100.500, 100.501, 100.502)], crs=4326)
    buildings.to_parquet(curated / "osm/buildings.parquet")
    water = gpd.GeoDataFrame({"water_kind": ["canal"]},
        geometry=[LineString([(100.4996, 13.7195), (100.4996, 13.7215)])], crs=4326)
    water.to_parquet(curated / "osm/water.parquet")
    fetch = {"retrieved_at": "2026-10-04T00:00:00+00:00",
             "content_sha256": "1" * 64, "query_sha256": "2" * 64}
    write_json(curated / "osm/provenance.json", {"fetches": [fetch] * 3})
    write_json(curated / "aoi/khlong-san-district.provenance.json", {
        **fetch, "aoi_id": "khlong-san-district", "osm_id": 3147280,
    })
    monkeypatch.setattr(runner, "CURATED_DIR", curated)
    monkeypatch.setattr(runner, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(runner.aoi_module, "load_aoi", lambda _: area)
    return tmp_path / "runs"


@pytest.mark.parametrize("flood_enabled", [False, True])
def test_pilot_publishes_verified_source_identity(pilot_inputs, flood_enabled):
    result = runner.execute_run(flood_enabled=flood_enabled, max_agents=10)
    run = Path(result["run_dir"])
    assert result["validation_passed"]
    assert read_json(run / "run_state.json")["state"] == "published"
    manifest = read_json(run / "manifest.json")
    assert manifest["code_identity"]["verification"] == "matched_before_publication"
    assert len(manifest["code_identity"]["source_sha256"]) == 64
    assert runner.manifest_module.validate_manifest(manifest) == []


@pytest.mark.parametrize("check_number", [1, 2])
def test_pilot_drift_at_either_publication_check_stays_failed(pilot_inputs, monkeypatch, check_number):
    verify = runner.verify_code_identity
    checks = 0

    def drift(before, run_dir):
        nonlocal checks
        checks += 1
        if checks == check_number:
            before = {**before, "source_sha256": "0" * 64}
        return verify(before, run_dir)

    monkeypatch.setattr(runner, "verify_code_identity", drift)
    with pytest.raises(RuntimeError, match="Source changed"):
        runner.execute_run(max_agents=10)
    run = next(pilot_inputs.iterdir())
    assert read_json(run / "run_state.json")["state"] == "failed_source_changed"
    assert (run / "manifest.json").exists() == (check_number == 2)
