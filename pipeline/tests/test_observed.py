"""Tests for the observed-extent and destination-candidate modules.

Source-coded raster fixtures independently check the JRC waterClass contract.
An OSM tag must never emerge from this code path as a verified refuge.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow.sources import destinations, gsw  # noqa: E402


# --------------------------------------------------------------------------
# JRC classification codes
# --------------------------------------------------------------------------


def raster_fixture(tmp_path, values):
    import rasterio
    from rasterio.transform import from_origin
    path = tmp_path / "water.tif"
    with rasterio.open(path, "w", driver="GTiff", width=len(values), height=1,
                       count=1, dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(100.5, 13.7, 0.00025, 0.00025)) as dst:
        dst.write(np.array([values], dtype="uint8"), 1)
    return path, (100.5, 13.69975, 100.5 + len(values) * 0.00025, 13.7)


@pytest.mark.parametrize("clip", [False, True])
def test_source_coded_raster_preserves_water_classes(tmp_path, clip):
    # JRC Data Users Guide v4 p15: no observations, non-water, seasonal, permanent.
    from shapely.geometry import box
    path, bounds = raster_fixture(tmp_path, [0, 1, 2, 3])
    result = gsw.measure_year(2020, path.name, path, bounds,
                              aoi_geometry=box(*bounds) if clip else None)
    assert result.aoi_water_pixels == 2
    assert result.aoi_total_pixels == 3
    assert result.aoi_water_share == pytest.approx(2 / 3)
    assert result.aoi_seasonal_pixels == result.aoi_permanent_pixels == 1
    mask, _ = gsw.observed_water_mask(path, box(*bounds))
    assert mask.tolist() == [[False, False, True, True]]


def test_unobserved_area_is_not_reported_as_zero_flooding(tmp_path):
    path, bounds = raster_fixture(tmp_path, [0, 0])
    result = gsw.measure_year(2020, path.name, path, bounds)
    assert result.aoi_water_share is None
    assert result.as_dict()["aoi_water_share"] is None


def test_unknown_source_code_is_rejected():
    with pytest.raises(ValueError, match="waterClass"):
        gsw.is_water(np.array([0, 1, 255], dtype="uint8"))


def test_water_outside_aoi_is_excluded(tmp_path):
    from shapely.geometry import box
    path, bounds = raster_fixture(tmp_path, [0, 1, 2, 3])
    aoi = box(bounds[0], bounds[1], bounds[2] - 0.00025, bounds[3])
    result = gsw.measure_year(2020, path.name, path, bounds, aoi_geometry=aoi)
    assert result.aoi_water_pixels == 1
    assert result.aoi_total_pixels == 2


@pytest.mark.parametrize("wet_column", [1, 6, 11])
def test_road_samples_cover_each_entire_edge_without_mixing_edges(monkeypatch, wet_column):
    import geopandas as gpd
    from rasterio.transform import from_origin
    from shapely.geometry import LineString
    from bkkflow import observed_evac
    wet = np.zeros((3, 20), dtype=bool)
    wet[0, wet_column] = True
    monkeypatch.setattr(observed_evac, "water_mask", lambda year:
        (wet, from_origin(0, 3, 1, 1), "EPSG:32647"))
    edges = gpd.GeoDataFrame(geometry=[LineString([(1, 2.5), (11, 2.5)]),
        LineString([(1, 1.5), (11, 1.5)])], crs="EPSG:32647")
    assert observed_evac.edges_in_water(edges, 2020).tolist() == [True, False]


# --------------------------------------------------------------------------
# tile addressing
# --------------------------------------------------------------------------


def test_tile_name_for_bangkok_is_the_known_good_tile() -> None:
    # Verified by downloading it: the tile covers lon 100-110, lat 10-20.
    name = gsw.tile_name_for(2011, (100.3279, 13.2191, 100.9386, 13.9552))
    assert name == "yearlyClassification2011-0000240000-0001120000.tif"


def test_tile_name_uses_the_top_edge_not_the_bottom() -> None:
    """A tile 10 degrees further south than the AOI would be a real file for
    the wrong place, so the regression has to be pinned."""
    bangkok = gsw.tile_name_for(2011, (100.33, 13.22, 100.94, 13.96))
    # Latitude band 10-20 must not resolve to the 0-10 band.
    assert "0000240000" in bangkok
    assert "0000280000" not in bangkok


def test_tile_name_reference_tiles() -> None:
    # Measured directly from the downloaded rasters.
    assert gsw.tile_name_for(2011, (-180, 70, -170, 80)) == (
        "yearlyClassification2011-0000000000-0000000000.tif"
    )
    assert gsw.tile_name_for(2011, (-180, 60, -170, 70)) == (
        "yearlyClassification2011-0000040000-0000000000.tif"
    )


def test_tile_name_handles_a_bound_exactly_on_the_band_edge() -> None:
    # Northern edge at 80N belongs to the 70-80 band, not a hypothetical 80-90.
    assert gsw.tile_name_for(2011, (-180, 70, -170, 80)).startswith(
        "yearlyClassification2011-0000000000"
    )


def test_tile_name_refuses_to_straddle_a_tile_edge() -> None:
    with pytest.raises(ValueError):
        gsw.tile_name_for(2011, (95.0, 5.0, 125.0, 25.0))


# --------------------------------------------------------------------------
# summary statistics
# --------------------------------------------------------------------------


def test_observed_payload_declares_it_is_not_depth() -> None:
    assert "NOT depth" in gsw.__doc__ or "not depth" in gsw.__doc__.lower()


# --------------------------------------------------------------------------
# destinations
# --------------------------------------------------------------------------


def test_every_destination_class_maps_to_an_amenity() -> None:
    for amenity, destination_class in destinations.DESTINATION_AMENITIES.items():
        assert isinstance(amenity, str)
        assert destination_class


def test_shelter_is_a_candidate_class_never_a_refuge_class() -> None:
    assert destinations.DESTINATION_AMENITIES["shelter"] == "shelter_candidate"
    assert "shelter_candidate" in destinations.NEVER_REFUGE_CLASSES


def test_destination_module_states_tags_are_not_guarantees() -> None:
    text = destinations.__doc__ or ""
    assert "lead, not a refuge" in text
    assert "verified=False" in text
