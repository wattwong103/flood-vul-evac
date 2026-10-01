"""Exposure uses cell areas, including grids with different origins."""
import sys
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bkkflow.observed_evac import exposed_cells


def test_offset_cells_overlap_even_when_centres_are_far_apart():
    population = pd.DataFrame({"x": [900., 1000., 1001., 900.],
                               "y": [900., 0., 0., -900.]})
    water = gpd.GeoDataFrame(geometry=[Point(0, 0)], crs="EPSG:32647")
    # A 100-by-100 corner overlap counts; a shared edge does not.
    assert exposed_cells(population, water).tolist() == [True, False, False, True]


def test_several_water_cells_never_duplicate_population():
    population = pd.DataFrame({"x": [500., 5000.], "y": [500., 5000.]})
    water = gpd.GeoDataFrame(geometry=[Point(0, 0), Point(1000, 1000)], crs="EPSG:32647")
    assert exposed_cells(population, water).tolist() == [True, False]
    assert not exposed_cells(population, water.iloc[:0]).any()
