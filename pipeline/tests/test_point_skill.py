"""Tests for the BKK-056b psk-v1 labels and building cover (docs/POINT_SKILL_PROTOCOL.md s3.2, s3.3, s5).

Synthetic fixtures only: no sensor feed, report source or building layer is read.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import point_skill as psk  # noqa: E402

CRS = "EPSG:32647"
T0 = pd.Timestamp("2026-09-26 09:00", tz="Asia/Bangkok")
WINDOW = (T0, T0 + pd.Timedelta(hours=6))


def readings(sensor, depths, start=T0, step_min=1):
    """One sensor's readings, one a minute from ``start``; NaN is a reading that arrived empty (a gap)."""
    times = start + pd.to_timedelta(np.arange(len(depths)) * step_min, unit="min")
    return pd.DataFrame({"sensor_id": sensor, "time": times, "depth_m": np.asarray(depths, dtype=float)})


def state_of(depths, scheduled):
    return psk.sensor_labels(readings("s", depths), {"s": scheduled}, WINDOW).set_index("sensor_id").loc["s", "state"]


# D2a and D2b, per sensor
def test_d2b_ninety_percent_of_scheduled_readings_all_below_threshold_is_dry():
    assert psk.DRY_SHARE == psk.Fraction(9, 10) and psk.WET_DEPTH_M == 0.15  # North, 10 Nov 2026 (D2a, D2b)
    assert state_of([0.14] * 89, 100) == "unknown"  # 89% reported: never dry
    assert state_of([0.14] * 90, 100) == "observed_dry"
    assert state_of([0.14] * 88 + [0.15], 100) == "observed_wet"  # fewer than 90% with a maximum >= 0.15 m
    assert state_of([0.14] * 89 + [np.nan], 100) == "unknown"  # an empty reading is a gap: 89 reported
    assert state_of([], 100) == "unknown"  # a silent sensor is a gap, never dry
    assert state_of([0.1499] * 100, 100) == "observed_dry" and state_of([0.15], 100) == "observed_wet"


@pytest.mark.parametrize("scheduled", range(1, 301))
def test_the_ninety_percent_share_is_exact_for_every_schedule(scheduled):
    least = -(-9 * scheduled // 10)  # the smallest count with 10 * reported >= 9 * scheduled, in integers
    assert state_of([0.0] * least, scheduled) == "observed_dry"
    assert state_of([0.0] * (least - 1), scheduled) == "unknown"


def test_only_readings_inside_the_closed_window_count_and_bad_feeds_are_refused():
    inside = readings("s", [0.0] * 9, start=T0 + pd.Timedelta(hours=6) - pd.Timedelta(minutes=8))  # last at the end
    outside = readings("s", [0.5, 0.5], start=T0 - pd.Timedelta(minutes=2))  # before the window opens
    labels = psk.sensor_labels(pd.concat([inside, outside]), {"s": 10, "silent": 4}, WINDOW).set_index("sensor_id")
    assert labels.loc["s", "reported"] == 9 and labels.loc["s", "state"] == "observed_dry"
    assert labels.loc["silent", "reported"] == 0 and labels.loc["silent", "state"] == "unknown"
    assert set(labels["state"]) <= set(psk.SENSOR_STATES)
    with pytest.raises(ValueError, match="duplicate"):
        psk.sensor_labels(pd.concat([inside, inside]), {"s": 20}, WINDOW)
    with pytest.raises(ValueError, match="more readings than scheduled"):
        psk.sensor_labels(inside, {"s": 8}, WINDOW)
    with pytest.raises(ValueError, match="schedule"):
        psk.sensor_labels(inside, {"other": 10}, WINDOW)
    for bad in (0, -3, 2.5, True):
        with pytest.raises(ValueError, match="schedule"):
            psk.sensor_labels(inside, {"s": bad}, WINDOW)


# Several sensors in one block (North, 10 Nov 2026, Q1)
def test_block_of_groups_lattice_points_two_by_two_as_oec_v1():
    origin = (12.5, 40.0)
    i, j = np.meshgrid(np.arange(-4, 6), np.arange(-3, 5))
    bi, bj = psk.block_of(origin[0] + 50 * i.ravel(), origin[1] + 50 * j.ravel(), origin)
    assert bi.tolist() == (i.ravel() // 2).tolist() and bj.tolist() == (j.ravel() // 2).tolist()
    bi, bj = psk.block_of([origin[0] - 24.9, origin[0] + 74.9], [origin[1] + 74.9, origin[1] - 25.1], origin)
    assert bi.tolist() == [0, 0] and bj.tolist() == [0, -1]  # a block spans the squares of its four points


@pytest.mark.parametrize("states, block_state", [
    (["observed_wet", "observed_dry"], "observed_wet"),  # any wet
    (["observed_dry", "observed_dry"], "observed_dry"),  # all dry
    (["observed_dry", "unknown"], "unknown"),  # a gap anywhere keeps the block from being dry
    (["unknown", "unknown"], "unknown"),
    (["observed_wet", "unknown"], "observed_wet"),
])
def test_a_block_is_wet_if_any_sensor_is_wet_and_dry_only_if_all_are(states, block_state):
    labels = pd.DataFrame({"sensor_id": ["a", "b", "c"], "state": [*states, "observed_dry"]})
    sensors = pd.DataFrame({"sensor_id": ["a", "b", "c"], "x": [10.0, 60.0, 310.0], "y": [10.0, 60.0, 10.0]})
    blocks, counts = psk.block_sensor_labels(labels, sensors, (0.0, 0.0))
    assert blocks[["bi", "bj", "sensors", "state"]].values.tolist() == [[0, 0, 2, block_state], [3, 0, 1, "observed_dry"]]
    conflict = {"observed_wet", "observed_dry"} <= set(states)
    assert counts == {"blocks_with_several_sensors": 1, "blocks_with_wet_dry_conflict": int(conflict)}
    with pytest.raises(ValueError, match="position"):
        psk.block_sensor_labels(labels, sensors.iloc[:2], (0.0, 0.0))


# Citizen reports (D2c with North's Q3: both classes need building cover above zero)
def test_reports_are_presence_only_and_both_classes_need_building_cover():
    cover = pd.DataFrame({"bi": [0, 1, 2, 3], "bj": 0, "cover": [0.4, 0.2, 0.0, 0.0]})
    counts = pd.DataFrame({"bi": [0, 2, 9, 1], "bj": 0, "count": [2, 1, 3, 5],
                           "time": [T0, T0 + pd.Timedelta(hours=1), T0, T0 - pd.Timedelta(minutes=1)]})
    blocks, tally = psk.report_labels(counts, cover, WINDOW)
    assert blocks[["bi", "reports", "state"]].values.tolist() == [
        [0, 2, "reported"], [1, 0, "not_reported"], [2, 1, "unknown"], [3, 0, "unknown"]]
    assert tally == {"reported_zero_cover_blocks": 1, "reported_outside_domain_blocks": 1}  # block 9: outside
    assert "observed_dry" not in set(blocks["state"]) and set(blocks["state"]) <= set(psk.REPORT_STATES)


def test_report_input_carries_block_counts_only():
    cover = pd.DataFrame({"bi": [0], "bj": [0], "cover": [0.5]})
    counts = pd.DataFrame({"bi": [0], "bj": [0], "time": [T0], "count": [1]})
    for extra in ("report_id", "text", "photo_url", "lon"):  # s3.7: no text, photo or id is ever kept
        with pytest.raises(ValueError, match="bi, bj, time, count"):
            psk.report_labels(counts.assign(**{extra: "x"}), cover, WINDOW)
    for bad in ([-1], [0.5]):
        with pytest.raises(ValueError, match="count"):
            psk.report_labels(counts.assign(count=bad), cover, WINDOW)
    with pytest.raises(ValueError, match="cover"):
        psk.report_labels(counts, cover.assign(cover=[1.2]), WINDOW)


# Building cover, the exposure rung and D2c's control pool (D3)
def blocks_frame(*pairs):
    return pd.DataFrame(pairs, columns=["bi", "bj"])


def test_building_cover_is_the_share_of_the_block_under_footprints():
    footprints = gpd.GeoDataFrame(geometry=[
        box(0, 0, 50, 50),  # inside block (0, 0), which spans x and y from -25 to 75
        box(0, 0, 50, 50),  # an overlapping duplicate never counts twice
        box(50, 100, 100, 150),  # straddles blocks (0, 1) and (1, 1): 25 m in each
        LineString([(200, 0), (260, 0)]), Point(210, 10),  # no area
    ], crs=CRS)
    cover = psk.building_cover(footprints, (0.0, 0.0), blocks_frame((0, 0), (0, 1), (1, 1), (2, 0)))
    assert cover["cover"].tolist() == pytest.approx([0.25, 0.125, 0.125, 0.0])
    assert cover[["bi", "bj"]].values.tolist() == [[0, 0], [0, 1], [1, 1], [2, 0]]
    full = gpd.GeoDataFrame(geometry=[box(-100, -100, 200, 200), box(-25, -25, 75, 75)], crs=CRS)
    assert psk.building_cover(full, (0.0, 0.0), blocks_frame((0, 0)))["cover"].tolist() == [1.0]


def test_building_cover_projects_repairs_and_refuses_a_layer_without_crs():
    footprints = gpd.GeoDataFrame(geometry=[box(660_000, 1_520_000, 660_050, 1_520_050)], crs=CRS)
    origin, block = (0.0, 0.0), blocks_frame((6600, 15200))
    in_degrees = footprints.to_crs("EPSG:4326")
    assert psk.building_cover(in_degrees, origin, block)["cover"].tolist() == pytest.approx([0.25], abs=1e-6)
    bow_tie = Polygon([(0, 0), (50, 50), (50, 0), (0, 50)])  # self-intersecting: two 625 m2 triangles
    repaired = psk.building_cover(gpd.GeoDataFrame(geometry=[bow_tie], crs=CRS), origin, blocks_frame((0, 0)))
    assert repaired["cover"].tolist() == pytest.approx([0.125])
    with pytest.raises(ValueError, match="CRS"):
        psk.building_cover(gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)]), origin, blocks_frame((0, 0)))


# Review round (code-reviewer, python-reviewer): regressions
def test_building_cover_matches_a_brute_force_union_on_hundreds_of_blocks():
    rng = np.random.default_rng(12)
    corners = rng.uniform(-50, 1950, size=(1500, 2))
    sizes = rng.uniform(2, 40, size=(1500, 2))
    footprints = gpd.GeoDataFrame(geometry=[box(x, y, x + w, y + h) for (x, y), (w, h) in zip(corners, sizes)], crs=CRS)
    blocks = blocks_frame(*[(i, j) for i in range(20) for j in range(20)])
    cover = psk.building_cover(footprints, (0.0, 0.0), blocks)["cover"].to_numpy()
    union = footprints.geometry.union_all()
    boxes = psk.block_boxes(blocks, (0.0, 0.0))
    brute = np.array([square.intersection(union).area / 10_000 for square in boxes])
    assert cover == pytest.approx(np.where(brute * 10_000 >= 1.0, brute, 0.0), abs=1e-12)


def test_cover_below_one_square_metre_is_zero():
    # North, 10 Nov 2026: a 1 m2 floor, so reprojection slivers never make a building-free block a control.
    assert psk.MIN_COVER_M2 == 1.0
    touching = gpd.GeoDataFrame(geometry=[box(75, 0, 100, 50)], crs=CRS).to_crs("EPSG:4326")  # abuts block (0, 0)
    assert psk.building_cover(touching, (0.0, 0.0), blocks_frame((0, 0)))["cover"].tolist() == [0.0]
    small = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1), box(30, 30, 30.9, 31)], crs=CRS)  # 1 m2 and 0.9 m2
    cover = psk.building_cover(small, (0.0, 0.0), blocks_frame((0, 0)))["cover"].tolist()
    assert cover == pytest.approx([1.9e-4])  # the floor reads the block's total, not each footprint
    alone = gpd.GeoDataFrame(geometry=[box(30, 30, 30.9, 31)], crs=CRS)
    assert psk.building_cover(alone, (0.0, 0.0), blocks_frame((0, 0)))["cover"].tolist() == [0.0]


def test_building_cover_ignores_empty_geometry_and_refuses_bad_input():
    mixed = gpd.GeoDataFrame(geometry=[box(0, 0, 50, 50), LineString([(0, 0), (50, 50)]), None, Polygon()], crs=CRS)
    assert psk.building_cover(mixed, (0.0, 0.0), blocks_frame((0, 0)))["cover"].tolist() == [0.25]
    with pytest.raises(ValueError, match="once"):
        psk.building_cover(mixed, (0.0, 0.0), blocks_frame((0, 0), (0, 0)))
    broken = gpd.GeoDataFrame(geometry=[Polygon([(0, 0), (np.nan, 1), (1, 1)])], crs=CRS)
    with pytest.raises(ValueError, match="finite"):
        psk.building_cover(broken, (0.0, 0.0), blocks_frame((0, 0)))


def test_depths_must_be_readings_and_windows_must_be_sound():
    for bad in (-9999.0, -0.01, np.inf):  # ingest (BKK-056c) maps any sentinel to a gap; the harness never guesses
        with pytest.raises(ValueError, match="depth"):
            state_of([0.1] * 95 + [bad], 100)
    assert state_of([0.1] * 90, np.int64(100)) == "observed_dry"  # a schedule may hold numpy integers
    feed = readings("s", [0.1] * 10)
    with pytest.raises(ValueError, match="window"):
        psk.sensor_labels(feed, {"s": 10}, WINDOW[::-1])
    with pytest.raises(ValueError, match="time zone"):
        psk.sensor_labels(feed, {"s": 10}, (T0.tz_localize(None), WINDOW[1].tz_localize(None)))
    with pytest.raises(ValueError, match="sensor_id"):
        psk.sensor_labels(feed.assign(sensor_id=[None] + ["s"] * 9), {"s": 10}, WINDOW)
    with pytest.raises(ValueError, match="finite"):
        psk.block_of([np.inf, 0.0], [0.0, 0.0], (0.0, 0.0))


def test_sensor_blocks_refuse_duplicate_positions_and_unknown_states():
    labels = pd.DataFrame({"sensor_id": ["a"], "state": ["observed_dry"]})
    twice = pd.DataFrame({"sensor_id": ["a", "a"], "x": [0.0, 1.0], "y": [0.0, 1.0]})
    with pytest.raises(ValueError):
        psk.block_sensor_labels(labels, twice, (0.0, 0.0))
    with pytest.raises(ValueError, match="states"):
        psk.block_sensor_labels(labels.assign(state="dry"), twice.iloc[:1], (0.0, 0.0))


def test_report_counts_must_be_aggregated_and_may_be_empty():
    cover = pd.DataFrame({"bi": [0, 1], "bj": [0, 0], "cover": [0.5, 0.0]})
    empty = pd.DataFrame(columns=list(psk.REPORT_COLUMNS))  # a window with no report at all
    blocks, tally = psk.report_labels(empty, cover, WINDOW)
    assert blocks["state"].tolist() == ["not_reported", "unknown"] and sum(tally.values()) == 0
    counts = pd.DataFrame({"bi": [0], "bj": [0], "time": [WINDOW[1]], "count": [1]})  # exactly at the end
    assert psk.report_labels(counts, cover, WINDOW)[0]["state"].tolist() == ["reported", "unknown"]
    for bad, message in ((pd.concat([counts, counts]), "aggregated"), (counts.assign(bi=["0"]), "integer"),
                         (counts.assign(bi=[0.0]), "integer"),
                         (counts.assign(count=pd.array([pd.NA], dtype="Int64")), "count")):
        with pytest.raises(ValueError, match=message):
            psk.report_labels(bad, cover, WINDOW)
    assert psk.check_report_counts(counts) is not None


# Codex review of PR 2: regressions
def test_depths_and_rain_must_be_numbers_never_strings():
    # A string column aggregates lexically: "1e-2" > "0.15", so a wet sensor would read dry.
    feed = pd.DataFrame({"sensor_id": "s", "time": [T0, T0 + pd.Timedelta(minutes=1)], "depth_m": ["0.15", "1e-2"]})
    with pytest.raises(ValueError, match="numbers"):
        psk.sensor_labels(feed, {"s": 2}, WINDOW)
    with pytest.raises(ValueError, match="numbers"):
        psk.window_tally(feed, "sensor_id", "depth_m", {"s": 2}, WINDOW)


def test_an_observation_without_a_time_is_refused_never_dropped():
    cover = pd.DataFrame({"bi": [0], "bj": [0], "cover": [0.5]})
    counts = pd.DataFrame({"bi": [0], "bj": [0], "time": pd.to_datetime([None]).tz_localize("Asia/Bangkok"),
                           "count": [1]})
    with pytest.raises(ValueError, match="time"):
        psk.report_labels(counts, cover, WINDOW)  # else the block would become a not_reported control
    feed = readings("s", [0.1] * 3).assign(time=lambda f: f["time"].where(f.index != 1))
    with pytest.raises(ValueError, match="time"):
        psk.sensor_labels(feed, {"s": 3}, WINDOW)


def test_a_positioned_sensor_without_a_label_keeps_its_block_from_being_dry():
    labels = pd.DataFrame({"sensor_id": ["a"], "state": ["observed_dry"]})
    sensors = pd.DataFrame({"sensor_id": ["a", "b"], "x": [10.0, 60.0], "y": [10.0, 60.0]})  # both in block (0, 0)
    blocks, counts = psk.block_sensor_labels(labels, sensors, (0.0, 0.0))
    assert blocks[["sensors", "state"]].values.tolist() == [[2, "unknown"]]
    assert counts["blocks_with_several_sensors"] == 1


def test_report_blocks_must_not_be_missing():
    cover = pd.DataFrame({"bi": [0], "bj": [0], "cover": [0.5]})
    for column in ("bi", "bj"):
        counts = pd.DataFrame({"bi": [0], "bj": [0], "time": [T0], "count": [1]})
        counts[column] = pd.array([pd.NA], dtype="Int64")
        with pytest.raises(ValueError, match="block"):
            psk.report_labels(counts, cover, WINDOW)
