"""Tests for the BKK-056b psk-v1 grid statistics: TOC, toroidal null, paired bootstrap, correlogram.

Synthetic fixtures only. On oec-v1's own fixtures the new code must reproduce oec-v1's results
(docs/POINT_SKILL_PROTOCOL.md section 3.4); oec-v1's code, PROTOCOL and tests are not touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import observed_extent_stats as oes  # noqa: E402
from bkkflow import point_skill_stats as pss  # noqa: E402

POS, NEG = [10.0, 30.0, np.inf], [20.0, 30.0, np.inf, 40.0]  # oec-v1's hand ranks, positives first
WET = np.array([True] * 3 + [False] * 4)
SQUARES = np.add.outer(np.arange(12) // 3, np.arange(12) // 3) % 2  # 300 m squares: range 200 m
CHECKER = np.indices((12, 12)).sum(0) % 2  # range 100 m
HALF_PLANE = np.repeat((np.arange(20) < 10)[:, None], 40, axis=1).astype(int)  # r stays near 0.4 to lag 10


def grid_blocks(label, distance):
    """oec-v1's block table for a dense grid: label 1 observed wet, 0 not mapped, -1 unknown."""
    label, distance = np.atleast_2d(label), np.atleast_2d(np.asarray(distance, dtype=float))
    bi, bj = np.indices(label.shape)
    state = np.select([label == 1, label == 0], ["observed_wet", "not_mapped_as_flooded"], "unknown")
    return pd.DataFrame({"bi": bi.ravel(), "bj": bj.ravel(), "state": state.ravel(),
                         "min_stored_distance_m": distance.ravel(), "min_stored_distance_all_m": distance.ravel()})


def sparse_labels(side=60, sensors=70, seed=7):
    """Sensor-like labels: a few labelled blocks scattered over a large grid, half of them positive."""
    label = np.full((side, side), -1)
    label.flat[np.random.default_rng(seed).choice(side * side, sensors, replace=False)] = np.arange(sensors) % 2
    return label


def null_fixtures():
    rng = np.random.default_rng(3)
    distance = rng.random((10, 10)) * 500
    clustered = (rng.random((20, 20)) < 0.3).astype(int)
    clustered[rng.random((20, 20)) < 0.2] = -1
    return [((rng.random((10, 10)) < 0.3).astype(int), distance),  # no structure
            ((distance < np.quantile(distance, 0.3)).astype(int), distance),  # aligned with the rank
            (np.array([[1, 0, 0, -1]]), np.array([[10.0, 20, 30, 40]])),  # a shift brings in unknown
            (clustered, rng.random((20, 20)))]  # unknown holes


# AUC and TOC
def test_auc_is_oec_v1s_unchanged_and_higher_scores_are_negated(monkeypatch):
    assert pss.auc(POS + NEG, WET, higher_is_wetter=False) == oes.auc(POS + NEG, WET) == pytest.approx(7 / 12)
    assert pss.auc(-np.array(POS + NEG), WET, higher_is_wetter=True) == pytest.approx(7 / 12)
    rng = np.random.default_rng(5)
    value, wet = rng.integers(0, 6, 60).astype(float), rng.random(60) < 0.4
    brute = np.mean([1.0 if p > q else 0.5 if p == q else 0.0 for p in value[wet] for q in value[~wet]])
    assert pss.auc(value, wet, higher_is_wetter=True) == pytest.approx(brute)
    calls = []
    monkeypatch.setattr(oes, "auc", lambda rank, positive: calls.append(np.asarray(rank)) or 0.25)
    assert pss.auc([0.2, 0.5], [True, False], higher_is_wetter=True) == 0.25
    assert calls[0].tolist() == [-0.2, -0.5]  # oec-v1's own auc, which ranks the lower value wetter


def test_toc_reproduces_oec_v1_and_keeps_the_scores_own_units():
    toc = pss.toc(POS + NEG, WET, higher_is_wetter=False, bottom="beyond_storage_corridor")
    assert [{"threshold_m" if key == "threshold" else key: value for key, value in point.items()}
            for point in toc] == oes.toc(POS + NEG, WET)
    depth = [0.5, 0.0, -np.inf, 0.5, 0.2]  # -inf: evaluated but never stored, the bottom tie
    assert pss.toc(depth, [True, False, True, False, True], higher_is_wetter=True, bottom="below_storage") == [
        {"threshold": 0.5, "flagged": 2, "hits": 1}, {"threshold": 0.2, "flagged": 3, "hits": 2},
        {"threshold": 0.0, "flagged": 4, "hits": 2}, {"threshold": "below_storage", "flagged": 5, "hits": 3}]
    assert str(pss.toc([0.0], [True], higher_is_wetter=True, bottom="x")[0]["threshold"]) == "0.0"  # never -0.0
    with pytest.raises(ValueError, match="NaN"):
        pss.toc([1.0, np.nan], [True, False], higher_is_wetter=True, bottom="x")


# Toroidal null
@pytest.mark.parametrize("index", range(4))
def test_null_reproduces_oec_v1_when_the_domain_is_the_labelled_blocks(index):
    label, distance = null_fixtures()[index]
    new = pss.toroidal_null(label, {"d": distance}, domain=label != -1, n=99, seed=1)
    assert new["d"] == oes.toroidal_null(grid_blocks(label, distance), "primary", n=99, seed=1)


def test_a_shifted_label_is_scored_wherever_it_lands_in_the_domain():
    # North, 10 Nov 2026 (Q6): oec-v1 scores a shifted label only where a label already sat, which
    # leaves most shifts of sparse sensor labels undefined.
    label = sparse_labels()
    distance = np.random.default_rng(8).random(label.shape)
    assert oes.toroidal_null(grid_blocks(label, distance), "primary", n=99, seed=1)["n_undefined"] > 50
    everywhere = np.ones(label.shape, dtype=bool)
    new = pss.toroidal_null(label, {"d": distance, "reversed": -distance}, domain=everywhere, n=99, seed=1)
    assert new["d"]["n_undefined"] == 0 and new["d"]["evaluable_range"] == [70, 70]
    shared = ("method", "seed", "n", "n_undefined", "prevalence_range", "evaluable_range")
    assert {key: new["d"][key] for key in shared} == {key: new["reversed"][key] for key in shared}
    holed = everywhere.copy()
    holed[:, :30] = False  # a label that lands outside the domain leaves that shift's sample
    low, high = pss.toroidal_null(label, {"d": distance}, domain=holed, n=99, seed=1)["d"]["evaluable_range"]
    assert low < high < 70
    with pytest.raises(ValueError, match="undefined"):
        pss.toroidal_null(np.zeros((4, 4), dtype=int), {"d": distance[:4, :4]}, domain=everywhere[:4, :4], n=9, seed=1)


# Paired block bootstrap
@pytest.mark.parametrize("label, block_m", [(SQUARES, 200), (CHECKER, 100), (np.eye(4, dtype=int), 400),
                                            (HALF_PLANE, 300)])
def test_paired_bootstrap_reproduces_oec_v1_for_every_score(label, block_m):
    rng = np.random.default_rng(4)
    scores = {"a": rng.random(label.shape) * 100,
              "b": np.add.outer(np.arange(label.shape[0]), np.arange(label.shape[1])).astype(float)}
    new = pss.paired_block_bootstrap(label, scores, [("a", "b")], domain=label != -1, block_m=block_m, n=49, seed=21)
    for name, rank in scores.items():
        old = oes.block_bootstrap(grid_blocks(label, rank), "primary", block_m, 49, 21)
        assert new["ci95"][name] == old["ci95"]
        assert (new["n_tiles"], new["n_undefined"], new["block_m"]) == (old["n_tiles"], old["n_undefined"], block_m)


def test_the_paired_difference_comes_from_the_same_resamples():
    distinct = np.add.outer(np.arange(12.0) * 12, np.arange(12.0))  # no ties, so AUC(-d) = 1 - AUC(d) per draw
    out = pss.paired_block_bootstrap(SQUARES, {"d": distinct, "reversed": -distinct, "same": distinct},
                                     [("d", "reversed"), ("d", "same")], domain=SQUARES != -1,
                                     block_m=200, n=99, seed=5)
    low, high = out["ci95"]["d"]
    assert out["differences"][0]["candidate"] == "d" and out["differences"][0]["rung"] == "reversed"
    assert out["differences"][0]["ci95"] == pytest.approx([2 * low - 1, 2 * high - 1])
    assert out["differences"][1] == {"candidate": "d", "rung": "same", "ci95": [0.0, 0.0]}
    for bad in (150, 0, 200.0, True, "capped"):
        with pytest.raises(ValueError, match="multiple of 100"):
            pss.paired_block_bootstrap(SQUARES, {"d": distinct}, [], domain=SQUARES != -1, block_m=bad, n=9, seed=1)
    with pytest.raises(ValueError, match="score"):
        pss.paired_block_bootstrap(SQUARES, {"d": distinct}, [("d", "missing")], domain=SQUARES != -1,
                                   block_m=200, n=9, seed=1)


# Correlogram and the block-length rule
@pytest.mark.parametrize("label", [SQUARES, CHECKER, HALF_PLANE, np.eye(12, 30, dtype=int)])
def test_correlogram_and_range_reproduce_oec_v1_on_dense_labels(label):
    blocks = grid_blocks(label, np.zeros(label.shape))
    correlogram = pss.correlogram(label)
    assert correlogram["r"] == oes.correlogram(blocks)
    assert correlogram["lags_m"] == [100 * h for h in range(1, min(label.shape) // 2 + 1)]
    assert pss.correlation_range_m(label) == oes.correlation_range_m(blocks)
    assert pss.correlogram(SQUARES)["pairs"] == [2 * 12 * (12 - h) for h in range(1, 7)]


def test_the_range_rule_reads_only_lags_with_thirty_pairs():
    assert pss.MIN_LAG_PAIRS == 30  # North, 10 Nov 2026 (Q7), amending D4 for sparse labels

    def rule(r, pairs):
        return pss.range_from_correlogram({"lags_m": [100 * h for h in range(1, len(r) + 1)], "r": r, "pairs": pairs})

    assert rule([0.4, -0.3, 0.05, -0.2], [30, 29, 30, 30]) == 300  # -0.3 rests on 29 pairs: skipped
    assert rule([0.4, None, 0.02], [30, 40, 30]) == 300  # an undefined lag is skipped, as in oec-v1
    assert rule([0.4, 0.3], [30, 30]) == pss.NOT_ESTIMABLE == oes.NOT_ESTIMABLE
    assert rule([-0.5, -0.5], [29, 2]) == pss.NOT_ESTIMABLE  # no lag qualifies
    assert rule([], []) == pss.NOT_ESTIMABLE  # a grid too narrow for any lag
    with pytest.raises(ValueError, match="no correlogram lag"):
        rule([None, None], [30, 40])  # lags qualify, but one class only: locked undefined, as in D4


def test_sparse_sensor_labels_get_no_block_length_from_a_handful_of_pairs():
    # psk-v1 section 3.4 required this fixture before any real run; it found the rule picking lengths
    # from 3-4 pairs, so North set the 30-pair minimum (Q7).
    label = sparse_labels()
    assert isinstance(oes.correlation_range_m(grid_blocks(label, np.zeros(label.shape))), int)  # oec-v1 picks one
    correlogram = pss.correlogram(label)
    assert len(correlogram["lags_m"]) == 30 and max(correlogram["pairs"]) < 10
    assert all(r is None for r in correlogram["r"])
    assert pss.correlation_range_m(label) == pss.NOT_ESTIMABLE
    assert pss.not_estimable_interval(label) == {
        "method": "paired_block_bootstrap", "status": "interval_not_estimable", "reason": "no_lag_with_min_pairs",
        "lags_m": correlogram["lags_m"], "r": correlogram["r"], "pairs": correlogram["pairs"], "ci95": None}
    patch = np.full((60, 60), -1)
    patch[:12, :12] = SQUARES  # a dense patch keeps its range: only its own lags qualify
    correlogram = pss.correlogram(patch)
    assert correlogram["pairs"] == [2 * 12 * (12 - h) for h in range(1, 12)] + [0] * 19
    assert correlogram["r"][9] is not None and correlogram["r"][10] is None  # lag 11 has 24 pairs
    assert pss.correlation_range_m(patch) == 200


def test_the_fallback_keeps_oec_v1s_reason_when_lags_qualify_but_never_fall():
    interval = pss.not_estimable_interval(HALF_PLANE)
    assert interval["reason"] == oes.PROTOCOL["interval"]["fallback"]["reason"] == "correlation_range_exceeds_half_grid"
    assert interval["lags_m"] == list(range(100, 1100, 100)) and all(r > 0.05 for r in interval["r"])
    assert interval["ci95"] is None and interval["status"] == oes.NOT_ESTIMABLE
    with pytest.raises(ValueError, match="has a range"):
        pss.not_estimable_interval(SQUARES)
