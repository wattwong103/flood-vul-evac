"""BKK-056b psk-v1 point-observation skill check: unit, labels and building cover.

The check scores flood surfaces against timed point observations (road-sensor depths and citizen
reports) on 100 m blocks: exact 2 x 2 groups of oec-v1's 50 m lattice points in EPSG:32647 (D1).
Labels follow D2 and North's choices of 10 November 2026 (docs/POINT_SKILL_PROTOCOL.md s3.2, s5).
It is a plausibility check with baselines, not calibration, and no observation ever reaches the
scenario builders. Tested on synthetic fixtures only: no real observation is read here.
"""

from __future__ import annotations

import numbers
from collections.abc import Mapping
from fractions import Fraction
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from . import observed_extent as oe

CHECK_ID = "point-observation-skill"
PROTOCOL_VERSION = "psk-v1"
ANALYSIS_CRS = oe.ANALYSIS_CRS
LATTICE_M = oe.LATTICE_M
BLOCK_M = int(oe.LATTICE_M * oe.BLOCK_NODES)
WET_DEPTH_M = oe.SECONDARY_DEPTH_M  # D2a: oec-v1's 0.15 m, also the API's FLOOD_AREA_THRESHOLD_M
DRY_SHARE = Fraction(9, 10)  # D2b: the share of scheduled readings, compared exactly
MIN_COVER_M2 = 1.0  # North, 10 Nov 2026: less footprint than this in a block is no cover (reprojection slivers)
SENSOR_STATES = ("observed_wet", "observed_dry", "unknown")
REPORT_STATES = ("reported", "not_reported", "unknown")  # presence-only: never observed_dry
REPORT_COLUMNS = ("bi", "bj", "time", "count")  # s3.7: aggregated at ingest; no text, photo or id


def block_of(x: Any, y: Any, origin: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """The 100 m block holding each point. Block b spans lattice points 2b and 2b + 1 on each axis (oec-v1's i // 2)."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("positions must have finite x and y in EPSG:32647")
    bi = np.floor((x - origin[0] + LATTICE_M / 2) / BLOCK_M).astype("int64")
    bj = np.floor((y - origin[1] + LATTICE_M / 2) / BLOCK_M).astype("int64")
    return bi, bj


def _in_window(frame: pd.DataFrame, window: tuple[Any, Any]) -> pd.DataFrame:
    """The rows whose time lies in the closed window, once the window itself is checked."""
    start, end = window
    if not start < end:
        raise ValueError(f"a window must open before it closes, not {start} to {end}")
    if frame["time"].isna().any():
        raise ValueError("every observation needs a time; one without it is never dropped silently")
    if pd.api.types.is_datetime64_any_dtype(frame["time"]):
        aware = isinstance(frame["time"].dtype, pd.DatetimeTZDtype)
        if aware != (getattr(start, "tzinfo", None) is not None) or aware != (getattr(end, "tzinfo", None) is not None):
            raise ValueError("the window and the observations must both carry a time zone, or neither")
    return frame[(frame["time"] >= start) & (frame["time"] <= end)]


def _schedule(scheduled: Mapping[str, Any]) -> dict[str, int]:
    checked = {}
    for name, count in scheduled.items():
        if isinstance(count, (bool, np.bool_)) or not isinstance(count, numbers.Integral) or count < 1:
            raise ValueError(f"{name!r} needs a schedule of at least one reading, not {count!r}")
        checked[name] = int(count)
    return checked


def _numbers(readings: pd.DataFrame, value: str) -> None:
    column = readings[value]
    if len(column) and (not pd.api.types.is_numeric_dtype(column) or pd.api.types.is_bool_dtype(column)):
        raise ValueError(f"{value} must hold numbers, not {column.dtype}: text would aggregate lexically")


def window_tally(readings: pd.DataFrame, key: str, value: str, scheduled: Mapping[str, int],
                 window: tuple[Any, Any]) -> pd.DataFrame:
    """For each scheduled id, the readings that arrived in the closed window: their count, maximum and sum.

    A reading that is missing or empty (NaN) is a gap. A reading without an id, a time or a schedule, two
    at one time, more than scheduled, or a value that is not a number is refused: a feed that breaks its
    schedule is never guessed at.
    """
    _numbers(readings, value)
    schedule = _schedule(scheduled)
    if readings[key].isna().any():
        raise ValueError(f"every reading needs a {key}")
    unscheduled = set(readings[key]) - set(schedule)
    if unscheduled:
        raise ValueError(f"{key} {sorted(map(str, unscheduled))} have readings but no schedule, which D2b counts against")
    inside = _in_window(readings, window)
    if inside.duplicated([key, "time"]).any():
        raise ValueError(f"a {key} has duplicate readings at one time")
    arrived = inside.dropna(subset=[value]).groupby(key)[value].agg(["size", "max", "sum"])
    rows = []
    for name, n_scheduled in sorted(schedule.items()):
        n_reported = int(arrived["size"].get(name, 0))
        if n_reported > n_scheduled:
            raise ValueError(f"{key} {name!r} has more readings than scheduled ({n_reported} > {n_scheduled})")
        rows.append((name, n_scheduled, n_reported, float(arrived["max"].get(name, np.nan)),
                     float(arrived["sum"].get(name, np.nan))))
    return pd.DataFrame(rows, columns=[key, "scheduled", "reported", "max", "sum"])


def sensor_labels(readings: pd.DataFrame, scheduled: Mapping[str, int], window: tuple[Any, Any]) -> pd.DataFrame:
    """D2a and D2b for each scheduled sensor in one closed window [start, end].

    observed_wet: the window maximum of the reported depth is >= 0.15 m, whatever the share.
    observed_dry: at least 90% of the scheduled readings arrived, every one below 0.15 m.
    unknown: anything else. A gap (a reading missing or empty) never makes a sensor dry. A negative or
    infinite depth is refused: ingest (BKK-056c) maps any sentinel to a gap, and the harness never guesses.
    """
    _numbers(readings, "depth_m")
    depth = readings["depth_m"].to_numpy(dtype=float)
    if np.isinf(depth).any() or (depth[~np.isnan(depth)] < 0).any():
        raise ValueError("a depth must be a finite reading of at least 0 m, or NaN for a gap")
    tally = window_tally(readings, "sensor_id", "depth_m", scheduled, window)
    complete = DRY_SHARE.denominator * tally["reported"] >= DRY_SHARE.numerator * tally["scheduled"]  # integers
    state = np.where(tally["max"] >= WET_DEPTH_M, "observed_wet", np.where(complete, "observed_dry", "unknown"))
    return pd.DataFrame({"sensor_id": tally["sensor_id"], "scheduled": tally["scheduled"],
                         "reported": tally["reported"], "max_depth_m": tally["max"], "state": state})


def block_sensor_labels(labels: pd.DataFrame, sensors: pd.DataFrame,
                        origin: tuple[float, float]) -> tuple[pd.DataFrame, dict[str, int]]:
    """North's Q1: a block is wet if any of its sensors is wet, dry only if every one is dry, else unknown.

    ``sensors`` gives each sensor's position (x, y) in EPSG:32647. A positioned sensor without a label is
    unknown, so it keeps its block from being dry. The counts say how often a block held several sensors,
    and how often one was wet while another was dry.
    """
    if not set(labels["state"]) <= set(SENSOR_STATES):
        raise ValueError(f"sensor states must be among {SENSOR_STATES}")
    placed = sensors[["sensor_id", "x", "y"]].merge(labels[["sensor_id", "state"]], on="sensor_id", how="outer",
                                                    validate="one_to_one")
    if placed[["x", "y"]].isna().any(axis=None):
        raise ValueError("every labelled sensor needs a position (x, y) in EPSG:32647")
    placed["state"] = placed["state"].fillna("unknown")
    bi, bj = block_of(placed["x"], placed["y"], origin)
    placed = placed.assign(bi=bi, bj=bj, wet=placed["state"] == "observed_wet", dry=placed["state"] == "observed_dry")
    blocks = placed.groupby(["bi", "bj"], as_index=False).agg(
        sensors=("sensor_id", "size"), wet=("wet", "any"), all_dry=("dry", "all"), any_dry=("dry", "any"))
    state = np.where(blocks["wet"], "observed_wet", np.where(blocks["all_dry"], "observed_dry", "unknown"))
    counts = {"blocks_with_several_sensors": int((blocks["sensors"] > 1).sum()),
              "blocks_with_wet_dry_conflict": int((blocks["wet"] & blocks["any_dry"]).sum())}
    return blocks.assign(state=state)[["bi", "bj", "sensors", "state"]], counts


def check_report_counts(counts: pd.DataFrame) -> pd.DataFrame:
    """Report counts as aggregated at ingest (s3.7): exactly bi, bj, time and count, one row per block and time.

    No text, photo or report id can enter, and a row per report cannot pass as an aggregate. Ingest
    (BKK-056c) sets the time grain. An empty table is a window with no report.
    """
    if set(counts.columns) != set(REPORT_COLUMNS):
        raise ValueError(f"report counts must have exactly the columns {', '.join(REPORT_COLUMNS)}")
    if counts.empty:
        return counts.astype({"bi": "int64", "bj": "int64", "count": "int64"})
    if counts[["bi", "bj"]].isna().any(axis=None):
        raise ValueError("every report count needs its block (bi, bj)")
    if counts["time"].isna().any():
        raise ValueError("every report count needs a time; one without it is never dropped silently")
    if not (pd.api.types.is_integer_dtype(counts["bi"]) and pd.api.types.is_integer_dtype(counts["bj"])):
        raise ValueError("bi and bj must be integer block indices")
    if counts["count"].isna().any() or not pd.api.types.is_integer_dtype(counts["count"]) or (counts["count"] < 0).any():
        raise ValueError("report counts must be whole numbers, never negative or missing")
    if counts.duplicated(["bi", "bj", "time"]).any():
        raise ValueError("report counts must be aggregated: one row per block and time")
    return counts


def report_labels(counts: pd.DataFrame, cover: pd.DataFrame,
                  window: tuple[Any, Any]) -> tuple[pd.DataFrame, dict[str, int]]:
    """D2c with North's Q3: presence-only report labels on the blocks of the case's domain.

    ``cover`` lists every in-domain block and its building cover. reported: at least one report in the
    closed window; not_reported: none. Both need cover at or above the 1 m2 floor. Any other block is
    unknown, and the blocks whose reports fall outside the classes are counted, never dropped silently.
    """
    counts = check_report_counts(counts)
    if not cover["cover"].between(0.0, 1.0).all():
        raise ValueError("building cover must be a share between 0 and 1")
    per_block = _in_window(counts, window).groupby(["bi", "bj"], as_index=False)["count"].sum()
    blocks = cover[["bi", "bj", "cover"]].merge(per_block, on=["bi", "bj"], how="left", validate="one_to_one")
    blocks = blocks.rename(columns={"count": "reports"}).assign(reports=lambda f: f["reports"].fillna(0).astype("int64"))
    covered, reported = blocks["cover"] >= MIN_COVER_M2 / BLOCK_M**2, blocks["reports"] > 0
    state = np.where(~covered, "unknown", np.where(reported, "reported", "not_reported"))
    beyond = per_block.merge(cover[["bi", "bj"]], on=["bi", "bj"], how="left", indicator=True)
    tally = {"reported_zero_cover_blocks": int((reported & ~covered).sum()),
             "reported_outside_domain_blocks": int(((beyond["_merge"] == "left_only") & (beyond["count"] > 0)).sum())}
    return blocks.assign(state=state)[["bi", "bj", "cover", "reports", "state"]], tally


def block_boxes(blocks: pd.DataFrame, origin: tuple[float, float]) -> np.ndarray:
    """Each block's 100 m square: the 50 m squares of its four lattice points."""
    x0 = origin[0] - LATTICE_M / 2 + BLOCK_M * blocks["bi"].to_numpy(dtype=float)
    y0 = origin[1] - LATTICE_M / 2 + BLOCK_M * blocks["bj"].to_numpy(dtype=float)
    return shapely.box(x0, y0, x0 + BLOCK_M, y0 + BLOCK_M)


def _footprints(buildings: gpd.GeoDataFrame) -> np.ndarray:
    if buildings.crs is None:
        raise ValueError("the building layer has no CRS; it must be stated, never assumed")
    geometry = buildings.to_crs(ANALYSIS_CRS).geometry.to_numpy()
    geometry = geometry[~(shapely.is_missing(geometry) | shapely.is_empty(geometry))]
    if not np.isfinite(shapely.get_coordinates(geometry)).all():  # bounds skip a NaN vertex; GEOS then fails
        raise ValueError("every footprint must have finite coordinates")
    return shapely.make_valid(geometry)


def building_cover(buildings: gpd.GeoDataFrame, origin: tuple[float, float], blocks: pd.DataFrame) -> pd.DataFrame:
    """The share of each 100 m block covered by OSM building footprints: D3's exposure rung, D2c's pool.

    Footprints are projected to EPSG:32647 and repaired; overlaps count once (the union within each
    block); lines, points, missing and empty geometries cover nothing; less than 1 m2 in a block is no
    cover. A layer without a CRS is refused, never assumed. The footprints are present-day, not
    event-time: oec-v1's assumption A7 applies to every result.
    """
    if blocks.duplicated(["bi", "bj"]).any():
        raise ValueError("each block must be listed once")
    footprints, boxes = _footprints(buildings), block_boxes(blocks, origin)
    hit, box_index = shapely.STRtree(boxes).query(footprints, predicate="intersects")
    order = np.argsort(box_index, kind="stable")  # one sort, then contiguous runs: linear in the pairs
    hit, box_index = hit[order], box_index[order]
    pieces = shapely.intersection(footprints[hit], boxes[box_index])
    ids, starts, sizes = np.unique(box_index, return_index=True, return_counts=True)
    area = np.zeros(len(boxes))
    single = sizes == 1
    area[ids[single]] = shapely.area(pieces[starts[single]])
    for block, first, size in zip(ids[~single], starts[~single], sizes[~single]):
        area[block] = shapely.area(shapely.union_all(pieces[first:first + size]))
    area = np.where(area >= MIN_COVER_M2, area, 0.0)
    return blocks[["bi", "bj"]].reset_index(drop=True).assign(cover=np.minimum(area / BLOCK_M**2, 1.0))
