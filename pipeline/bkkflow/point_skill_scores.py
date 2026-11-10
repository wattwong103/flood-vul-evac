"""BKK-056b psk-v1 block scores: candidate surfaces and the ladder's rung inputs, one value per 100 m block.

North's choices of 10 November 2026 (docs/POINT_SKILL_PROTOCOL.md s5):
- Q2: a block's score is the wettest of its four 50 m lattice points, the maximum of a depth or index, or
  the nearest for a distance. Points the surface evaluated but did not store tie at the bottom; a coarser
  surface gives each lattice point the value of its cell.
- Q4: the rain-only rung is inverse-distance weighting, power 2, over every admitted gauge with a complete
  accumulation: a locked number of hours before t for a timed surface, the event window for a declared one.
- Q5: the persistence rung reads the same kind of observation in the equal-length window before the
  scoring window.
D6 sets the windows. Every function reads a surface or an observation and returns values; none builds,
changes or feeds a surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd
import shapely
from shapely.geometry.base import BaseGeometry

from . import observed_extent as oe
from .point_skill import BLOCK_M, LATTICE_M, block_of, check_report_counts, window_tally

IDW_POWER = 2  # Q4b
BOTTOM = -np.inf  # the bottom tie of a score on which higher is wetter
_NODE_STATES = ("stored", "evaluated_below_storage", "not_evaluated")
_ON_GAUGE_M = 1e-6
_CHUNK = 4096  # block centres per IDW step, so a city run never holds a blocks x gauges matrix at once
_TOL = 1e-9


def block_scores(points: pd.DataFrame, *, higher_is_wetter: bool) -> pd.DataFrame:
    """Q2 on lattice points (i, j, aoi_frac, value): each block's wettest eligible point, and whether it is in the domain.

    A point is eligible when at least half its 50 m square lies in the AOI (oec-v1's MIN_EVALUABLE) and the
    surface gave it a value; NaN means never evaluated. A block is in the domain when the surface evaluated
    at least half its area inside the AOI, so an in-domain block always holds an eligible point.
    """
    evaluated = points["value"].notna()
    eligible = evaluated & (points["aoi_frac"] >= oe.MIN_EVALUABLE - _TOL)
    frame = points.assign(bi=points["i"] // oe.BLOCK_NODES, bj=points["j"] // oe.BLOCK_NODES,
                          rank=points["value"].where(eligible), area=points["aoi_frac"].where(evaluated, 0.0))
    blocks = frame.groupby(["bi", "bj"], as_index=False).agg(
        score=("rank", "max" if higher_is_wetter else "min"), area=("area", "sum"))
    in_domain = blocks["area"] >= oe.MIN_EVALUABLE * oe.BLOCK_NODES**2 - _TOL
    return blocks.assign(in_domain=in_domain)[["bi", "bj", "score", "in_domain"]]


def scenario_points(nodes: pd.DataFrame, field: str = "peak_depth_m") -> pd.DataFrame:
    """A declared scenario's lattice points from oec-v1's declared_nodes, valued for block_scores.

    A stored point carries its value; a point evaluated below storage ties at the bottom; a point never
    evaluated has none (NaN), so it can neither set a score nor count toward the domain.
    """
    if not set(nodes["state"]) <= set(_NODE_STATES):
        raise ValueError(f"lattice point states must come from declared_nodes: {_NODE_STATES}")
    value = np.select([nodes["state"] == "stored", nodes["state"] == "evaluated_below_storage"],
                      [nodes[field].to_numpy(dtype=float), BOTTOM], np.nan)
    return nodes[["i", "j", "x", "y", "aoi_frac"]].assign(value=value)


def cell_values(x: Any, y: Any, cells: pd.DataFrame, cell_m: float) -> np.ndarray:
    """Q2 for a surface coarser than 50 m: each point takes its cell's value; cells are half-open, NaN outside all."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("lattice points must have finite x and y")
    x0, y0 = cells["x_min"].min(), cells["y_min"].min()
    ci, cj = (cells["x_min"].to_numpy() - x0) / cell_m, (cells["y_min"].to_numpy() - y0) / cell_m
    ki, kj = np.rint(ci).astype("int64"), np.rint(cj).astype("int64")
    keys = list(zip(ki.tolist(), kj.tolist()))
    if not (np.allclose(ci, ki, rtol=0, atol=_TOL) and np.allclose(cj, kj, rtol=0, atol=_TOL)) or len(set(keys)) < len(keys):
        raise ValueError(f"cells must form one regular grid of {cell_m:g} m, each cell once")
    lookup = dict(zip(keys, cells["value"].to_numpy(dtype=float)))
    pi = np.floor((x - x0) / cell_m).astype("int64").tolist()
    pj = np.floor((y - y0) / cell_m).astype("int64").tolist()
    return np.array([lookup.get(key, np.nan) for key in zip(pi, pj)], dtype=float)


def channel_distance(points: pd.DataFrame, mask: BaseGeometry) -> np.ndarray:
    """The channel rung's input: each lattice point's distance in metres to oec-v1's channel mask.

    The mask is the union of MitrEarth water bodies and GSW permanent water, in EPSG:32647
    (observed_extent_stats PROTOCOL["masks"]); block_scores then keeps each block's nearest point.
    """
    if not isinstance(mask, BaseGeometry) or mask.is_empty:
        raise ValueError("the channel mask must be one non-empty geometry in EPSG:32647")
    return shapely.distance(shapely.points(points["x"].to_numpy(dtype=float), points["y"].to_numpy(dtype=float)), mask)


def scoring_window(candidate: Mapping[str, Any], event_window: tuple[Any, Any]) -> tuple[Any, Any]:
    """D6: a timed surface (issue time t, lead) is scored on the closed [t, t + lead]; a declared scenario on the event window."""
    timing = candidate.get("timing")
    if timing == "timed":
        if not candidate["lead"] > pd.Timedelta(0):
            raise ValueError("a timed surface needs a positive lead")
        return candidate["issue_time"], candidate["issue_time"] + candidate["lead"]
    if timing == "declared":
        start, end = event_window
        if not start < end:
            raise ValueError("the event window must open before it closes")
        return start, end
    raise ValueError(f"timing must be 'timed' or 'declared', not {timing!r}")


def prior_window(window: tuple[Any, Any]) -> tuple[Any, Any]:
    """Q5: the equal-length window just before a scoring window, read half-open [start - length, start)."""
    start, end = window
    return start - (end - start), start


def rain_window(candidate: Mapping[str, Any], event_window: tuple[Any, Any], hours_before: int) -> tuple[Any, Any]:
    """Q4: the rain-only accumulation: the closed [t - hours, t] for a timed surface, the event window for a declared one."""
    if type(hours_before) is not int or hours_before < 1:
        raise ValueError(f"the rain accumulation needs a whole number of hours, at least 1, not {hours_before!r}")
    start, end = scoring_window(candidate, event_window)
    if candidate.get("timing") == "timed":
        return start - pd.Timedelta(hours=hours_before), start
    return start, end


def gauge_totals(readings: pd.DataFrame, scheduled: Mapping[str, int], window: tuple[Any, Any]) -> pd.DataFrame:
    """Each scheduled gauge's rain over the closed window, complete only when every scheduled reading arrived (Q4b)."""
    if (readings["rain_mm"] < 0).any():
        raise ValueError("rain must never be negative")
    tally = window_tally(readings, "gauge_id", "rain_mm", scheduled, window)
    return pd.DataFrame({"gauge_id": tally["gauge_id"], "total_mm": tally["sum"].fillna(0.0),
                         "complete": tally["reported"] == tally["scheduled"]})


def idw_rain(blocks: pd.DataFrame, origin: tuple[float, float], gauges: pd.DataFrame, totals: pd.DataFrame) -> np.ndarray:
    """Q4b: each block centre's rain by inverse-distance weighting, power 2, over gauges with a complete accumulation.

    A gauge with any gap is left out, never read as zero; a centre on a gauge takes that gauge's value.
    With no complete gauge it raises, so the rung is null with that reason, never a guess.
    """
    used = totals[totals["complete"]].merge(gauges[["gauge_id", "x", "y"]], on="gauge_id", how="left",
                                            validate="one_to_one")
    if used.empty:
        raise ValueError("no admitted gauge has a complete accumulation in the window")
    if used[["x", "y"]].isna().any(axis=None):
        raise ValueError("every complete gauge needs a position (x, y) in EPSG:32647")
    gx, gy, rain = (used[column].to_numpy(dtype=float) for column in ("x", "y", "total_mm"))
    cx = origin[0] + BLOCK_M * blocks["bi"].to_numpy(dtype=float) + LATTICE_M / 2  # the 2 x 2 group's centre
    cy = origin[1] + BLOCK_M * blocks["bj"].to_numpy(dtype=float) + LATTICE_M / 2
    out = np.empty(len(cx))
    for first in range(0, len(cx), _CHUNK):
        part = slice(first, first + _CHUNK)
        distance = np.hypot(cx[part, None] - gx, cy[part, None] - gy)
        on = distance <= _ON_GAUGE_M
        with np.errstate(divide="ignore", invalid="ignore"):
            weight = np.where(on, 0.0, 1.0 / distance**IDW_POWER)
            value = (weight * rain).sum(axis=1) / weight.sum(axis=1)
            at = on.any(axis=1)
            value[at] = (on[at] * rain).sum(axis=1) / on[at].sum(axis=1)
        out[part] = value
    return out


def _aligned(blocks: pd.DataFrame, per_block: pd.Series, missing: float) -> np.ndarray:
    if per_block.empty:
        return np.full(len(blocks), missing, dtype=float)
    return per_block.reindex(pd.MultiIndex.from_frame(blocks[["bi", "bj"]]), fill_value=missing).to_numpy(dtype=float)


def sensor_persistence(readings: pd.DataFrame, sensors: pd.DataFrame, origin: tuple[float, float],
                       window: tuple[Any, Any], blocks: pd.DataFrame) -> np.ndarray:
    """Q5 for a sensor case: each block's maximum reported depth in the prior window; none ties at the bottom."""
    start, end = prior_window(window)
    prior = readings[(readings["time"] >= start) & (readings["time"] < end)].dropna(subset=["depth_m"])
    placed = prior.merge(sensors[["sensor_id", "x", "y"]], on="sensor_id", how="left", validate="many_to_one")
    if placed[["x", "y"]].isna().any(axis=None):
        raise ValueError("every sensor with a prior reading needs a position (x, y) in EPSG:32647")
    bi, bj = block_of(placed["x"], placed["y"], origin)
    return _aligned(blocks, placed.assign(bi=bi, bj=bj).groupby(["bi", "bj"])["depth_m"].max(), BOTTOM)


def report_persistence(counts: pd.DataFrame, window: tuple[Any, Any], blocks: pd.DataFrame) -> np.ndarray:
    """Q5 for a report case: each block's report count in the prior window; a block with none counts 0, the bottom."""
    counts = check_report_counts(counts)
    start, end = prior_window(window)
    prior = counts[(counts["time"] >= start) & (counts["time"] < end)]
    return _aligned(blocks, prior.groupby(["bi", "bj"])["count"].sum(), 0.0)
