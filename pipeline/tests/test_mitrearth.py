"""Tests for the MitrEarth ingest's geometry repair and its provenance counts.

The flood layer ships with self-intersecting rings. The ingest promises to
repair what ``make_valid`` can turn back into a line or polygon, drop what it
cannot, and count both. These tests write a tiny shapefile with one feature of
each kind and check that the promise holds end to end: a repaired feature is
kept, an unrepairable one is dropped, and the counts say which happened.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import Polygon, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow.sources import mitrearth  # noqa: E402

ANALYSIS_CRS = "EPSG:32647"
AOI = box(100.40, 13.60, 100.70, 13.90)

#: Valid squares, so every fixture has features that need no repair.
SQUARE = box(100.55, 13.75, 100.56, 13.76)
OTHER_SQUARE = box(100.60, 13.75, 100.61, 13.76)
#: Self-intersecting "bow-tie"; make_valid splits it into two triangles.
BOW_TIE = Polygon([(100.50, 13.70), (100.52, 13.72), (100.52, 13.70), (100.50, 13.72)])
#: Lopsided bow-tie: its lobes partly cancel in the raw ring area (150 units)
#: but add up once repaired (250 units), so the repair changes the extent.
LOPSIDED_BOW_TIE = Polygon([(100.50, 13.70), (100.53, 13.72), (100.53, 13.70), (100.50, 13.71)])
#: One ring that pinches through the same vertex twice, like the "Ring
#: Self-intersection" defects in the real flood layer. Both lobes wind the
#: same way, so repair splits them and keeps the area exactly.
PINCHED = Polygon(
    [
        (100.50, 13.70), (100.52, 13.70), (100.52, 13.72), (100.54, 13.72),
        (100.54, 13.74), (100.52, 13.74), (100.52, 13.72), (100.50, 13.72),
    ]
)
#: Every vertex is the same point; make_valid can only return a Point.
COLLAPSED = Polygon([(100.50, 13.70)] * 4)


def _ingest_flood_layer(tmp_path: Path, geometries: list, years: list[int]):
    relative = mitrearth.LAYER_FILES["flood_extent_gistda"]
    path = tmp_path / "raw" / relative
    path.parent.mkdir(parents=True)
    gpd.GeoDataFrame({"year": years}, geometry=geometries, crs="EPSG:4326").to_file(path)
    assert not gpd.read_file(path).geometry.is_valid.all(), "fixture must contain invalid rings"

    aoi = gpd.GeoDataFrame(geometry=[AOI], crs="EPSG:4326")
    out_dir = tmp_path / "curated"
    result = mitrearth.ingest(
        aoi_frame=aoi, analysis_crs=ANALYSIS_CRS, raw_root=tmp_path / "raw", out_dir=out_dir
    )
    written = pd.read_parquet(out_dir / "flood_extent_gistda.parquet")
    return result, written


def test_repairable_ring_survives_ingest_and_is_counted_as_repaired(tmp_path: Path) -> None:
    result, written = _ingest_flood_layer(tmp_path, [SQUARE, BOW_TIE], [2006, 2010])
    layer = result.layers["flood_extent_gistda"]

    assert layer["repaired_geometries"] == 1
    assert layer["dropped_unrepairable"] == 0
    assert layer["rows_total"] == 2
    assert layer["rows_in_aoi"] == 2
    assert sorted(written["year"]) == [2006, 2010]
    assert shapely.is_valid(shapely.from_wkt(written["geometry_wkt"].to_numpy())).all()
    by_year = {entry["year"]: entry for entry in result.flood_extent_by_year["years"]}
    assert by_year[2010]["polygons"] == 1
    assert by_year[2010]["union_km2"] > 0
    # The symmetric bow-tie's lobes cancel to a raw ring area of 0, so the
    # repair cannot be shown to keep its area and the year stays unreliable.
    assert by_year[2010]["invalid_geometry"]["repaired_area_changed"] == 1
    assert by_year[2010]["reliable"] is False


def test_unrepairable_ring_is_dropped_and_counted(tmp_path: Path) -> None:
    result, written = _ingest_flood_layer(tmp_path, [SQUARE, COLLAPSED], [2006, 2010])
    layer = result.layers["flood_extent_gistda"]

    assert layer["repaired_geometries"] == 0
    assert layer["dropped_unrepairable"] == 1
    assert layer["rows_total"] == 2
    assert layer["rows_in_aoi"] == 1
    assert written["year"].tolist() == [2006]


def _years(result) -> dict[int, dict]:
    return {entry["year"]: entry for entry in result.flood_extent_by_year["years"]}


def test_year_whose_repairs_keep_their_area_is_reliable(tmp_path: Path) -> None:
    result, _ = _ingest_flood_layer(tmp_path, [SQUARE, PINCHED], [2006, 2010])
    year = _years(result)[2010]

    assert year["invalid_geometry"] == {
        "invalid_features": 1,
        "repaired": 1,
        "repaired_area_changed": 0,
        "dropped": 0,
    }
    assert year["reliable"] is True
    assert result.flood_extent_by_year["unreliable_years"] == []


def test_year_whose_repair_changes_area_is_unreliable(tmp_path: Path) -> None:
    result, _ = _ingest_flood_layer(tmp_path, [SQUARE, LOPSIDED_BOW_TIE], [2006, 2010])
    year = _years(result)[2010]

    assert result.layers["flood_extent_gistda"]["repaired_area_changed"] == 1
    assert year["invalid_geometry"]["repaired_area_changed"] == 1
    assert year["reliable"] is False
    assert result.flood_extent_by_year["unreliable_years"] == [2010]


def test_year_that_lost_a_feature_is_unreliable(tmp_path: Path) -> None:
    result, _ = _ingest_flood_layer(
        tmp_path, [SQUARE, OTHER_SQUARE, COLLAPSED], [2006, 2010, 2010]
    )
    year = _years(result)[2010]

    assert year["invalid_geometry"]["dropped"] == 1
    assert year["polygons"] == 1
    assert year["reliable"] is False
    assert result.flood_extent_by_year["unreliable_years"] == [2010]


def test_year_that_lost_every_feature_is_still_listed_unreliable(tmp_path: Path) -> None:
    result, _ = _ingest_flood_layer(tmp_path, [SQUARE, COLLAPSED], [2006, 2010])
    year = _years(result)[2010]

    assert year["polygons"] == 0
    # The lost extent is unknown, not zero: a 0.0 would read as "no flood".
    assert year["union_km2"] is None
    assert year["is_largest_mapped_event"] is False
    assert year["invalid_geometry"]["dropped"] == 1
    assert year["reliable"] is False
    assert result.flood_extent_by_year["unreliable_years"] == [2010]
