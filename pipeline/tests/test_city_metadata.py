"""Run metadata describes the bytes and features actually used."""
import sys
from pathlib import Path
import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, box
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bkkflow import city_runner
from bkkflow.sources import city_osm
from bkkflow.util import read_json, sha256_file, write_json


def test_water_stats_describe_saved_features_and_exclude_polygon_perimeters(tmp_path):
    water = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (100, 0)]),
        box(10, 10, 20, 20), LineString([(500, 500), (600, 500)])], crs="EPSG:32647")
    aoi = gpd.GeoDataFrame(geometry=[box(-1, -1, 200, 200)], crs=water.crs)
    result = city_runner.save_mapped_water(water, aoi, "EPSG:32647", tmp_path)
    assert result["features"] == len(pd.read_parquet(tmp_path / "water_features.parquet")) == 2
    assert result["waterway_length_km"] == .1
    assert result["water_area_km2"] == .0001


def test_population_version_uses_own_verified_download(tmp_path, monkeypatch):
    source = tmp_path / "population.tif"
    source.write_bytes(b"population raster")
    monkeypatch.setattr(city_runner, "WORLDPOP_RASTER", source)
    write_json(source.with_suffix(".provenance.json"), {
        "resource_url": city_runner.WORLDPOP_URL, "retrieved_at": "2026-09-29T17:12:01Z",
        "content_sha256": sha256_file(source)})
    result = city_runner.population_source_version("bangkok-bma")
    assert result["retrieved_at"] == "2026-09-29T17:12:01Z"
    assert result["source_id"] == "worldpop-global-2000-2020-tha-100m"
    assert result["request_parameters"]["resource_url"] == city_runner.WORLDPOP_URL


def test_coverage_manifest_ref_is_small_and_hashes_separate_geometry(tmp_path):
    coverage = {"polygon_wkt": box(100, 13, 101, 14).wkt, "covers_aoi": True, "path": "/private/local/cache.poly",
                "sha256": "source-poly-hash", "crs": "EPSG:4326"}
    result = city_runner.save_coverage(coverage, tmp_path)
    assert "polygon_wkt" not in result
    assert result["geometry_sha256"] == sha256_file(tmp_path / result["geometry_uri"])
    assert read_json(tmp_path / result["geometry_uri"])["polygon_wkt"] == coverage["polygon_wkt"]
    assert "path" not in read_json(tmp_path / result["geometry_uri"])


@pytest.mark.parametrize("body", ["name\n1\n100 13\nEND\nEND", "name\n1\nx y\nEND\nEND",
                                     "name\n1\n100 13\n101 13\n101 14\n100 14"])
def test_malformed_source_polygon_has_clear_diagnostic(tmp_path, body):
    path = tmp_path / "bad.poly"
    path.write_text(body)
    with pytest.raises(ValueError, match="Malformed OSM coverage polygon"):
        city_osm.source_coverage(path, gpd.GeoDataFrame(geometry=[box(100.1, 13.1, 100.2, 13.2)], crs="EPSG:4326"))


def test_cache_validation_uses_recorded_coverage_path(tmp_path, monkeypatch):
    path = tmp_path / "custom.poly"
    path.write_text("name\n1\n100 13\n101 13\n101 14\n100 14\nEND\nEND\n")
    aoi = gpd.GeoDataFrame(geometry=[box(100.1, 13.1, 100.2, 13.2)], crs="EPSG:4326")
    coverage = city_osm.source_coverage(path, aoi)
    monkeypatch.setattr(city_osm, "source_provenance", lambda *a: {"content_sha256": "pbf"})
    record = {"source_id": city_osm.SOURCE_ID, "pbf_path": "unused", "resource_url": "unused",
              "content_sha256": "pbf", "coverage": coverage, "layers": {}}
    city_osm.validate_cached_ingest(record, aoi, tmp_path)
    path.write_text("changed")
    with pytest.raises(ValueError):
        city_osm.validate_cached_ingest(record, aoi, tmp_path)


def test_coverage_on_another_drive_remains_usable(tmp_path, monkeypatch):
    path = tmp_path / "coverage.poly"
    path.write_text("name\n1\n100 13\n101 13\n101 14\n100 14\nEND\nEND\n")
    aoi = gpd.GeoDataFrame(geometry=[box(100.1, 13.1, 100.2, 13.2)], crs="EPSG:4326")
    def another_drive(*args):
        raise ValueError("path is on mount D:, start on mount C:")
    monkeypatch.setattr(city_osm.os.path, "relpath", another_drive)
    assert Path(city_osm.source_coverage(path, aoi)["path"]) == path.resolve()
