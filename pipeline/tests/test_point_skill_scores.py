"""Tests for the BKK-056b psk-v1 block scores: candidates (Q2), channel, D6 windows, rain (Q4), persistence (Q5).

Synthetic fixtures only: no gauge, sensor, report or surface from a real run is read.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Polygon, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import observed_extent as oec  # noqa: E402
from bkkflow import point_skill_scores as pks  # noqa: E402
from bkkflow.flood import FloodScenario, build_depth_surface, build_flood_slices  # noqa: E402

CRS = "EPSG:32647"
ORIGIN = (0.0, 0.0)
T0 = pd.Timestamp("2026-09-26 09:00", tz="Asia/Bangkok")
WINDOW = (T0, T0 + pd.Timedelta(hours=6))
INF = np.inf


def points(rows):
    return pd.DataFrame(rows, columns=["i", "j", "aoi_frac", "value"])


def blocks_frame(*pairs):
    return pd.DataFrame(pairs, columns=["bi", "bj"])


# Q2: a block's score is its wettest lattice point
def test_a_block_takes_its_wettest_point_and_unstored_points_tie_at_the_bottom():
    frame = points([
        (0, 0, 1.0, 0.3), (1, 0, 1.0, 0.1), (0, 1, 1.0, -INF), (1, 1, 1.0, np.nan),  # 3 squares evaluated
        (2, 0, 1.0, -INF), (3, 0, 1.0, -INF), (2, 1, 1.0, np.nan), (3, 1, 1.0, np.nan),  # evaluated, none stored
        (4, 0, 1.0, 0.9), (5, 0, 1.0, np.nan), (4, 1, 1.0, np.nan), (5, 1, 1.0, np.nan),  # 1 square: out
        (6, 0, 0.4, 0.8), (7, 0, 1.0, 0.2), (6, 1, 1.0, np.nan), (7, 1, 1.0, 0.1),  # 0.8 sits mostly outside the AOI
    ])
    scores = pks.block_scores(frame, higher_is_wetter=True)
    assert scores["bi"].tolist() == [0, 1, 2, 3] and scores["in_domain"].tolist() == [True, True, False, True]
    assert scores.loc[scores.in_domain, "score"].tolist() == [0.3, -INF, 0.2]
    distances = pks.block_scores(frame.assign(value=frame["value"].abs()), higher_is_wetter=False)
    assert distances["score"].tolist()[:2] == [0.1, INF]  # nearest for a distance; the bottom tie is +inf


def test_the_scenario_block_score_orders_blocks_as_oec_v1s_block_rank():
    diagonal = gpd.GeoDataFrame(geometry=[LineString([(10, 20), (810, 820)])], crs=CRS)
    square = box(0, 0, 800, 800)
    scenario = FloodScenario("t", "moderate", 0, 600, 1200, decay_length_m=40.0, peak_depth_m=0.55)
    surface = build_depth_surface(diagonal, scenario=scenario, analysis_crs=CRS, aoi_geometry=square)
    nodes, _ = oec.declared_nodes(build_flood_slices(surface, scenario=scenario), diagonal, square)
    observed = nodes[["i", "j"]].assign(observed_wet_frac=0.0, channel_frac=0.0, source_role="mapped")
    ranks = oec.block_table(nodes, observed, "mitrearth-flood-gistda")[["bi", "bj", "min_stored_distance_m"]]
    scores = pks.block_scores(pks.scenario_points(nodes), higher_is_wetter=True)
    joined = ranks.merge(scores, on=["bi", "bj"], validate="one_to_one").sort_values("min_stored_distance_m")
    score = joined["score"].to_numpy()
    assert np.all(score[1:] <= score[:-1])  # nearer is never shallower; -inf <= -inf holds for the bottom tie
    assert (joined["min_stored_distance_m"] == INF).tolist() == (joined["score"] == -INF).tolist()
    assert (joined["score"] == -INF).any() and (joined["score"] > 0).any()
    with pytest.raises(ValueError, match="state"):
        pks.scenario_points(nodes.assign(state="dry"))


def test_a_coarser_surface_gives_each_point_its_cells_value():
    cells = pd.DataFrame({"x_min": [0.0, 1000.0, 0.0], "y_min": [0.0, 0.0, 1000.0], "value": [0.2, 0.7, 0.5]})
    x, y = [0.0, 999.9, 1000.0, 500.0, 2500.0, -0.1], [0.0, 0.0, 0.0, 1500.0, 0.0, 0.0]
    values = pks.cell_values(x, y, cells, 1000.0)
    assert values[:4].tolist() == [0.2, 0.2, 0.7, 0.5] and np.isnan(values[4:]).all()  # half-open cells
    with pytest.raises(ValueError, match="regular grid"):
        pks.cell_values(x, y, cells.assign(x_min=[0.0, 1000.0, 10.0]), 1000.0)
    with pytest.raises(ValueError, match="regular grid"):
        pks.cell_values(x, y, pd.concat([cells, cells.iloc[:1]]), 1000.0)


def test_the_channel_rung_is_the_distance_of_the_blocks_nearest_point():
    lattice = pd.DataFrame({"i": [0, 1, 2, 3], "j": 0, "x": [0.0, 50.0, 100.0, 150.0], "y": 0.0, "aoi_frac": 1.0})
    distance = pks.channel_distance(lattice, box(-1000, -1000, -25, 1000))
    assert distance.tolist() == [25.0, 75.0, 125.0, 175.0]
    scores = pks.block_scores(lattice.assign(value=distance), higher_is_wetter=False)
    assert scores["score"].tolist() == [25.0, 125.0]
    with pytest.raises(ValueError, match="channel mask"):
        pks.channel_distance(lattice, Polygon())


# D6 windows
def test_timed_surfaces_score_t_to_t_plus_lead_and_declared_scenarios_the_event_window():
    timed = {"timing": "timed", "issue_time": T0, "lead": pd.Timedelta(hours=3)}
    assert pks.scoring_window(timed, WINDOW) == (T0, T0 + pd.Timedelta(hours=3))
    assert pks.scoring_window({"timing": "declared"}, WINDOW) == WINDOW
    assert pks.prior_window(WINDOW) == (T0 - pd.Timedelta(hours=6), T0)
    for bad in ({**timed, "lead": pd.Timedelta(0)}, {"timing": "forecast"}, {}):
        with pytest.raises(ValueError, match="timing|lead"):
            pks.scoring_window(bad, WINDOW)
    with pytest.raises(ValueError, match="event window"):
        pks.scoring_window({"timing": "declared"}, WINDOW[::-1])
    assert pks.rain_window(timed, WINDOW, hours_before=3) == (T0 - pd.Timedelta(hours=3), T0)  # Q4: before t
    assert pks.rain_window({"timing": "declared"}, WINDOW, hours_before=3) == WINDOW
    for bad in (0, 2.5, True):
        with pytest.raises(ValueError, match="hours"):
            pks.rain_window(timed, WINDOW, hours_before=bad)


# Q4: the rain-only rung
def rain(gauge, values, start=T0):
    times = start + pd.to_timedelta(np.arange(len(values)), unit="h")
    return pd.DataFrame({"gauge_id": gauge, "time": times, "rain_mm": np.asarray(values, dtype=float)})


def test_a_gauge_with_any_gap_is_incomplete_and_never_read_as_zero():
    feed = pd.concat([rain("a", [1, 2, 3, 0, 0, 4, 5]), rain("b", [9] * 5), rain("c", [1, np.nan, 1, 1, 1, 1, 1]),
                      rain("a", [50.0], start=T0 - pd.Timedelta(hours=1))])  # before the window
    totals = pks.gauge_totals(feed, {"a": 7, "b": 7, "c": 7, "d": 7}, WINDOW).set_index("gauge_id")
    assert totals.loc["a"].tolist() == [15.0, True] and not totals.loc[["b", "c", "d"], "complete"].any()
    for bad_feed, schedule, message in ((rain("a", [-1.0]), {"a": 1}, "negative"),
                                        (pd.concat([rain("a", [1.0])] * 2), {"a": 2}, "duplicate"),
                                        (rain("a", [1.0, 1.0]), {"a": 1}, "more readings"),
                                        (rain("z", [1.0]), {"a": 1}, "schedule"), (rain("a", [1.0]), {"a": 0}, "schedule")):
        with pytest.raises(ValueError, match=message):
            pks.gauge_totals(bad_feed, schedule, WINDOW)


def test_the_rain_rung_is_idw_power_two_over_complete_gauges():
    assert pks.IDW_POWER == 2  # North, 10 Nov 2026 (Q4b)
    gauges = pd.DataFrame({"gauge_id": ["g1", "g2", "g3"], "x": [25.0, 1025.0, 225.0], "y": [25.0, 25.0, 25.0]})
    totals = pd.DataFrame({"gauge_id": ["g1", "g2", "g3"], "total_mm": [10.0, 30.0, 1000.0],
                           "complete": [True, True, False]})  # g3 has a gap: left out, never zero
    values = pks.idw_rain(blocks_frame((0, 0), (5, 0), (2, 0)), ORIGIN, gauges, totals)
    assert values == pytest.approx([10.0, 20.0, (16 * 10 + 30) / 17])  # on g1; halfway; 200 m and 800 m away
    with pytest.raises(ValueError, match="complete"):
        pks.idw_rain(blocks_frame((0, 0)), ORIGIN, gauges, totals.assign(complete=False))
    with pytest.raises(ValueError, match="position"):
        pks.idw_rain(blocks_frame((0, 0)), ORIGIN, gauges.iloc[:1], totals)


# Q5: the persistence rung
def test_persistence_reads_the_equal_window_before_and_ties_blocks_without_one_at_the_bottom():
    sensors = pd.DataFrame({"sensor_id": ["a", "b"], "x": [10.0, 310.0], "y": [10.0, 10.0]})
    hours = pd.Timedelta(hours=1)
    readings = pd.DataFrame({"sensor_id": ["a", "a", "a", "a"], "depth_m": [0.3, 0.9, 0.5, np.nan],
                             "time": [T0 - hours, T0 - 7 * hours, T0, T0 - 2 * hours]})
    values = pks.sensor_persistence(readings, sensors, ORIGIN, WINDOW, blocks_frame((0, 0), (3, 0), (5, 5)))
    assert values.tolist() == [0.3, -INF, -INF]  # 0.9 is too early; 0.5 is inside the scoring window
    counts = pd.DataFrame({"bi": [0, 1, 0], "bj": 0, "count": [2, 1, 4],
                           "time": [T0 - 2 * hours, T0 - 6 * hours, T0]})
    assert pks.report_persistence(counts, WINDOW, blocks_frame((0, 0), (1, 0), (2, 0))).tolist() == [2, 1, 0]
    with pytest.raises(ValueError, match="bi, bj, time, count"):
        pks.report_persistence(counts.assign(text="x"), WINDOW, blocks_frame((0, 0)))


# Review round (code-reviewer, python-reviewer): regressions
def test_block_scores_refuse_duplicate_points_and_blank_out_of_domain_blocks():
    frame = points([(0, 0, 1.0, 0.9), (1, 0, 1.0, np.nan), (0, 1, 1.0, np.nan), (1, 1, 1.0, np.nan)])
    scores = pks.block_scores(frame, higher_is_wetter=True)
    assert scores["in_domain"].tolist() == [False] and np.isnan(scores["score"]).all()  # never ranked by mistake
    with pytest.raises(ValueError, match="once"):
        pks.block_scores(pd.concat([frame, frame]), higher_is_wetter=True)


def test_scenario_points_refuse_a_stored_point_without_a_value():
    nodes = pd.DataFrame({"i": [0], "j": [0], "x": [0.0], "y": [0.0], "aoi_frac": [1.0], "state": ["stored"],
                          "peak_depth_m": [np.nan]})
    with pytest.raises(ValueError, match="stored"):
        pks.scenario_points(nodes)


def test_cell_values_tolerate_float_edges_and_refuse_bad_grids():
    origin = 0.1 + 0.2  # 0.30000000000000004: a lattice point meant to sit on a cell edge lands a hair below it
    cells = pd.DataFrame({"x_min": [origin, origin + 1000.0], "y_min": [0.0, 0.0], "value": [0.2, 0.7]})
    edge = origin + 1000.0 - 1e-12
    assert pks.cell_values([edge], [10.0], cells, 1000.0).tolist() == [0.7]
    for bad_cells, cell_m in ((cells.iloc[:0], 1000.0), (cells, -1000.0), (cells, np.nan)):
        with pytest.raises(ValueError, match="cell"):
            pks.cell_values([500.0], [10.0], bad_cells, cell_m)


def test_channel_distance_refuses_non_finite_points_and_reads_each_part_of_the_mask():
    mask = box(-1000, -1000, -25, 1000).union(box(300, -1000, 400, 1000))  # two separate channels
    lattice = pd.DataFrame({"x": [0.0, 250.0, 350.0], "y": 0.0})
    assert pks.channel_distance(lattice, mask).tolist() == [25.0, 50.0, 0.0]
    with pytest.raises(ValueError, match="finite"):
        pks.channel_distance(lattice.assign(x=[0.0, np.nan, 1.0]), mask)


def test_rain_must_be_finite_and_the_chunked_idw_matches_one_pass(monkeypatch):
    with pytest.raises(ValueError, match="finite"):
        pks.gauge_totals(rain("a", [1.0, np.inf]), {"a": 2}, WINDOW)
    gauges = pd.DataFrame({"gauge_id": ["g1", "g2"], "x": [25.0, 1025.0], "y": [25.0, 525.0]})
    totals = pd.DataFrame({"gauge_id": ["g1", "g2"], "total_mm": [10.0, 30.0], "complete": True})
    with pytest.raises(ValueError, match="finite"):
        pks.idw_rain(blocks_frame((0, 0)), ORIGIN, gauges, totals.assign(total_mm=[10.0, np.nan]))
    blocks = blocks_frame(*[(i, j) for i in range(4) for j in range(3)])
    whole = pks.idw_rain(blocks, ORIGIN, gauges, totals)
    monkeypatch.setattr(pks, "_CHUNK", 5)  # 12 blocks in chunks of 5, 5 and 2
    assert pks.idw_rain(blocks, ORIGIN, gauges, totals).tolist() == whole.tolist()
    assert pks.rain_window({"timing": "declared"}, WINDOW, hours_before=np.int64(3)) == WINDOW


def test_windows_are_checked_and_empty_observations_give_the_bottom():
    with pytest.raises(ValueError, match="window"):
        pks.prior_window(WINDOW[::-1])
    with pytest.raises(ValueError, match="lead|issue_time"):
        pks.scoring_window({"timing": "timed", "issue_time": T0}, WINDOW)
    sensors = pd.DataFrame({"sensor_id": ["a"], "x": [10.0], "y": [10.0]})
    naive = pd.DataFrame({"sensor_id": ["a"], "depth_m": [0.3], "time": [(T0 - pd.Timedelta(hours=1)).tz_localize(None)]})
    with pytest.raises(ValueError, match="time zone"):
        pks.sensor_persistence(naive, sensors, ORIGIN, WINDOW, blocks_frame((0, 0)))
    silent = pd.DataFrame({"sensor_id": [], "depth_m": [], "time": []})
    assert pks.sensor_persistence(silent, sensors, ORIGIN, WINDOW, blocks_frame((0, 0))).tolist() == [-INF]
    quiet = pd.DataFrame({"bi": [], "bj": [], "time": [], "count": []})
    assert pks.report_persistence(quiet, WINDOW, blocks_frame((1, 0), (0, 0))).tolist() == [0.0, 0.0]
