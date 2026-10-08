"""Closures may remove paths, but must never move access points."""
import sys
from pathlib import Path
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bkkflow import observed_evac as screening
from bkkflow.city_network import CityRoutingIndex
from bkkflow.city_method import SNAP_TOLERANCE_M, ROUTING_CUTOFF_MINUTES


def roads():
    lines = [LineString([(0, 0), (100, 0)]), LineString([(100, 0), (200, 0)])]
    return gpd.GeoDataFrame({"edge_id": ["a", "b"], "u": [0, 1], "v": [1, 2],
        "length_m": [100., 100.], "walk_allowed": [True, True],
        "speed_walk_mps": [1., 1.], "geometry_wkt": [p.wkt for p in lines]},
        geometry=lines, crs="EPSG:32647")


def test_closed_access_edge_does_not_move_origin(tmp_path, monkeypatch):
    edges = roads()
    targets = gpd.GeoDataFrame(geometry=[Point(200, 0)], crs=edges.crs)
    water = gpd.GeoDataFrame(geometry=[Point(0, 0)], crs=edges.crs)
    pd.DataFrame({"x": [0.], "y": [0.], "pop": [10.]}).to_parquet(tmp_path / "population_grid_1km.parquet")
    monkeypatch.setattr(screening, "_load", lambda p: edges if p.name == "network_edges.parquet" else targets)
    monkeypatch.setattr(screening, "_water_cell_geometries", lambda *a: water)
    monkeypatch.setattr(screening, "edges_in_water", lambda *a: np.array([True, False]))
    cutoffs = []
    original = CityRoutingIndex.dijkstra
    def record_cutoff(self, source, *, cutoff=None):
        cutoffs.append(cutoff)
        return original(self, source, cutoff=cutoff)
    monkeypatch.setattr(CityRoutingIndex, "dijkstra", record_cutoff)
    closed = screening.run_connectivity_screening(run_dir=tmp_path, closure_fraction=1)
    reopened = screening.run_connectivity_screening(run_dir=tmp_path, closure_fraction=0)
    assert closed.reachable_population == 0
    assert reopened.reachable_population == 10
    assert closed.no_network_access_cells == reopened.no_network_access_cells == 0
    assert cutoffs == [ROUTING_CUTOFF_MINUTES * 60] * 2
    assert reopened.as_dict()["routing_cutoff_minutes"] == ROUTING_CUTOFF_MINUTES


def test_nested_closures_are_independent_of_input_row_order():
    ids = np.array([f"edge-{i}" for i in range(100)])
    wet = np.ones(100, dtype=bool)
    masks = [screening.closure_mask(wet, ids, f) for f in (0, .25, .5, 1)]
    assert [int(m.sum()) for m in masks] == [0, 25, 50, 100]
    assert all(np.all(a <= b) for a, b in zip(masks, masks[1:]))
    reversed_mask = screening.closure_mask(wet[::-1], ids[::-1], .5)
    assert set(ids[masks[2]]) == set(ids[::-1][reversed_mask])
    with pytest.raises(ValueError):
        screening.closure_mask(wet, ids, float("nan"))


def test_empty_and_isolated_nodes_remain_safe():
    edges = roads()
    index = CityRoutingIndex(edges, np.zeros(2, dtype=bool), np.ones(2),
                             anchor_mask=np.ones(2, dtype=bool))
    assert index.nearest_node(0, 0, index.coords) == 0
    costs, _ = index.dijkstra(2)
    assert np.isinf(costs[:2]).all()
    empty = CityRoutingIndex(edges, np.zeros(2, dtype=bool), np.ones(2))
    assert empty.nearest_node(0, 0, empty.coords) is None


def test_routing_cutoff_excludes_unsettled_costs():
    index = CityRoutingIndex(roads(), np.ones(2, dtype=bool), np.ones(2))
    costs, _ = index.dijkstra(0, cutoff=150)
    assert costs[:2].tolist() == [0, 100]
    assert np.isinf(costs[2])


def test_access_tolerance_includes_boundary_but_not_more():
    index = CityRoutingIndex(roads(), np.ones(2, dtype=bool), np.ones(2))
    assert index.nearest_node(0, SNAP_TOLERANCE_M, index.coords) == 0
    assert index.nearest_node(0, SNAP_TOLERANCE_M + .001, index.coords) is None
