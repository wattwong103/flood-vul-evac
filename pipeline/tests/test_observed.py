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


def raster_fixture(tmp_path, values, *, name="water.tif", west=100.5):
    import rasterio
    from rasterio.transform import from_origin
    path = tmp_path / name
    with rasterio.open(path, "w", driver="GTiff", width=len(values), height=1,
                       count=1, dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(west, 13.7, 0.00025, 0.00025)) as dst:
        dst.write(np.array([values], dtype="uint8"), 1)
    return path, (west, 13.69975, west + len(values) * 0.00025, 13.7)


@pytest.mark.parametrize("clip", [False, True])
def test_source_coded_raster_preserves_water_classes(tmp_path, clip):
    # JRC Data Users Guide v4 p15: no observations, non-water, seasonal, permanent.
    from shapely.geometry import box
    path, bounds = raster_fixture(tmp_path, [0, 1, 2, 3])
    # All inside the max extent: code 0 is unobserved that year, not never-water.
    extent, _ = raster_fixture(tmp_path, [1, 1, 1, 1], name="extent.tif")
    result = gsw.measure_year(2020, path.name, path, bounds,
                              aoi_geometry=box(*bounds) if clip else None, extent_path=extent)
    assert result.aoi_water_pixels == 2
    assert result.classified_pixels == result.known_pixels == 3
    assert result.aoi_water_share == pytest.approx(2 / 3)
    assert result.aoi_seasonal_pixels == result.aoi_permanent_pixels == 1
    mask, _ = gsw.observed_water_mask(path, box(*bounds))
    assert mask.tolist() == [[False, False, True, True]]


def test_unobserved_area_is_not_reported_as_zero_flooding(tmp_path):
    path, bounds = raster_fixture(tmp_path, [0, 0])
    extent, _ = raster_fixture(tmp_path, [1, 255], name="extent.tif")
    result = gsw.measure_year(2020, path.name, path, bounds, extent_path=extent)
    assert result.aoi_water_share is None
    assert result.share_status == "no_known_pixels"
    assert result.as_dict()["aoi_water_share"] is None


@pytest.mark.parametrize("clip", [False, True])
def test_nodata_zero_tag_does_not_hide_no_observation_pixels(tmp_path, clip):
    import rasterio
    from shapely.geometry import box
    path, bounds = raster_fixture(tmp_path, [0, 1, 2, 3])
    with rasterio.open(path, "r+") as dst:
        dst.nodata = 0
    result = gsw.measure_year(2020, path.name, path, bounds,
                             aoi_geometry=box(*bounds) if clip else None)
    assert result.aoi_no_observation_pixels == 1
    assert result.aoi_water_pixels == 2


def test_road_outside_raster_does_not_inherit_border_water(monkeypatch):
    import geopandas as gpd
    from rasterio.transform import from_origin
    from shapely.geometry import LineString
    from bkkflow import observed_evac
    monkeypatch.setattr(observed_evac, "water_mask", lambda year:
        (np.ones((2, 2), dtype=bool), from_origin(0, 2, 1, 1), "EPSG:32647"))
    edges = gpd.GeoDataFrame(geometry=[LineString([(3, .5), (4, .5)])], crs="EPSG:32647")
    assert not observed_evac.edges_in_water(edges, 2020).any()


def test_unknown_source_code_is_rejected():
    with pytest.raises(ValueError, match="waterClass"):
        gsw.is_water(np.array([0, 1, 255], dtype="uint8"))


def test_water_outside_aoi_is_excluded(tmp_path):
    from shapely.geometry import box
    path, bounds = raster_fixture(tmp_path, [0, 1, 2, 3])
    aoi = box(bounds[0], bounds[1], bounds[2] - 0.00025, bounds[3])
    result = gsw.measure_year(2020, path.name, path, bounds, aoi_geometry=aoi)
    assert result.aoi_water_pixels == 1
    assert result.classified_pixels == 2


# --------------------------------------------------------------------------
# share denominator (BKK-054): yearly code 0 recoded with Maximum Water Extent
# --------------------------------------------------------------------------

# Code 0 outside the max extent was never detected as water in 1984-2021, so it
# is observed not-water. Code 0 inside it, or under extent no-data, is unknown.
YEARLY = [0, 0, 0, 0, 1, 2, 3]
EXTENT = [0, 0, 1, 255, 1, 1, 1]


@pytest.mark.parametrize("clip", [False, True])
def test_code_zero_outside_max_extent_stays_in_the_share_denominator(tmp_path, clip):
    from shapely.geometry import box
    yearly, bounds = raster_fixture(tmp_path, YEARLY)
    extent, _ = raster_fixture(tmp_path, EXTENT, name="extent.tif")
    aoi = box(*bounds) if clip else None
    result = gsw.measure_year(2020, yearly.name, yearly, bounds, aoi_geometry=aoi,
                              extent_path=extent)
    assert (result.aoi_pixels, result.classified_pixels) == (7, 3)
    assert (result.never_water_pixels, result.unknown_pixels, result.known_pixels) == (2, 2, 5)
    # 2 / 5, not 2 / 3: dividing by classified pixels drops never-water land.
    assert result.aoi_water_share == pytest.approx(2 / 5)
    assert result.share_status == "ok"
    assert result.known_km2 / result.aoi_water_km2 == pytest.approx(5 / 2)
    assert result.classified_km2 / result.aoi_water_km2 == pytest.approx(3 / 2)
    # Water area never reads the extent tile, so the denominator fix cannot move it.
    without = gsw.measure_year(2020, yearly.name, yearly, bounds, aoi_geometry=aoi)
    assert result.aoi_water_pixels == without.aoi_water_pixels == 2
    assert result.aoi_water_km2 == without.aoi_water_km2
    record = result.as_dict()
    assert record["aoi_water_share"] == pytest.approx(0.4)
    assert "aoi_area_km2" not in record and "aoi_total_pixels" not in record


def test_share_is_null_with_a_reason_when_max_extent_is_missing(tmp_path):
    yearly, bounds = raster_fixture(tmp_path, YEARLY)
    result = gsw.measure_year(2020, yearly.name, yearly, bounds)
    assert result.aoi_water_share is None
    assert result.share_status == "max_extent_unavailable"
    assert result.known_pixels is result.unknown_pixels is result.known_km2 is None
    assert result.aoi_water_pixels == 2 and result.classified_pixels == 3
    assert result.as_dict()["share_status"] == "max_extent_unavailable"


def test_max_extent_on_a_different_grid_is_refused(tmp_path):
    yearly, bounds = raster_fixture(tmp_path, YEARLY)
    extent, _ = raster_fixture(tmp_path, EXTENT, name="extent.tif", west=100.50025)
    with pytest.raises(ValueError, match="grid"):
        gsw.measure_year(2020, yearly.name, yearly, bounds, extent_path=extent)


def test_unknown_max_extent_code_is_rejected():
    with pytest.raises(ValueError, match="Maximum Water Extent"):
        gsw.share_support(np.array([0, 1], dtype="uint8"), np.array([0, 2], dtype="uint8"))


def test_extent_tile_uses_the_yearly_tile_offsets():
    bounds = (100.3279, 13.2191, 100.9386, 13.9552)
    assert gsw.extent_tile_name_for(bounds) == "extent-0000240000-0001120000.tif"


def _stage(tmp_path, fixture, name, url):
    from bkkflow.util import sha256_file, write_json
    directory = tmp_path / "gsw"
    directory.mkdir(exist_ok=True)
    tile = directory / name
    tile.write_bytes(fixture.read_bytes())
    write_json(tile.with_suffix(".provenance.json"), {
        "resource_url": url, "retrieved_at": "2026-10-20T00:00:00Z",
        "content_sha256": sha256_file(tile)})
    return tile


@pytest.mark.parametrize("with_extent", [True, False])
def test_observed_cells_share_the_measure_year_denominator(tmp_path, monkeypatch, with_extent):
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import box
    import build_observed_cells
    from bkkflow import aoi
    yearly, bounds = raster_fixture(tmp_path, YEARLY)
    extent, _ = raster_fixture(tmp_path, EXTENT, name="extent.tif")
    name = gsw.tile_name_for(2020, bounds)
    _stage(tmp_path, yearly, name, f"{gsw.BASE}/yearlyClassification2020/{name}")
    if with_extent:
        extent_name = gsw.extent_tile_name_for(bounds)
        _stage(tmp_path, extent, extent_name, f"{gsw.EXTENT_BASE}/{extent_name}")
    monkeypatch.setattr(gsw, "STAGED_DIR", tmp_path)
    monkeypatch.setattr(aoi, "load_aoi", lambda *a: gpd.GeoDataFrame(geometry=[box(*bounds)], crs="EPSG:4326"))
    monkeypatch.setattr(build_observed_cells, "YEARS", (2020,))
    result = build_observed_cells.build(out_dir=tmp_path / "output")
    frame = pd.read_parquet(result["path"])
    assert "classified_px" not in frame.columns
    assert frame["water_px"].sum() == 2
    if with_extent:
        assert frame["known_px"].sum() == 5
        assert frame["water_share"].tolist() == pytest.approx(
            (frame["water_px"] / frame["known_px"]).tolist())
        assert result["per_year"][2020]["share_status"] == "ok"
    else:
        assert frame["water_share"].isna().all() and frame["known_px"].isna().all()
        assert result["per_year"][2020]["share_status"] == "max_extent_unavailable"


def test_gsw_max_extent_is_its_own_licence_gated_resource():
    # Yearly code 0 cannot be split into "never water" and "unobserved" without
    # the Maximum Water Extent product (guide p12: 0 not water, 1 water
    # detected, 255 no data). The licence gate is per resource, so it needs its
    # own entry rather than riding on the yearly classification's approval.
    from bkkflow.sources.registry import REGISTRY_PATH, SourceRegistry
    from bkkflow.util import read_json
    registry = SourceRegistry(read_json(REGISTRY_PATH))
    yearly = registry.get(gsw.SOURCE_ID)
    extent = registry.get("jrc-global-surface-water-max-extent-v1.4")
    assert yearly.resource_url.endswith("/GSWE/YearlyClassification/LATEST/tiles/")
    assert extent.resource_url.endswith("/GSWE/Aggregated/LATEST/extent/tiles/")
    assert extent.licence.startswith("CC BY 4.0")
    assert extent.raw["licence_url"].endswith("/GSWE/Aggregated/copyright.txt")
    assert extent.raw["used_in_runs"] is True  # BKK-054b: the share denominator reads it


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
