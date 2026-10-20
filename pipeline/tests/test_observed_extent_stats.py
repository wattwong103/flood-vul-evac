"""Tests for the BKK-053b observed-extent statistics (design note section 10, tests 5-8).

Synthetic fixtures only: no release, source or observed layer is read, and no real
declared-versus-observed number is computed before the oec-v1 lock (section 7).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import observed_extent as oec  # noqa: E402
from bkkflow import observed_extent_stats as oes  # noqa: E402
from bkkflow.flood import FloodScenario, build_depth_surface, build_flood_slices  # noqa: E402

CRS = "EPSG:32647"
DIAGONAL = gpd.GeoDataFrame(geometry=[LineString([(10, 20), (810, 820)])], crs=CRS)
SQUARE = box(0, 0, 800, 800)  # 16 x 16 lattice points, all in the evaluated box: 8 x 8 blocks
POS, NEG = [10.0, 30.0, np.inf], [20.0, 30.0, np.inf, 40.0]  # observed-wet and not-mapped block ranks


CASE = ("sai-mai-district", "mitrearth-flood-gistda", 2006)


def fast_protocol(block_m=100, n=49, minimum=1):
    """The locked protocol with fewer draws; a minimum of 1 lets the statistics be checked on tiny grids."""
    protocol = oes.lock_protocol({CASE: block_m})
    protocol["null"]["n"] = protocol["interval"]["n"] = n
    protocol["definition"] = {"min_observed_wet_blocks": minimum, "min_not_mapped_blocks": minimum}
    return protocol


def grid_blocks(label, distance, wet_points=0, evaluable_points=4):
    """A block table from dense arrays: label 1 observed wet, 0 not mapped, -1 unknown."""
    label, distance = np.atleast_2d(label), np.atleast_2d(np.asarray(distance, dtype=float))
    bi, bj = np.indices(label.shape)
    state = np.select([label == 1, label == 0], ["observed_wet", "not_mapped_as_flooded"], "unknown")
    return pd.DataFrame({"bi": bi.ravel(), "bj": bj.ravel(), "state": state.ravel(),
                         "min_stored_distance_m": distance.ravel(), "min_stored_distance_all_m": distance.ravel(),
                         "wet_points_0_15m": wet_points, "evaluable_points": evaluable_points})


def scenario_blocks(peak, decay, wet_blocks):
    """The real scenario lattice on the diagonal fixture, with whole blocks mapped as flooded."""
    scenario = FloodScenario("t", "moderate", 0, 600, 1200, decay_length_m=decay, peak_depth_m=peak)
    surface = build_depth_surface(DIAGONAL, scenario=scenario, analysis_crs=CRS, aoi_geometry=SQUARE)
    nodes, origin = oec.declared_nodes(build_flood_slices(surface, scenario=scenario), DIAGONAL, SQUARE)
    wet = [(i // 2, j // 2) in wet_blocks for i, j in zip(nodes.i, nodes.j)]
    observed = nodes[["i", "j"]].assign(
        observed_wet_frac=np.where(wet, nodes.aoi_frac, 0.0), channel_frac=0.0, source_role="mapped")
    return nodes, origin, oec.block_table(nodes, observed, "mitrearth-flood-gistda")


# Test 5: statistics against hand values
def test_auc_is_mann_whitney_with_ties_counted_half():
    wet = np.array([True] * 3 + [False] * 4)
    assert oes.auc(POS + NEG, wet) == pytest.approx(7 / 12)  # 4 + (2 + 1/2) + 1/2 of 12 pairs
    rng = np.random.default_rng(5)
    distance, wet = rng.integers(0, 6, 60).astype(float), rng.random(60) < 0.4
    brute = np.mean([1.0 if p < q else 0.5 if p == q else 0.0 for p in distance[wet] for q in distance[~wet]])
    assert oes.auc(distance, wet) == pytest.approx(brute)
    assert oes.auc(distance, np.zeros(60, bool)) is None
    with pytest.raises(ValueError, match="NaN"):
        oes.auc([1.0, np.nan], [True, False])


def test_toc_and_median_distances_match_hand_values():
    wet = np.array([True] * 3 + [False] * 4)
    assert oes.toc(POS + NEG, wet) == [
        {"threshold_m": 10.0, "flagged": 1, "hits": 1}, {"threshold_m": 20.0, "flagged": 2, "hits": 1},
        {"threshold_m": 30.0, "flagged": 4, "hits": 2}, {"threshold_m": 40.0, "flagged": 5, "hits": 2},
        {"threshold_m": "beyond_storage_corridor", "flagged": 7, "hits": 3}]
    blocks = grid_blocks(wet.astype(int), POS + NEG)
    result = oes.evaluate(blocks, fast_protocol(), CASE)
    assert result["median_distance_m"] == {"observed_wet": 30.0, "not_mapped": 35.0}
    assert result["auc"] == pytest.approx(7 / 12) and result["status"] == "ok" and result["row"] == "primary"
    sensitivity = blocks.assign(min_stored_distance_all_m=[40.0, 40, 40, 10, 10, 10, 10])
    assert oes.evaluate(sensitivity, fast_protocol(), CASE, row="sensitivity:all_stored_points")["auc"] == 0.0
    beyond = oes.evaluate(grid_blocks([1, 1, 1, 0], [np.inf, np.inf, 10, 20]), fast_protocol(), CASE)
    assert beyond["median_distance_m"]["observed_wet"] == "beyond_storage_corridor"


def test_m1_matches_a_hand_table_and_csi_random_its_formula():
    scores = oes.contingency([1, 1, 0, 0, 1], [1, 0, 1, 0, 0])
    p_d, p_o = 0.6, 0.4
    assert scores.pop("table") == {"A": 1, "B": 2, "C": 1, "D": 1}
    assert scores == pytest.approx({"H": 0.5, "FAR": 2 / 3, "CSI": 0.25, "bias": 1.5, "p_d": p_d, "p_o": p_o,
                                    "CSI_random": p_d * p_o / (p_d + p_o - p_d * p_o)})
    assert oes.contingency([0, 0, 0], [1, 0, 0])["FAR"] is None  # nothing declared wet: undefined, not 0


def test_m1_counts_only_evaluable_points_and_needs_half_of_them():
    s = "stored"
    nodes = pd.DataFrame([  # block (0, 0) then block (1, 0)
        (0, 0, s, 10.0, 1.0, 0.3), (1, 0, s, 20.0, 1.0, 0.2), (0, 1, s, 90.0, 1.0, 0.05), (1, 1, s, 99.0, 1.0, 0.02),
        (2, 0, s, 5.0, 1.0, 0.4), (3, 0, s, 50.0, 1.0, 0.15), (2, 1, s, 80.0, 1.0, 0.1), (3, 1, s, 99.0, 1.0, 0.02),
    ], columns=["i", "j", "state", "distance_to_water_m", "aoi_frac", "peak_depth_m"])
    observed = nodes[["i", "j"]].assign(observed_wet_frac=0.0, channel_frac=0.0, source_role="mapped")
    observed.loc[4, "channel_frac"] = 1.0  # block (1, 0)'s deepest point is canal: it must not count
    blocks = oec.block_table(nodes, observed, "mitrearth-flood-gistda")
    assert blocks[["evaluable_points", "wet_points_0_15m"]].values.tolist() == [[4, 2], [3, 1]]
    assert oes.declared_wet(blocks).tolist() == [True, False]  # 2 of 4 is half; 1 of 3 is not
    counts = pd.DataFrame({"evaluable_points": [4, 3, 1, 0], "wet_points_0_15m": [2, 2, 1, 0]})
    assert oes.declared_wet(counts).tolist() == [True, True, True, False]


# Test 6: invariance, stated correctly
def test_auc_ignores_peak_and_decay_while_the_stored_set_is_fixed():
    rng = np.random.default_rng(11)
    for _ in range(4):
        wet_blocks = {(bi, bj) for bi in range(8) for bj in range(8) if rng.random() < 0.3}
        # Corridors of 80 m and 104 m both store 2 diagonal steps (71 m) and not 3 (106 m); the absurd
        # 60 m peak puts 0.15 m two steps out, so M1 changes while the stored set does not.
        runs = [scenario_blocks(peak, decay, wet_blocks) for peak, decay in ((0.55, 20.0), (60.0, 12.0))]
        stored = [set(zip(*nodes.loc[nodes.state == "stored", ["i", "j"]].values.T)) for nodes, _, _ in runs]
        assert stored[0] == stored[1]
        first, second = (oes.evaluate(blocks, fast_protocol(), CASE) for _, _, blocks in runs)
        for key in ("auc", "toc", "median_distance_m", "null", "interval"):
            assert first[key] == second[key]
        assert first["secondary_at_0_15m"] != second["secondary_at_0_15m"]  # M1 does depend on the preset


def test_a_wider_storage_corridor_can_change_the_auc():
    ring = {(bi, bj) for bi in range(8) for bj in range(8) if abs(bi - bj) == 2}
    narrow = oes.evaluate(scenario_blocks(0.55, 20.0, ring)[2], fast_protocol(), CASE)  # ring ties at the bottom
    wide = oes.evaluate(scenario_blocks(0.55, 40.0, ring)[2], fast_protocol(), CASE)  # ring is now stored
    assert narrow["auc"] < wide["auc"]


# Test 7: null and interval
def test_shift_null_is_deterministic_uniform_without_structure_and_small_with_it():
    rng = np.random.default_rng(3)
    distance = rng.random((10, 10)) * 500
    p_values = [oes.toroidal_null(grid_blocks((rng.random((10, 10)) < 0.3).astype(int), distance),
                                  "primary", n=99, seed=1)["p_ge_observed"] for _ in range(200)]
    assert 0.42 < np.mean(p_values) < 0.58 and 0.03 < np.mean(np.array(p_values) <= 0.1) < 0.18
    aligned = grid_blocks((distance < np.quantile(distance, 0.3)).astype(int), distance)
    assert oes.toroidal_null(aligned, "primary", n=99, seed=1)["p_ge_observed"] < 0.05
    clustered = grid_blocks(rng.random((20, 20)) < 0.3, rng.random((20, 20)))
    runs = [oes.evaluate(clustered, fast_protocol(n=99), CASE) for _ in range(2)]
    assert runs[0] == runs[1] and runs[0]["null"]["n"] == 99


def test_a_shift_that_brings_in_unknown_drops_those_blocks_and_one_tile_fixes_the_sample():
    # Torus of 4: the three shifts give AUC 1 and 0 on two blocks each, and one shift has no positive.
    null = oes.toroidal_null(grid_blocks([1, 0, 0, -1], [10.0, 20, 30, 40]), "primary", n=99, seed=1)
    assert null == {"method": "toroidal_shift", "seed": 1, "n": 3, "n_undefined": 1, "p_ge_observed": 2 / 3,
                    "share_ge_observed": 0.5, "prevalence_range": [0.5, 0.5], "evaluable_range": [2, 2]}
    # One 400 m tile covers the 4 x 4 grid, so every resample is the sample itself.
    blocks = grid_blocks(np.eye(4, dtype=int), np.add.outer(np.arange(4.0), np.arange(4.0)))
    observed = oes.evaluate(blocks, fast_protocol(block_m=400), CASE)
    assert observed["interval"]["ci95"] == pytest.approx([observed["auc"]] * 2)


def test_bootstrap_block_length_comes_from_the_correlogram_and_the_protocol(monkeypatch):
    assert len(oes.correlogram(grid_blocks(np.eye(12, 30, dtype=int), np.zeros((12, 30))))) == 6  # half of 12
    with monkeypatch.context() as patch:  # the rule: first lag at or below 0.05; undefined lags are skipped
        patch.setattr(oes, "correlogram", lambda blocks: [0.4, None, 0.05, -0.2])
        assert oes.correlation_range_m(None) == 300
    squares = np.add.outer(np.arange(12) // 3, np.arange(12) // 3) % 2  # 300 m squares, alternating
    assert oes.correlation_range_m(grid_blocks(squares, np.zeros((12, 12)))) == 200
    assert oes.correlation_range_m(grid_blocks(np.indices((12, 12)).sum(0) % 2, np.zeros((12, 12)))) == 100
    half_plane = np.repeat((np.arange(20) < 10)[:, None], 40, axis=1).astype(int)
    with pytest.raises(ValueError, match="correlation range"):
        oes.correlation_range_m(grid_blocks(half_plane, np.zeros((20, 40))))
    blocks = grid_blocks(squares, np.add.outer(np.arange(12.0), np.arange(12.0)))
    with pytest.raises(ValueError, match="not locked"):  # a defined case locked without a length
        oes.evaluate(blocks, fast_protocol(block_m=None), CASE)
    for bad in (150, 0, 200.0, True):
        with pytest.raises(ValueError, match="multiple of 100"):
            oes.lock_protocol({CASE: bad})
    assert oes.PROTOCOL["cases"] == []  # locking copies the template
    interval = oes.evaluate(blocks, fast_protocol(block_m=200), CASE)["interval"]
    assert interval["block_m"] == 200 and interval["n_tiles"] == 36 and interval["ci95"][0] <= interval["ci95"][1]


# Test 8: undefined states
@pytest.mark.parametrize("labels, status", [
    ([0, 0, 0, -1], "undefined_no_observed_positives"),  # Khlong San and Din Daeng today
    ([-1, -1, -1, -1], "undefined_no_evaluable_blocks"),
    ([1, 1, 1, -1], "undefined_no_not_mapped_blocks"),
])
def test_a_pilot_without_both_classes_is_undefined_never_zero_or_half(labels, status):
    result = oes.evaluate(grid_blocks(labels, [10.0, 20, 30, 40]), fast_protocol(block_m=None), CASE)
    assert result["status"] == status
    assert all(result[key] is None for key in result if key not in ("status", "row"))
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("short", [None, "observed_positives", "not_mapped_blocks"])
def test_a_class_below_the_locked_minimum_is_undefined(short):
    definition = oes.PROTOCOL["definition"]
    assert definition == {"min_observed_wet_blocks": 30, "min_not_mapped_blocks": 30}  # fixed before any run
    n_wet = definition["min_observed_wet_blocks"] - (short == "observed_positives")
    n_not_mapped = definition["min_not_mapped_blocks"] - (short == "not_mapped_blocks")
    labels = [1] * n_wet + [0] * n_not_mapped
    protocol = oes.lock_protocol({CASE: 100})
    protocol["null"]["n"] = protocol["interval"]["n"] = 9
    result = oes.evaluate(grid_blocks(labels, np.arange(len(labels), dtype=float)), protocol, CASE)
    assert result["status"] == (f"undefined_too_few_{short}" if short else "ok")
    assert (result["auc"] is None) == bool(short)


def test_only_locked_pilot_layer_years_are_evaluated_and_recorded():
    blocks = grid_blocks([1, 0], [10.0, 20.0])
    for aoi_id, layer, year in (("bangkok-city", CASE[1], 2011), (CASE[0], CASE[1], 2010),
                                (CASE[0], "mitrearth-water-body", 2006), (CASE[0], CASE[1], 2006.0)):
        with pytest.raises(ValueError, match="pilot layer-year"):  # 2011 outside the pilots is reserved
            oes.lock_protocol({(aoi_id, layer, year): 100})
    with pytest.raises(ValueError, match="not a locked"):  # lock before any overlap
        oes.evaluate(blocks, fast_protocol(), (CASE[0], CASE[1], 2011))
    with pytest.raises(ValueError, match="block_table"):
        oes.evaluate(blocks.assign(state=["observed_wet", "stored"]), fast_protocol(), CASE)
    seen = {(entry["year"], tuple(entry["aoi_ids"])) for entry in oes.PROTOCOL["seen_by_authors"]}
    assert seen == {(2006, tuple(oes.PILOT_AOIS)), (2011, tuple(oes.PILOT_AOIS))} and len(oes.PILOT_AOIS) == 4
    assert [(entry["year"], entry["for"]) for entry in oes.PROTOCOL["reserved"]] == [
        (2011, "BKK-036C held-out validation")]


def test_protocol_record_locks_every_choice_and_fills_the_record():
    protocol = fast_protocol()
    assert protocol["protocol_version"] == "oec-v1" and protocol["layers"] == {"mitrearth-flood-gistda": [2006, 2011]}
    assert {"statistic", "secondary", "null", "interval", "definition", "unit", "masks", "rows", "observed_input",
            "seen_by_authors", "reserved", "cases"} <= set(protocol)
    assert protocol["null"]["method"] == "toroidal_shift" and protocol["interval"]["method"] == "block_bootstrap"
    nodes, origin, blocks = scenario_blocks(0.55, 150.0, {(0, 0), (3, 3), (5, 1)})
    scenario = {"model_name": "bkk-scenario-depth-decay", "model_version": "0.1.0", "parameters": {
        "severity": "moderate", "source_role": "scenario", "peak_depth_m": 0.55, "decay_length_m": 150.0}}
    kwargs = dict(run_id="r", aoi_id=CASE[0], flood_scenario=scenario, declared_sha256="d", layer=CASE[1],
                  year=CASE[2], observed_sha256="o", nodes=nodes, origin=origin, blocks=blocks, protocol=protocol)
    record = oec.build_record(**kwargs, metrics=oes.evaluate(blocks, protocol, CASE))
    assert record["metrics"]["status"] == "ok" and record["metrics"]["interval"]["block_m"] == 100
    assert record["seen_by_authors"] == oes.PROTOCOL["seen_by_authors"] and record["reserved"] == oes.PROTOCOL["reserved"]
    assert json.loads(json.dumps(record, allow_nan=False)) == record
    for bad in ({"year": 2011}, {"aoi_id": "din-daeng-district"}):  # pilot layer-years, but not locked cases
        with pytest.raises(ValueError, match="locked case"):
            oec.build_record(**{**kwargs, **bad})
    with pytest.raises(ValueError, match="row"):
        oec.build_record(**kwargs, metrics=oes.evaluate(blocks, protocol, CASE, row="sensitivity:all_stored_points"))
    for bad in ({"aoi_id": "bangkok-city", "year": 2011}, {"year": 2010}):  # never the reserved area, with or
        for extra in ({"protocol": None}, {"protocol": None, "metrics": record["metrics"]}):  # without a protocol
            with pytest.raises(ValueError, match="pilot layer-year"):
                oec.build_record(**{**kwargs, **bad, **extra})
    with pytest.raises(ValueError, match="locked protocol"):
        oec.build_record(**{**kwargs, "protocol": None}, metrics=record["metrics"])
    record["reserved"][0]["use"] = "changed"
    assert oes.PROTOCOL["reserved"][0]["use"].startswith("none")  # the record holds a copy
