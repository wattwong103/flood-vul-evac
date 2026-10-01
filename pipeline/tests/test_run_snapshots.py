"""Regression checks for immutable city inputs and screening snapshots."""
import sys
from pathlib import Path
from types import SimpleNamespace
import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bkkflow import city_runner, observed_evac
from bkkflow.sources import gsw
from test_observed import raster_fixture


def test_existing_run_is_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(city_runner, "RUNS_DIR", tmp_path)
    run = tmp_path / "saved"
    run.mkdir()
    sentinel = run / "stats.json"
    sentinel.write_text("saved results")
    def stop_before_processing(*args):
        raise AssertionError("an existing run reached source processing")
    monkeypatch.setattr(city_runner, "load_config", stop_before_processing)
    with pytest.raises(FileExistsError):
        city_runner.execute_city_run(run_id="saved")
    assert sentinel.read_text() == "saved results"


def test_screening_reads_selected_run_water_cells(tmp_path):
    selected = tmp_path / "selected"
    selected.mkdir()
    pd.DataFrame({"year": [2020], "x": [661500.], "y": [1517500.],
                  "lon": [100.5], "lat": [13.7]}).to_parquet(selected / "observed_water_cells.parquet")
    assert len(observed_evac._water_cell_geometries(2020, selected)) == 1
    with pytest.raises(FileNotFoundError):
        observed_evac._water_cell_geometries(2020, tmp_path / "missing")


def test_water_cache_retains_original_retrieval_and_rejects_changed_bytes(tmp_path, monkeypatch):
    tile, bounds = raster_fixture(tmp_path, [0, 1, 2, 3])
    body = tile.read_bytes()
    calls = []
    def fetch(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(body=body, retrieved_at="2026-09-29T00:00:00Z")
    monkeypatch.setattr(gsw, "STAGED_DIR", tmp_path / "staged")
    aoi = gpd.GeoDataFrame(geometry=[box(*bounds)], crs="EPSG:4326")
    client = SimpleNamespace(get=fetch)
    first = gsw.fetch_years(client, [2020], bounds, aoi)
    again = gsw.fetch_years(client, [2020], bounds, aoi)
    assert len(calls) == 1
    assert again["years"][0]["retrieved_at"] == first["years"][0]["retrieved_at"] == "2026-09-29T00:00:00Z"
    Path(first["years"][0]["local_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="provenance"):
        gsw.fetch_years(client, [2020], bounds, aoi)


def test_screening_keeps_node_zero_and_honours_zero_closure(tmp_path, monkeypatch):
    from shapely.geometry import LineString, Point
    edges = gpd.GeoDataFrame({"geometry_wkt": ["LINESTRING (0 0, 10 0)"],
        "walk_allowed": [True], "speed_walk_mps": [1.25], "edge_id": ["test"]},
        geometry=[LineString([(0, 0), (10, 0)])], crs="EPSG:32647")
    pd.DataFrame({"x": [0.], "y": [0.], "pop": [10.]}).to_parquet(tmp_path / "population_grid_1km.parquet")
    points = gpd.GeoDataFrame(geometry=[Point(0, 0)], crs="EPSG:32647")
    monkeypatch.setattr(observed_evac, "_load", lambda p: edges if p.name == "network_edges.parquet" else points)
    monkeypatch.setattr(observed_evac, "_water_cell_geometries", lambda *a: points)
    monkeypatch.setattr(observed_evac, "edges_in_water", lambda *a: __import__('numpy').array([True]))
    class Index:
        def __init__(self, edges, opened, speeds, **kwargs):
            self.coords = __import__('numpy').array([[0., 0.]])
            self.node_count = 1
        def nearest_node(self, *args): return 0
        def dijkstra(self, *args, **kwargs): return __import__('numpy').array([0.]), None
    monkeypatch.setattr(observed_evac, "CityRoutingIndex", Index)
    result = observed_evac.run_connectivity_screening(run_dir=tmp_path, closure_fraction=0)
    assert result.reachable_population == 10
    assert result.closed_edges == 0
