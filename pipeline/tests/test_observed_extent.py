"""Tests for the BKK-053a observed-extent check core (design note section 10, tests 1-3 and 9).

Synthetic fixtures only. The declared side is built with the real scenario
functions so the recovered lattice is the one flood.py actually evaluates.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import observed_extent as oec  # noqa: E402
from bkkflow.flood import FloodScenario, build_depth_surface, build_flood_slices  # noqa: E402

CRS = "EPSG:32647"
AOI = box(0, 0, 400, 300)  # larger than the water box, so some AOI points are never evaluated


def water(*lines):
    return gpd.GeoDataFrame(geometry=[LineString(line) for line in lines], crs=CRS)


# The second line lies outside the AOI; flood.py discards it, so the box must too.
WATER = water([(10, 20), (210, 220)], [(1000, 1000), (1100, 1100)])


def declared_slices(decay_m=20.0):
    scenario = FloodScenario("t", "moderate", 0, 600, 1200, decay_length_m=decay_m)
    surface = build_depth_surface(WATER, scenario=scenario, analysis_crs=CRS, aoi_geometry=AOI)
    return build_flood_slices(surface, scenario=scenario), len(surface)


def nodes_frame(rows):  # (i, j, state, distance[, aoi_frac]); squares lie wholly in the AOI by default
    rows = [row if len(row) == 5 else (*row, 1.0) for row in rows]
    frame = pd.DataFrame(rows, columns=["i", "j", "state", "distance_to_water_m", "aoi_frac"])
    return frame.assign(peak_depth_m=np.nan)  # only the M1 secondary row (BKK-053b) reads depth


def observed_for(nodes, role="mapped", **fractions):
    frame = nodes[["i", "j"]].assign(observed_wet_frac=0.0, channel_frac=0.0, source_role=role)
    for (i, j), (wet, channel) in fractions.get("cells", {}).items():
        hit = (frame.i == i) & (frame.j == j)
        frame.loc[hit, ["observed_wet_frac", "channel_frac"]] = (wet, channel)
    return frame


def by_block(blocks):
    return blocks.set_index(["bi", "bj"])


# Test 1: lattice recovery and declared states
def test_lattice_origin_and_spacing_are_recovered_from_stored_points():
    slices, _ = declared_slices()
    assert oec.recover_lattice(slices.x, slices.y) == pytest.approx((10.0, 20.0))
    wrapped_x, _ = oec.recover_lattice([99.9999999, 150.0], [20.0, 70.0])  # same offset as 0, unrounded
    assert abs(wrapped_x) < 1e-6
    for xs, match in (([10.0, 60.0, 75.0], "one lattice offset"), ([10.0, 110.0, 210.0], "50 m lattice spacing"),
                      ([10.0, np.nan, 60.0], "finite")):
        with pytest.raises(ValueError, match=match):  # a 100 m run would read its midpoints as evaluated
            oec.recover_lattice(xs, [20.0] * len(xs))


def test_declared_states_separate_unstored_from_never_evaluated():
    slices, stored_count = declared_slices()
    nodes, origin = oec.declared_nodes(slices, WATER, AOI)
    assert origin == pytest.approx((10.0, 20.0))
    states = nodes.set_index(["i", "j"]).state
    assert (nodes.state == "stored").sum() == stored_count == 19
    assert states[(3, 0)] == "evaluated_below_storage"  # (160, 20): inside the box, depth <= 0.01 m
    assert states[(6, 2)] == "not_evaluated"  # (310, 120): inside the AOI, outside the box
    assert nodes.loc[nodes.state != "stored", "distance_to_water_m"].isna().all()
    aoi_frac = nodes.set_index(["i", "j"]).aoi_frac  # (10, 20)'s square is [-15, 35] x [-5, 45]
    assert aoi_frac[(0, 0)] == pytest.approx(0.7 * 0.9) and aoi_frac[(3, 2)] == 1.0
    assert oec.declared_coverage(nodes) == {
        "aoi_points": 48, "not_evaluated": 23, "not_evaluated_share": pytest.approx(23 / 48)}


@pytest.mark.parametrize("aoi, lines, decay_m, origin", [
    (Polygon([(3.7, 6.2), (420.0, 15.3), (390.2, 260.9), (40.1, 300.4)]),  # water crosses the AOI edges
     [[(-80.3, 33.1), (260.6, 211.7)], [(120.4, -50.2), (180.9, 250.8)]], 30.0, (3.7, 6.2)),
    # The box starts on a vertical AOI edge at four decimals: its unstored edge points must survive.
    (box(3.7004, 6.2004, 403.7004, 306.2004), [[(-100.0, 100.0), (150.0, 350.0)]], 10.0, (3.7004, 0.0)),
])
def test_states_match_the_scenario_lattice_with_fractional_origin_and_clipped_box(aoi, lines, decay_m, origin):
    lines = water(*lines)
    scenario = FloodScenario("t", "moderate", 0, 600, 1200, decay_length_m=decay_m)
    surface = build_depth_surface(lines, scenario=scenario, analysis_crs=CRS, aoi_geometry=aoi)
    nodes, recovered = oec.declared_nodes(build_flood_slices(surface, scenario=scenario), lines, aoi)
    # Independently: the scenario's arange over (water bounds cut to AOI bounds), overhang included.
    x0, y0 = np.maximum(lines.total_bounds[:2], aoi.bounds[:2])
    x1, y1 = np.minimum(lines.total_bounds[2:], aoi.bounds[2:])
    gx, gy = np.meshgrid(np.arange(x0, x1 + 50, 50), np.arange(y0, y1 + 50, 50))
    expected = {(round(x, 3), round(y, 3)) for x, y in zip(gx.ravel(), gy.ravel()) if aoi.intersects(Point(x, y))}
    evaluated = nodes[nodes.state != "not_evaluated"]
    assert {(round(x, 3), round(y, 3)) for x, y in zip(evaluated.x, evaluated.y)} == expected
    assert recovered == pytest.approx(origin) and (nodes.state == "stored").sum() == len(surface)
    assert {"evaluated_below_storage", "not_evaluated"} <= set(nodes.state)


def test_water_layer_or_aoi_off_the_stored_lattice_is_refused():
    slices, _ = declared_slices()
    with pytest.raises(ValueError, match="A5"):
        oec.declared_nodes(slices, water([(15, 20), (215, 220)]), AOI)
    with pytest.raises(ValueError, match="stored points lie outside the area of interest"):
        oec.declared_nodes(slices, WATER, box(0, 0, 100, 100))


# Test 2: 2 x 2 blocking
def test_blocks_are_lattice_aligned_and_ranked_by_minimum_stored_distance():
    s, b, n = "stored", "evaluated_below_storage", "not_evaluated"
    nodes = nodes_frame([
        (0, 0, s, 30.0), (1, 0, s, 80.0), (0, 1, b, None), (1, 1, b, None),  # full block
        (2, 0, b, None), (3, 0, b, None), (2, 1, b, None), (3, 1, b, None),  # nothing stored
        (4, 0, b, None), (5, 0, b, None),  # half the block in the AOI
        (6, 0, s, 10.0),  # a quarter in the AOI
        (0, 2, s, 50.0), (1, 2, s, 60.0), (0, 3, n, None), (1, 3, n, None),
        (2, 2, s, 40.0), (2, 3, n, None), (3, 2, n, None), (3, 3, n, None),
        (-2, 0, b, None), (-1, 0, s, 70.0),  # west of the origin: floor division keeps pairs together
        (10, 0, s, 20.0, 0.1), (11, 0, s, 25.0, 0.1),  # two centres in a strip covering 5% of the block
    ])
    blocks = by_block(oec.block_table(nodes, observed_for(nodes), "mitrearth-flood-gistda"))
    assert blocks.loc[(0, 0), "min_stored_distance_m"] == 30.0
    assert blocks.loc[(-1, 0), ["points", "min_stored_distance_m"]].tolist() == [2, 70.0]
    assert blocks.loc[(1, 0), "bottom_tie"] and blocks.loc[(2, 0), "bottom_tie"]
    assert blocks.loc[(1, 0), "min_stored_distance_m"] == blocks.loc[(2, 0), "min_stored_distance_m"]
    assert blocks.loc[(2, 0), "state"] == "not_mapped_as_flooded"  # 2 of 4 evaluable: >= 50%
    assert blocks.loc[(5, 0), ["state", "unknown_reason"]].tolist() == ["unknown", "outside_aoi"]  # by area
    assert blocks.loc[(3, 0), ["state", "unknown_reason"]].tolist() == ["unknown", "outside_aoi"]
    assert blocks.loc[(0, 1), ["state", "min_stored_distance_m"]].tolist() == ["not_mapped_as_flooded", 50.0]
    assert blocks.loc[(1, 1), ["state", "unknown_reason"]].tolist() == ["unknown", "not_evaluated"]


def test_primary_rank_uses_only_evaluable_points_and_the_sensitivity_rank_keeps_all():
    s, b = "stored", "evaluated_below_storage"
    nodes = nodes_frame([
        (0, 0, s, 2.0), (1, 0, s, 60.0), (0, 1, s, 70.0), (1, 1, s, 80.0),  # a canal point beside land
        (2, 0, s, 5.0), (3, 0, b, None), (2, 1, b, None), (3, 1, b, None),  # only the canal is stored
        (4, 0, s, 3.0), (5, 0, s, 40.0), (4, 1, s, 25.0), (5, 1, b, None),  # partial channel shares
    ])
    observed = observed_for(nodes, cells={
        (0, 0): (0.0, 1.0), (2, 0): (0.0, 1.0), (4, 0): (0.0, 0.6), (4, 1): (0.0, 0.4)})
    blocks = by_block(oec.block_table(nodes, observed, "mitrearth-flood-gistda"))
    ranks = ["state", "min_stored_distance_m", "min_stored_distance_all_m"]
    # Masked water must not re-enter through the declared side: the land sets the primary rank.
    assert blocks.loc[(0, 0), ranks].tolist() == ["not_mapped_as_flooded", 60.0, 2.0]
    # In the domain with no evaluable stored point: the primary rank ties at the bottom.
    assert blocks.loc[(1, 0), ranks].tolist() == ["not_mapped_as_flooded", np.inf, 5.0]
    assert blocks.loc[(1, 0), "bottom_tie"] and not blocks.loc[(0, 0), "bottom_tie"]
    # A point counts when at least half its square is evaluable: 40% channel counts, 60% does not.
    assert blocks.loc[(2, 0), ranks].tolist() == ["not_mapped_as_flooded", 25.0, 3.0]


@pytest.mark.parametrize("aoi_frac, channel, counts", [
    (1.0, 0.5, True), (0.7, 0.2, True),  # exactly half evaluable (0.7 - 0.2 is 0.4999... in floats)
    (0.3, 0.0, False),  # a square mostly outside the AOI does not set the rank
])
def test_rank_threshold_is_half_the_square(aoi_frac, channel, counts):
    nodes = nodes_frame([(0, 0, "stored", 4.0, aoi_frac), (1, 0, "stored", 90.0), (0, 1, "stored", 95.0),
                         (2, 0, "evaluated_below_storage", None)])  # block (1, 0): nothing stored
    observed = observed_for(nodes, cells={(0, 0): (0.0, channel)})
    blocks = by_block(oec.block_table(nodes, observed, "mitrearth-flood-gistda"))
    assert blocks.loc[(0, 0), "min_stored_distance_m"] == (4.0 if counts else 90.0)
    assert blocks.loc[(1, 0), ["min_stored_distance_m", "min_stored_distance_all_m"]].tolist() == [np.inf] * 2


# Test 3: per-layer domains; no observation is not dry
def test_gsw_code_zero_is_never_channel_or_not_mapped():
    assert oec.gsw_channel(np.array([0, 1, 2, 3])).tolist() == [False, False, False, True]
    with pytest.raises(ValueError):
        oec.gsw_channel(np.array([4]))
    nodes = nodes_frame([(0, 0, "stored", 5.0)])
    for mask_layer in ("gsw-permanent-water", "mitrearth-water-body"):
        with pytest.raises(ValueError, match="not a comparison layer"):
            oec.block_table(nodes, observed_for(nodes, role="observed"), mask_layer)
    masks = {key for key, spec in oec.LAYERS.items() if spec["use"] == "channel_mask"}
    assert masks == {"gsw-permanent-water", "mitrearth-water-body"}
    # MitrEarth absence is its own rule (A1): GSW code 0 over the same squares adds no channel and no unknown.
    nodes = nodes_frame([(i, j, "stored", 5.0) for i in range(2) for j in range(2)])
    observed = observed_for(nodes).assign(channel_frac=oec.gsw_channel(np.zeros(4, int)).astype(float))
    assert oec.block_table(nodes, observed, "mitrearth-flood-gistda").state.tolist() == ["not_mapped_as_flooded"]


def test_channel_and_unknown_area_leave_numerator_and_denominator():
    cells = [(i, j) for i in range(4) for j in range(2)]
    nodes = nodes_frame([(i, j, "stored", 10.0 * i) for i, j in cells])
    observed = observed_for(nodes, cells={
        # Wet over half the block, the other half channel: wet 1.0 of 2.0 open squares, so >= 50%.
        (0, 0): (0.0, 1.0), (1, 0): (0.0, 1.0), (0, 1): (0.5, 0.0), (1, 1): (0.5, 0.0),
        (2, 0): (0.0, 1.0), (3, 0): (0.0, 1.0), (2, 1): (0.0, 1.0),  # 0.25 open: masked
    })
    blocks = oec.block_table(nodes, observed, "mitrearth-flood-gistda")
    assert by_block(blocks).loc[[(0, 0), (1, 0)], "state"].tolist() == ["observed_wet", "unknown"]
    summary = oec.domain_summary(blocks)
    assert summary["evaluable"] == summary["observed_wet"] + summary["not_mapped_as_flooded"] == 1
    assert summary["unknown_by_reason"] == {"channel": 1} and summary["masked_channel"] == 1


def test_missing_or_duplicated_observed_values_are_refused():
    nodes = nodes_frame([(0, 0, "stored", 5.0), (1, 0, "stored", 9.0)])
    with pytest.raises(ValueError, match="unknown is never dry"):
        oec.block_table(nodes, observed_for(nodes).iloc[:1], "mitrearth-flood-gistda")
    with pytest.raises(ValueError):  # a repeated square would count its area twice
        oec.block_table(nodes, pd.concat([observed_for(nodes)] * 2), "mitrearth-flood-gistda")


# Test 9: role guards and labels
def test_roles_are_guarded_on_both_sides():
    slices, _ = declared_slices()
    with pytest.raises(ValueError, match="source_role"):
        oec.declared_nodes(slices.assign(source_role="observed"), WATER, AOI)
    nodes = nodes_frame([(0, 0, "stored", 5.0)])
    for role in ("scenario", "observed"):  # MitrEarth keeps its own role: mapped
        with pytest.raises(ValueError, match="source_role"):
            oec.block_table(nodes, observed_for(nodes, role=role), "mitrearth-flood-gistda")


@pytest.mark.parametrize("module", ["observed_extent.py", "observed_extent_stats.py"])
def test_module_never_imports_the_depth_builders(module):
    tree = ast.parse((Path(oec.__file__).parent / module).read_text(encoding="utf-8"))
    forbidden = {"build_depth_surface", "build_flood_slices", "flood"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module not in {"flood", "bkkflow.flood"}
            assert not forbidden & {alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            assert not any(alias.name.endswith("flood") for alias in node.names)
        elif isinstance(node, (ast.Name, ast.Attribute)):
            assert getattr(node, "id", getattr(node, "attr", None)) not in forbidden - {"flood"}


def test_record_carries_labels_assumptions_and_no_metrics():
    slices, _ = declared_slices()
    nodes, origin = oec.declared_nodes(slices, WATER, AOI)
    blocks = oec.block_table(nodes, observed_for(nodes), "mitrearth-flood-gistda")
    scenario = {"model_name": "bkk-scenario-depth-decay", "model_version": "0.1.0", "parameters": {
        "severity": "moderate", "source_role": "scenario", "peak_depth_m": 0.55, "decay_length_m": 150.0}}
    kwargs = dict(run_id="r", aoi_id="sai-mai-district", flood_scenario=scenario, declared_sha256="d",
                  layer="mitrearth-flood-gistda", year=2006, observed_sha256="o",
                  nodes=nodes, origin=origin, blocks=blocks)
    record = oec.build_record(**kwargs)
    assert record["labels"] == oec.LABELS and record["labels"]["measures"] == "extent_only"
    assert not any(record["labels"][key] for key in (
        "depth_compared", "timing_compared", "is_validation", "is_calibration", "is_evacuation_simulation"))
    assert record["assumptions"] == [f"A{n}" for n in range(1, 8)]
    assert set(record["assumption_text"]) == set(record["assumptions"])
    assert record["metrics"] is None and record["protocol_version"] == "oec-v1"
    assert record["declared"]["storage_corridor_m"] == 601
    assert record["declared"]["block_rank"] == "min_stored_distance_over_evaluable_points"
    assert record["declared"]["sensitivity_block_rank"] == "min_stored_distance_over_all_stored_points"
    assert record["declared"]["source_role"] == "scenario" and record["observed"]["source_role"] == "mapped"
    assert record["unit"] == {"crs": CRS, "block_m": 100, "lattice_origin_mod50": [10.0, 20.0],
                              "observed_wet_rule": ">=0.5 evaluable area",
                              "min_evaluable_rule": ">=0.5 block area"}
    assert json.loads(json.dumps(record, allow_nan=False)) == record
    scenario["parameters"]["source_role"] = "observed"
    with pytest.raises(ValueError, match="source_role"):
        oec.build_record(**kwargs)
