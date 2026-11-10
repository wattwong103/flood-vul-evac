"""BKK-056b psk-v1 point-observation skill check: unit, labels and building cover.

The check scores flood surfaces against timed point observations (road-sensor depths and citizen
reports) on 100 m blocks: exact 2 x 2 groups of oec-v1's 50 m lattice points in EPSG:32647 (D1).
Labels follow D2 and North's choices of 10 November 2026 (docs/POINT_SKILL_PROTOCOL.md s3.2, s5).
It is a plausibility check with baselines, not calibration, and no observation ever reaches the
scenario builders. Tested on synthetic fixtures only: no real observation is read here.
"""

from __future__ import annotations

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
SENSOR_STATES = ("observed_wet", "observed_dry", "unknown")
REPORT_STATES = ("reported", "not_reported", "unknown")  # presence-only: never observed_dry
REPORT_COLUMNS = ("bi", "bj", "time", "count")  # s3.7: aggregated at ingest; no text, photo or id


def block_of(x: Any, y: Any, origin: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """The 100 m block holding each point. Block b spans lattice points 2b and 2b + 1 on each axis (oec-v1's i // 2)."""
    ox, oy = origin
    bi = np.floor((np.asarray(x, dtype=float) - ox + LATTICE_M / 2) / BLOCK_M).astype("int64")
    bj = np.floor((np.asarray(y, dtype=float) - oy + LATTICE_M / 2) / BLOCK_M).astype("int64")
    return bi, bj


def _check_schedule(scheduled: Mapping[str, Any]) -> None:
    for sensor, count in scheduled.items():
        if type(count) is not int or count < 1:
            raise ValueError(f"sensor {sensor!r} needs a schedule of at least one reading, not {count!r}")


def sensor_labels(readings: pd.DataFrame, scheduled: Mapping[str, int], window: tuple[Any, Any]) -> pd.DataFrame:
    """D2a and D2b for each scheduled sensor in one closed window [start, end].

    observed_wet: the window maximum of the reported depth is >= 0.15 m, whatever the share.
    observed_dry: at least 90% of the scheduled readings arrived, every one below 0.15 m.
    unknown: anything else. A gap (a reading missing or empty) never makes a sensor dry.
    """
    _check_schedule(scheduled)
    unscheduled = set(readings["sensor_id"]) - set(scheduled)
    if unscheduled:
        raise ValueError(f"sensors {sorted(unscheduled)} have readings but no schedule, which D2b counts against")
    start, end = window
    inside = readings[(readings["time"] >= start) & (readings["time"] <= end)]
    if inside.duplicated(["sensor_id", "time"]).any():
        raise ValueError("a sensor has duplicate readings at one time")
    reported = inside.dropna(subset=["depth_m"]).groupby("sensor_id")["depth_m"].agg(["size", "max"])
    rows = []
    for sensor, n_scheduled in sorted(scheduled.items()):
        n_reported = int(reported["size"].get(sensor, 0))
        peak = float(reported["max"].get(sensor, np.nan))
        if n_reported > n_scheduled:
            raise ValueError(f"sensor {sensor!r} has more readings than scheduled ({n_reported} > {n_scheduled})")
        complete = DRY_SHARE.denominator * n_reported >= DRY_SHARE.numerator * n_scheduled  # integers only
        state = "observed_wet" if peak >= WET_DEPTH_M else "observed_dry" if complete else "unknown"
        rows.append((sensor, n_scheduled, n_reported, peak, state))
    return pd.DataFrame(rows, columns=["sensor_id", "scheduled", "reported", "max_depth_m", "state"])


def block_sensor_labels(labels: pd.DataFrame, sensors: pd.DataFrame,
                        origin: tuple[float, float]) -> tuple[pd.DataFrame, dict[str, int]]:
    """North's Q1: a block is wet if any of its sensors is wet, dry only if every one is dry, else unknown.

    ``sensors`` gives each sensor's position (x, y) in EPSG:32647. The counts say how often a block held
    several sensors, and how often one was wet while another was dry.
    """
    if not set(labels["state"]) <= set(SENSOR_STATES):
        raise ValueError(f"sensor states must be among {SENSOR_STATES}")
    placed = labels.merge(sensors[["sensor_id", "x", "y"]], on="sensor_id", how="left", validate="one_to_one")
    if placed[["x", "y"]].isna().any(axis=None):
        raise ValueError("every labelled sensor needs a position (x, y) in EPSG:32647")
    bi, bj = block_of(placed["x"], placed["y"], origin)
    placed = placed.assign(bi=bi, bj=bj, wet=placed["state"] == "observed_wet", dry=placed["state"] == "observed_dry")
    blocks = placed.groupby(["bi", "bj"], as_index=False).agg(
        sensors=("sensor_id", "size"), wet=("wet", "any"), all_dry=("dry", "all"), any_dry=("dry", "any"))
    state = np.where(blocks["wet"], "observed_wet", np.where(blocks["all_dry"], "observed_dry", "unknown"))
    counts = {"blocks_with_several_sensors": int((blocks["sensors"] > 1).sum()),
              "blocks_with_wet_dry_conflict": int((blocks["wet"] & blocks["any_dry"]).sum())}
    return blocks.assign(state=state)[["bi", "bj", "sensors", "state"]], counts


def report_labels(counts: pd.DataFrame, cover: pd.DataFrame,
                  window: tuple[Any, Any]) -> tuple[pd.DataFrame, dict[str, int]]:
    """D2c with North's Q3: presence-only report labels on the blocks of the case's domain.

    ``counts`` holds report counts aggregated to blocks at ingest, with exactly the columns bi, bj, time
    and count, so no text, photo or report id can enter (s3.7). ``cover`` lists every in-domain block and
    its building cover. reported: at least one report in the closed window; not_reported: none. Both need
    cover above zero. Any other block is unknown, and a reported one is counted, never dropped silently.
    """
    if set(counts.columns) != set(REPORT_COLUMNS):
        raise ValueError(f"report counts must have exactly the columns {', '.join(REPORT_COLUMNS)}")
    if not pd.api.types.is_integer_dtype(counts["count"]) or (counts["count"] < 0).any():
        raise ValueError("report counts must be whole numbers, never negative")
    if not cover["cover"].between(0.0, 1.0).all():
        raise ValueError("building cover must be a share between 0 and 1")
    start, end = window
    inside = counts[(counts["time"] >= start) & (counts["time"] <= end)]
    per_block = inside.groupby(["bi", "bj"], as_index=False)["count"].sum()
    blocks = cover[["bi", "bj", "cover"]].merge(per_block, on=["bi", "bj"], how="left", validate="one_to_one")
    blocks = blocks.rename(columns={"count": "reports"}).assign(reports=lambda f: f["reports"].fillna(0).astype("int64"))
    covered, reported = blocks["cover"] > 0, blocks["reports"] > 0
    state = np.where(~covered, "unknown", np.where(reported, "reported", "not_reported"))
    beyond = per_block.merge(cover[["bi", "bj"]], on=["bi", "bj"], how="left", indicator=True)
    tally = {"reported_zero_cover": int((reported & ~covered).sum()),
             "reported_outside_domain": int(((beyond["_merge"] == "left_only") & (beyond["count"] > 0)).sum())}
    return blocks.assign(state=state)[["bi", "bj", "cover", "reports", "state"]], tally


def block_boxes(blocks: pd.DataFrame, origin: tuple[float, float]) -> np.ndarray:
    """Each block's 100 m square: the 50 m squares of its four lattice points."""
    ox, oy = origin
    x0 = ox - LATTICE_M / 2 + BLOCK_M * blocks["bi"].to_numpy(dtype=float)
    y0 = oy - LATTICE_M / 2 + BLOCK_M * blocks["bj"].to_numpy(dtype=float)
    return shapely.box(x0, y0, x0 + BLOCK_M, y0 + BLOCK_M)


def building_cover(buildings: gpd.GeoDataFrame, origin: tuple[float, float], blocks: pd.DataFrame) -> pd.DataFrame:
    """The share of each 100 m block covered by OSM building footprints: D3's exposure rung, D2c's pool.

    Footprints are projected to EPSG:32647 and repaired; overlaps count once (the union within each
    block); lines and points cover nothing. A layer without a CRS is refused, never assumed. The
    footprints are present-day, not event-time: oec-v1's assumption A7 applies to every result.
    """
    if buildings.crs is None:
        raise ValueError("the building layer has no CRS; it must be stated, never assumed")
    footprints = shapely.make_valid(buildings.to_crs(ANALYSIS_CRS).geometry.to_numpy())
    boxes = block_boxes(blocks, origin)
    hit, box_index = shapely.STRtree(boxes).query(footprints, predicate="intersects")
    pieces = shapely.intersection(footprints[hit], boxes[box_index])
    covered = np.zeros(len(boxes))
    for b in np.unique(box_index):
        covered[b] = shapely.area(shapely.union_all(pieces[box_index == b]))
    return blocks[["bi", "bj"]].reset_index(drop=True).assign(cover=np.minimum(covered / BLOCK_M**2, 1.0))
