"""Tests for the JRC Maximum Water Extent summary (BKK-055c).

The extent marks every pixel ever detected as water in 1984-2021 (code 1),
never-water (0) and no-data (255). No-data is unknown, never dry, and only
pixels inside the AOI count.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow.sources import gsw  # noqa: E402

WEST, NORTH = 100.5, 13.7


def extent_fixture(tmp_path, rows, *, nodata=None, crs="EPSG:4326", step=0.00025, name="extent.tif",
                   transform=None):
    import rasterio
    from rasterio.transform import from_origin

    path = tmp_path / name
    array = np.array(rows, dtype="uint8")
    with rasterio.open(path, "w", driver="GTiff", width=array.shape[1], height=array.shape[0],
                       count=1, dtype="uint8", crs=crs, nodata=nodata,
                       transform=transform or from_origin(WEST, NORTH, step, step)) as dst:
        dst.write(array, 1)
    bounds = (WEST, NORTH - array.shape[0] * 0.00025, WEST + array.shape[1] * 0.00025, NORTH)
    return path, bounds


def pixel_area_km2(bounds):
    return (gsw.PIXEL_DEGREES * 111.32) ** 2 * np.cos(np.radians((bounds[1] + bounds[3]) / 2))


def test_extent_counts_water_and_keeps_no_data_unknown(tmp_path):
    from shapely.geometry import box

    path, bounds = extent_fixture(tmp_path, [[1, 1, 0, 255], [0, 1, 0, 0]])
    result = gsw.measure_extent(path, box(*bounds))

    assert result["aoi_pixels"] == 8
    assert result["ever_water_pixels"] == 3
    assert result["no_data_pixels"] == 1
    assert result["ever_water_km2"] == pytest.approx(3 * pixel_area_km2(bounds))
    assert result["no_data_km2"] == pytest.approx(1 * pixel_area_km2(bounds))
    # No-data is unknown, so the share is over the 7 observed pixels.
    assert result["ever_water_share_of_observed"] == pytest.approx(3 / 7)


def test_extent_counts_only_pixels_inside_the_aoi(tmp_path):
    from shapely.geometry import box

    path, bounds = extent_fixture(tmp_path, [[1, 1, 0, 255], [0, 1, 0, 0]])
    left_half = box(bounds[0], bounds[1], bounds[0] + 2 * 0.00025, bounds[3])
    result = gsw.measure_extent(path, left_half)

    assert result["aoi_pixels"] == 4
    assert result["ever_water_pixels"] == 3
    assert result["no_data_pixels"] == 0


def test_extent_cells_add_up_to_the_total(tmp_path):
    from shapely.geometry import box

    path, bounds = extent_fixture(tmp_path, [[1, 1, 0, 255], [0, 1, 0, 0]])
    result = gsw.measure_extent(path, box(*bounds))
    cells = result["cells"]

    assert cells, "water inside the AOI must produce at least one 1 km cell"
    assert sum(cell["water_px"] for cell in cells) == result["ever_water_pixels"]
    assert sum(cell["water_km2"] for cell in cells) == pytest.approx(result["ever_water_km2"])
    for cell in cells:
        assert cell["cell_id"].startswith("ow_")
        assert 0 < cell["water_share"] <= 1
        assert 99 < cell["lon"] < 102 and 12 < cell["lat"] < 15


def test_extent_with_no_observed_pixels_has_no_share(tmp_path):
    from shapely.geometry import box

    path, bounds = extent_fixture(tmp_path, [[255, 255]])
    result = gsw.measure_extent(path, box(*bounds))

    assert result["ever_water_pixels"] == 0
    assert result["ever_water_share_of_observed"] is None
    assert result["cells"] == []


def test_extent_with_an_unexpected_nodata_tag_is_refused(tmp_path):
    from shapely.geometry import box

    # A nodata tag of 0 would turn never-water into unknown.
    path, bounds = extent_fixture(tmp_path, [[1, 0]], nodata=0)
    with pytest.raises(ValueError, match="nodata"):
        gsw.measure_extent(path, box(*bounds))



# ---------------------------------------------------------------------------
# Review regressions.
# ---------------------------------------------------------------------------


def test_extent_with_codes_outside_the_product_is_refused(tmp_path):
    from shapely.geometry import box

    path, bounds = extent_fixture(tmp_path, [[1, 2]])
    with pytest.raises(ValueError, match="codes"):
        gsw.measure_extent(path, box(*bounds))


def test_extent_on_another_grid_is_refused(tmp_path):
    from shapely.geometry import box

    path, bounds = extent_fixture(tmp_path, [[1, 0]], step=0.001)
    with pytest.raises(ValueError, match="grid"):
        gsw.measure_extent(path, box(*bounds))


def test_an_aoi_reaching_beyond_the_tile_is_refused_not_truncated(tmp_path):
    from shapely.geometry import box

    path, bounds = extent_fixture(tmp_path, [[1, 0, 0, 1], [0, 1, 0, 0]])
    wider = box(bounds[0], bounds[1], bounds[2] + 4 * 0.00025, bounds[3])
    with pytest.raises(ValueError, match="beyond"):
        gsw.measure_extent(path, wider)


def test_extent_cells_span_the_public_grid_with_the_yearly_cell_ids(tmp_path):
    from shapely.geometry import box

    from build_observed_cells import cell_id
    from bkkflow.city_method import PUBLIC_GRID_M

    rows = [[1 if (r + c) % 3 else 0 for c in range(48)] for r in range(48)]
    path, bounds = extent_fixture(tmp_path, rows)
    result = gsw.measure_extent(path, box(*bounds))

    assert gsw.EXTENT_GRID_M == PUBLIC_GRID_M
    assert len(result["cells"]) > 1
    assert sum(cell["water_px"] for cell in result["cells"]) == result["ever_water_pixels"]
    for cell in result["cells"]:
        corner_x, corner_y = cell["x"] - PUBLIC_GRID_M / 2, cell["y"] - PUBLIC_GRID_M / 2
        assert cell["cell_id"] == cell_id(corner_x, corner_y)


def test_extent_counts_the_same_aoi_pixels_as_the_yearly_measure(tmp_path):
    from shapely.geometry import Polygon

    rows = [[1, 0, 1, 0, 1, 0], [0, 1, 0, 1, 0, 1], [1, 1, 0, 0, 1, 1], [0, 0, 1, 1, 0, 0]]
    extent, bounds = extent_fixture(tmp_path, rows)
    yearly, _ = extent_fixture(tmp_path, [[2 if v else 1 for v in row] for row in rows], name="yearly.tif")
    west, south, east, north = bounds
    triangle = Polygon([(west, south), (east, south), (west, north)])

    measured = gsw.measure_extent(extent, triangle)
    year = gsw.measure_year(2020, "yearly.tif", yearly, bounds, aoi_geometry=triangle, extent_path=extent)

    assert measured["aoi_pixels"] == year.aoi_pixels



# ---------------------------------------------------------------------------
# Cross-harness (Codex) regressions, and a CRS check that needs no EPSG lookup.
# ---------------------------------------------------------------------------


def test_an_oversized_window_is_refused_before_it_is_rasterised(tmp_path, monkeypatch):
    import rasterio.mask
    from shapely.geometry import box

    path, bounds = extent_fixture(tmp_path, [[1, 0, 1], [0, 1, 0]])

    def never(*args, **kwargs):
        raise AssertionError("the mask was built before the cap was checked")

    monkeypatch.setattr(gsw, "EXTENT_MAX_WINDOW_PIXELS", 4)
    monkeypatch.setattr(rasterio.mask, "raster_geometry_mask", never)
    with pytest.raises(ValueError, match="cap"):
        gsw.measure_extent(path, box(*bounds))


def test_a_rotated_extent_is_refused(tmp_path):
    from affine import Affine
    from shapely.geometry import box

    sheared = Affine(0.00025, 0.00001, WEST, 0.0, -0.00025, NORTH)
    path, bounds = extent_fixture(tmp_path, [[1, 0], [0, 1]], transform=sheared)
    with pytest.raises(ValueError, match="grid"):
        gsw.measure_extent(path, box(*bounds))


def test_the_crs_check_does_not_need_rasterios_epsg_lookup():
    from types import SimpleNamespace

    import pyproj
    from affine import Affine
    from shapely.geometry import box

    # On a machine whose PROJ_LIB points at an old proj.db, rasterio's EPSG
    # lookup returns None for a correct tile whose WKT is still intact.
    crs = SimpleNamespace(to_epsg=lambda *args, **kwargs: None,
                          to_wkt=lambda *args, **kwargs: pyproj.CRS.from_epsg(4326).to_wkt("WKT1_GDAL"))
    dataset = SimpleNamespace(
        nodata=None, crs=crs, res=(0.00025, 0.00025),
        transform=Affine(0.00025, 0.0, WEST, 0.0, -0.00025, NORTH),
        bounds=(WEST, NORTH - 0.0005, WEST + 0.0005, NORTH),
    )
    gsw._check_extent_grid(dataset, box(WEST, NORTH - 0.0005, WEST + 0.0005, NORTH))
