"""Tests for the drainage-discharge screening index.

The index is a screening aid, so what matters is not whether its numbers are
pretty but whether they obey their own contract: bounded, monotone in the
claimed directions, null where a value is unknown rather than zero, and
unmistakably labelled as a screening index rather than a measurement of water.
Those are the properties checked here, on small synthetic fixtures in the
Bangkok projection so the tests stay hermetic and fast.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import LineString, Point, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import drainage as dr  # noqa: E402

# Two cells 1 km apart near Khlong San, in EPSG:32647.
X0, X1, Y0 = 662000.0, 663000.0, 1520000.0


def _write_layer(curated: Path, name: str, geoms: list, **columns) -> None:
    frame = pd.DataFrame({"geometry_wkt": [shapely.to_wkt(g) for g in geoms]})
    for key, values in columns.items():
        frame[key] = values
    frame.to_parquet(curated / f"{name}.parquet", index=False)


def _write_grid(path: Path, centres: list[tuple[float, float]]) -> None:
    frame = pd.DataFrame(
        {
            "gx": [i for i, _ in enumerate(centres)],
            "gy": [0] * len(centres),
            "x": [x for x, _ in centres],
            "y": [y for _, y in centres],
        }
    )
    points = gpd.GeoSeries(gpd.points_from_xy(frame["x"], frame["y"]), crs="EPSG:32647")
    frame["geometry_wkt"] = points.to_crs("OGC:CRS84").to_wkt()
    frame.to_parquet(path, index=False)


def _build(tmp_path: Path, centres, *, drainage=None, overflow=None, basins=None, villages=None):
    """Build an index over a synthetic 1 km grid, layer by layer."""
    curated = tmp_path / "mitrearth"
    curated.mkdir(parents=True, exist_ok=True)
    grid_path = tmp_path / "population_grid_1km.parquet"
    _write_grid(grid_path, centres)
    if drainage is not None:
        _write_layer(curated, "drainage_system", drainage)
    if overflow is not None:
        _write_layer(curated, "overflow_flood", overflow)
    if basins is not None:
        _write_layer(curated, "drainage_basin", basins, STREAM_ID=[7] * len(basins))
    if villages is not None:
        _write_layer(curated, "flood_susceptible_village", villages)
    return dr.build_drainage_index(grid_path=grid_path, curated_dir=curated)


# --------------------------------------------------------------------------


def test_risk_index_is_bounded_and_non_negative(tmp_path: Path) -> None:
    result = _build(
        tmp_path,
        [(X0, Y0), (X1, Y0)],
        drainage=[
            LineString([(X0 - 500, Y0), (X0 + 500, Y0)]),
            LineString([(X0 - 500, Y0 + 600), (X1 + 500, Y0 + 600)]),
        ],
        overflow=[LineString([(X0 - 500, Y0 - 200), (X0 + 500, Y0 - 200)])],
        villages=[Point(X1, Y0)],
    )
    risk = result.frame["risk_index"]
    assert risk.notna().all()
    assert (risk >= 0.0).all()
    assert (risk <= 1.0).all()


def test_more_drainage_never_increases_risk(tmp_path: Path) -> None:
    """The two cells differ only in whether a channel crosses them."""
    result = _build(
        tmp_path,
        [(X0, Y0), (X1, Y0)],
        drainage=[
            # 400 m south of both centres, so it crosses cell 0 without
            # changing either cell's distance to its nearest channel.
            LineString([(X0 - 400, Y0 - 400), (X0 + 400, Y0 - 400)]),
            LineString([(X0 - 500, Y0 + 400), (X1 + 500, Y0 + 400)]),
        ],
    )
    frame = result.frame
    assert frame["drainage_m"].iloc[0] > frame["drainage_m"].iloc[1]
    # Everything else is held equal, so any difference is the density term.
    assert frame["distance_to_drainage_m"].iloc[0] == pytest.approx(
        frame["distance_to_drainage_m"].iloc[1]
    )
    assert frame["risk_index"].iloc[0] < frame["risk_index"].iloc[1]


def test_risk_ranks_against_drainage_density_over_the_whole_table(tmp_path: Path) -> None:
    centres = [(X0 + 1000.0 * i, Y0) for i in range(6)]
    result = _build(
        tmp_path,
        centres,
        drainage=[LineString([(x - 400, Y0 + 500), (x + 400, Y0 + 500)]) for x, _ in centres[:3]],
    )
    frame = result.frame
    correlation = frame["drainage_km_per_km2"].corr(frame["risk_index"], method="spearman")
    assert correlation <= 0.0


def test_a_cell_on_an_overflow_path_scores_at_least_as_high(tmp_path: Path) -> None:
    result = _build(
        tmp_path,
        [(X0, Y0), (X1, Y0)],
        drainage=[LineString([(X0 - 500, Y0 + 600), (X1 + 500, Y0 + 600)])],
        overflow=[LineString([(X0 - 400, Y0), (X0 + 400, Y0)])],  # crosses cell 0 only
    )
    frame = result.frame
    assert bool(frame["in_overflow_path"].iloc[0]) is True
    assert bool(frame["in_overflow_path"].iloc[1]) is False
    # Identical cells, identical distance: only the path differs.
    assert frame["distance_to_drainage_m"].iloc[0] == pytest.approx(
        frame["distance_to_drainage_m"].iloc[1]
    )
    assert frame["risk_index"].iloc[0] >= frame["risk_index"].iloc[1]


def test_susceptible_village_raises_risk(tmp_path: Path) -> None:
    result = _build(
        tmp_path,
        [(X0, Y0), (X1, Y0)],
        drainage=[LineString([(X0 - 500, Y0 + 600), (X1 + 500, Y0 + 600)])],
        villages=[Point(X1, Y0)],
    )
    frame = result.frame
    assert bool(frame["susceptible_village"].iloc[1]) is True
    assert bool(frame["susceptible_village"].iloc[0]) is False
    assert frame["risk_index"].iloc[1] > frame["risk_index"].iloc[0]


def test_distance_beyond_the_cutoff_is_null_never_zero(tmp_path: Path) -> None:
    """A cell 5 km from any channel is unknown, not '0 m away'."""
    result = _build(
        tmp_path,
        [(X0, Y0), (X1, Y0)],
        drainage=[LineString([(X0 - 500, Y0 + 5000), (X1 + 500, Y0 + 5000)])],
    )
    frame = result.frame
    assert frame["distance_to_drainage_m"].isna().all()
    assert (frame["distance_to_drainage_m"] != 0).all()
    assert frame["distance_to_drainage_m"].notna().sum() == 0
    # The cutoff is not written into the field either.
    assert not (frame["distance_to_drainage_m"].fillna(-1) == dr.DISTANCE_CUTOFF_M).any()
    # Scored at the radius, and the imputation is declared in the table.
    assert frame["index_components"].iloc[0]["distance_absence"] == 1.0
    assert not bool(frame["index_inputs_complete"].iloc[0])
    # The channel is mapped but out of reach, so the cell is not risk-free.
    assert frame["risk_index"].iloc[0] > 0.0


def test_basin_id_is_null_outside_every_basin(tmp_path: Path) -> None:
    result = _build(
        tmp_path,
        [(X0, Y0), (X1, Y0)],
        drainage=[LineString([(X0 - 500, Y0), (X0 + 500, Y0)])],
        basins=[box(X0 - 600, Y0 - 600, X0 + 600, Y0 + 600)],
    )
    frame = result.frame
    assert pd.notna(frame["basin_id"].iloc[0])
    assert pd.notna(frame["basin_drainage_density"].iloc[0])
    assert pd.isna(frame["basin_id"].iloc[1])
    assert frame["basin_drainage_density"].iloc[1] is None or np.isnan(
        frame["basin_drainage_density"].iloc[1]
    )


# --------------------------------------------------------------------------
# degradation
# --------------------------------------------------------------------------


def test_a_missing_input_degrades_to_a_recorded_unavailability(tmp_path: Path) -> None:
    """No drainage layer: still a table, with nulls and a stated reason."""
    result = _build(tmp_path, [(X0, Y0), (X1, Y0)], overflow=[])
    frame = result.frame

    assert result.status == "ok"
    assert result.inputs["drainage_system"]["status"] == "missing"
    assert frame["drainage_m"].isna().all(), "absent layer must not report 0 m of drainage"
    assert frame["drainage_km_per_km2"].isna().all()
    assert frame["distance_to_drainage_m"].isna().all()
    assert any("drainage layer is unavailable" in w for w in result.warnings)
    # The components that do exist still score, so the index is not fabricated
    # and not blank.
    assert frame["risk_index"].notna().all()
    assert frame["risk_index"].between(0.0, 1.0).all()
    assert not frame["index_inputs_complete"].any()


def test_an_unavailable_flag_layer_is_na_not_false(tmp_path: Path) -> None:
    """A missing map layer cannot assert that no overflow is mapped."""
    result = _build(tmp_path, [(X0, Y0)], drainage=[])
    frame = result.frame
    assert frame["in_overflow_path"].isna().all()
    assert frame["susceptible_village"].isna().all()
    assert result.inputs["overflow_flood"]["status"] == "missing"
    assert result.inputs["flood_susceptible_village"]["status"] == "missing"
    components = frame["index_components"].iloc[0]
    assert components["discharge_flag"] is None


def test_no_grid_at_all_is_unavailable_rather_than_an_exception(tmp_path: Path) -> None:
    result = dr.build_drainage_index(
        grid_path=tmp_path / "absent_grid.parquet",
        aoi_path=tmp_path / "absent_aoi.parquet",
        curated_dir=tmp_path / "mitrearth",
    )
    assert result.status == "unavailable"
    assert result.frame.empty
    assert list(result.frame.columns) == list(dr.OUTPUT_COLUMNS)
    assert any("UNAVAILABLE" in w for w in result.warnings)
    assert result.as_dict()["rows"] == 0


def test_the_grid_can_be_derived_from_the_aoi_when_no_grid_is_published(
    tmp_path: Path,
) -> None:
    """The fallback must still produce cells, and must say it renumbered them."""
    aoi = gpd.GeoDataFrame(
        {"aoi_id": ["test"]}, geometry=[box(661500, 1519500, 665500, 1521500)],
        crs="EPSG:32647",
    )
    aoi.to_parquet(tmp_path / "aoi.parquet", index=False)
    curated = tmp_path / "mitrearth"
    curated.mkdir(parents=True, exist_ok=True)
    _write_layer(
        curated, "drainage_system",
        [LineString([(662000, 1519600), (664000, 1519600)])],
    )
    result = dr.build_drainage_index(
        grid_path=tmp_path / "absent_grid.parquet",
        aoi_path=tmp_path / "aoi.parquet",
        curated_dir=curated,
    )
    assert result.status == "ok"
    assert result.grid_source == "derived_from_aoi_bounds"
    assert len(result.frame) == 8  # 4 x 2 km of AOI
    assert result.frame["risk_index"].between(0.0, 1.0).all()
    assert any("will not match the published population grid" in w for w in result.warnings)


# --------------------------------------------------------------------------
# honesty
# --------------------------------------------------------------------------


def test_no_field_or_label_implies_depth(tmp_path: Path) -> None:
    result = _build(
        tmp_path,
        [(X0, Y0)],
        drainage=[LineString([(X0 - 500, Y0), (X0 + 500, Y0)])],
        overflow=[LineString([(X0 - 500, Y0), (X0 + 500, Y0)])],
    )
    frame = result.frame
    column_names = list(frame.columns)
    assert "depth" not in column_names
    assert not any("depth" in name.lower() for name in column_names)
    assert not any("depth" in str(label).lower() for label in frame["risk_band"])
    assert set(frame["source_role"].unique()) == {"screening_index"}
    assert frame["source_role"].str.len().all()
    provenance = result.as_dict()
    assert provenance["source_role"] == "screening_index"
    assert provenance["is_flood_depth"] is False
    assert provenance["is_observation"] is False
    assert provenance["is_simulation"] is False


def test_the_docstring_states_the_limits_of_the_index() -> None:
    raw = Path(dr.__file__).read_text(encoding="utf-8").split('"""')[1]
    doc = " ".join(raw.split()).lower()  # the source wraps, so flatten it first
    for phrase in (
        "not** a hydraulic model",
        "not** a flood depth",
        "mapped layer, not an observation of water",
        "ignores rainfall",
        "screening_index",
        "nulls, never zeros",
    ):
        assert phrase in doc, f"docstring must state: {phrase}"


def test_weights_and_bands_are_the_documented_ones() -> None:
    assert sum(dr.COMPONENT_WEIGHTS.values()) == pytest.approx(1.0)
    assert set(dr.COMPONENT_WEIGHTS) == {
        "density_absence", "distance_absence", "discharge_flag"
    }
    assert [label for label, _, _ in dr.BANDS] == ["low", "moderate", "high", "very_high"]
    assert dr.band_for(0.0) == "low"
    assert dr.band_for(0.2499) == "low"
    assert dr.band_for(0.25) == "moderate"
    assert dr.band_for(0.5) == "high"
    assert dr.band_for(0.75) == "very_high"
    assert dr.band_for(1.0) == "very_high"


def test_grid_identity_matches_the_published_grid(tmp_path: Path) -> None:
    result = _build(tmp_path, [(X0, Y0), (X1, Y0)], drainage=[])
    frame = result.frame
    assert list(frame["cell_id"]) == ["dr_0_0", "dr_1_0"]
    assert frame["lon"].between(100.0, 101.0).all()
    assert frame["lat"].between(13.0, 14.0).all()
    assert frame["cell_area_km2"].eq(1.0).all()
    assert result.grid_source.startswith("published_grid:")


def test_cell_identity_is_stable_across_runs(tmp_path: Path) -> None:
    """Reversing the input layer order must not renumber any cell."""
    lines = [
        LineString([(X0 - 500, Y0), (X0 + 500, Y0)]),
        LineString([(X1 - 500, Y0), (X1 + 500, Y0)]),
    ]
    first = _build(tmp_path, [(X0, Y0), (X1, Y0)], drainage=lines)
    second = _build(tmp_path, [(X0, Y0), (X1, Y0)], drainage=list(reversed(lines)))
    pd.testing.assert_frame_equal(first.frame, second.frame)
