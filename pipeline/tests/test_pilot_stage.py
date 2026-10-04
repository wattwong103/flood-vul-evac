"""Four-area staging is source-verified, scoped and tamper-evident."""

import json
import shutil
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pyogrio
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, MultiPolygon, Polygon, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow.sources import city_osm, pilot_stage
from bkkflow.util import sha256_file, write_json


OSM_URL = "https://download.geofabrik.de/asia/thailand-260929.osm.pbf"
POP_URL = "https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/THA/tha_ppp_2020.tif"


@pytest.fixture
def stage_inputs(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    (config_dir / "pilots").mkdir(parents=True)
    source_config = Path(__file__).resolve().parents[2] / "config"
    shutil.copyfile(source_config / "population.json", config_dir / "population.json")
    shutil.copyfile(source_config / "scenario.json", config_dir / "scenario.json")

    aoi_geometry = MultiPolygon([box(100.005, 13.965, 100.035, 13.995)])
    aoi = gpd.GeoDataFrame(
        {"osm_id": ["999"], "name": ["Test"], "admin_level": ["6"],
         "boundary": ["administrative"], "other_tags": [None]},
        geometry=[aoi_geometry], crs="EPSG:4326",
    )
    area_km2 = round(float(aoi.to_crs("EPSG:32647").geometry.area.iloc[0]) / 1e6, 4)

    staged = tmp_path / "staged"
    pbf = staged / "osm/source.osm.pbf"
    pbf.parent.mkdir(parents=True)
    pbf.write_bytes(b"verified pbf")
    write_json(pbf.with_suffix(".provenance.json"), {
        "url": OSM_URL, "retrieved_at": "2026-09-29T00:00:00+00:00",
        "content_sha256": sha256_file(pbf),
    })
    coverage = staged / "osm/source.poly"
    coverage.write_text("test\n1\n99 13\n101 13\n101 15\n99 15\nEND\nEND\n", encoding="utf-8")

    population = staged / "population/source.tif"
    population.parent.mkdir(parents=True)
    values = (np.arange(1, 17, dtype="float32") + np.float32(0.123456)).reshape(4, 4)
    with rasterio.open(population, "w", driver="GTiff", width=4, height=4, count=1,
                       dtype="float32", crs="EPSG:4326",
                       transform=from_origin(100.0, 14.0, 0.01, 0.01), nodata=-99999.0) as dst:
        dst.write(values, 1)
    write_json(population.with_suffix(".provenance.json"), {
        "resource_url": POP_URL, "retrieved_at": "2026-09-29T00:00:00+00:00",
        "content_sha256": sha256_file(population),
    })

    city_dir = tmp_path / "city"
    city_dir.mkdir()
    layers = {
        "roads": gpd.GeoDataFrame({"osm_id": [1]}, geometry=[
            LineString([(100.0, 13.98), (100.04, 13.98)])], crs="EPSG:4326"),
        "buildings": gpd.GeoDataFrame({"osm_id": [2], "building": ["yes"]},
            geometry=[Polygon([(100.01, 13.97), (100.02, 13.98), (100.01, 13.98),
                               (100.02, 13.97), (100.01, 13.97)])], crs="EPSG:4326"),
        "water_lines": gpd.GeoDataFrame({"osm_id": [3], "water_kind": ["canal"]},
            geometry=[LineString([(100.02, 13.96), (100.02, 14.0)])], crs="EPSG:4326"),
    }
    layer_records = {}
    for name, frame in layers.items():
        path = city_dir / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        layer_records[name] = {"layer": name, "rows": len(frame), "crs": "EPSG:4326",
                               "sha256": sha256_file(path), "path": str(path)}
    coverage_record = city_osm.source_coverage(coverage, aoi)
    write_json(city_dir / "provenance.json", {
        "source_id": "geofabrik-thailand-osm-20260929", "pbf_path": str(pbf),
        "content_sha256": sha256_file(pbf), "retrieved_at": "2026-09-29T00:00:00+00:00",
        "resource_url": OSM_URL, "coverage": coverage_record, "layers": layer_records,
    })

    geometry_hash = pilot_stage.geometry_sha256(aoi_geometry)
    write_json(config_dir / "pilots/test-district.json", {
        "input_scope": "test-district", "analysis_crs": "EPSG:32647",
        "aoi": {"aoi_id": "test-district", "name": "Test", "name_en": "Test",
                "admin_level": "6", "osm_relation_id": 999, "area_km2": area_km2},
        "versions": {"population": "population-test-district", "network": "network-test-district",
                     "buildings": "buildings-test-district"},
        "sources": {"osm": "geofabrik-thailand-osm-20260929",
                    "population": "worldpop-global-2000-2020-tha-100m"},
        "source_sha256": {"osm": sha256_file(pbf), "population": sha256_file(population),
                          "geometry": geometry_hash},
        "flood_scenario_id": "bangkok-moderate-distance-to-water",
    })
    monkeypatch.setattr(pyogrio, "read_dataframe", lambda *args, **kwargs: aoi.copy())
    return {"config": config_dir, "curated": tmp_path / "curated", "city": city_dir,
            "pbf": pbf, "coverage": coverage, "population": population, "aoi": aoi}


def _stage(paths):
    return pilot_stage.stage_pilot(
        "test-district", config_dir=paths["config"], curated_dir=paths["curated"],
        city_dir=paths["city"], pbf_path=paths["pbf"], coverage_path=paths["coverage"],
        population_path=paths["population"],
    )


def test_stage_writes_complete_scoped_outputs_and_reopens_them(stage_inputs):
    result = _stage(stage_inputs)
    root = stage_inputs["curated"] / "pilots/test-district"
    assert result["state"] == "complete"
    assert result["aoi_id"] == "test-district"
    assert set(result["inputs"]["osm"]["cached_layer_sha256"]) == {
        "roads", "buildings", "water_lines"
    }
    assert result["geometry"]["osm_relation_id"] == 999
    assert (root / "stage_manifest.json").is_file()
    assert pilot_stage.validate_staged_pilot(root)["state"] == "complete"
    assert len(gpd.read_parquet(root / "aoi.parquet")) == 1
    assert len(gpd.read_parquet(root / "osm/roads.parquet")) == 1
    assert gpd.read_parquet(root / "population/population_cells.parquet")["pop_count"].sum() > 0
    osm_provenance = json.loads((root / "osm/provenance.json").read_text(encoding="utf-8"))
    assert osm_provenance["layers"]["buildings"]["geometry_diagnostics"]["predicate_repairs"] == 1
    assert _stage(stage_inputs)["reused"] is True


def test_stage_and_runner_validation_reject_changed_output(stage_inputs):
    _stage(stage_inputs)
    root = stage_inputs["curated"] / "pilots/test-district"
    roads = root / "osm/roads.parquet"
    roads.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Staged output changed"):
        pilot_stage.validate_staged_pilot(root)
    with pytest.raises(ValueError, match="Staged output changed"):
        _stage(stage_inputs)
    assert roads.read_bytes() == b"tampered"


def test_existing_stage_must_match_current_pilot_config(stage_inputs):
    _stage(stage_inputs)
    config_path = stage_inputs["config"] / "pilots/test-district.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["source_sha256"]["population"] = "f" * 64
    write_json(config_path, payload)
    with pytest.raises(ValueError, match="source hash mismatch"):
        _stage(stage_inputs)


def test_incomplete_provenance_has_clear_error(stage_inputs):
    _stage(stage_inputs)
    root = stage_inputs["curated"] / "pilots/test-district"
    provenance = root / "population/provenance.json"
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    payload.pop("resource_url")
    write_json(provenance, payload)
    with pytest.raises(ValueError, match="Incomplete staged provenance"):
        pilot_stage.validate_staged_pilot(root)


def test_boundary_relation_must_match_configuration(stage_inputs, monkeypatch):
    wrong = stage_inputs["aoi"].copy()
    wrong["osm_id"] = "1000"
    monkeypatch.setattr(pyogrio, "read_dataframe", lambda *args, **kwargs: wrong)
    with pytest.raises(ValueError, match="exactly one boundary"):
        _stage(stage_inputs)
