"""BKK-053b observed-extent check statistics, fixed by the oec-v1 protocol record.

Primary (M2 under N2): ROC AUC on the declared block rank, Mann-Whitney with ties
counted 1/2, reported with the TOC curve and median distances, a toroidal-shift null,
and a spatial block bootstrap whose block length the observed mask's correlogram fixes
before the run. M1 at 0.15 m beside CSI_random is a labelled secondary row. A pilot
without both observed classes is undefined, never 0 or 0.5 (design note s5-s7).
Tested on synthetic fixtures only: the one locked real run happens on the paper side.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from . import observed_extent as oe

ROWS = {"primary": "min_stored_distance_m", "sensitivity:all_stored_points": "min_stored_distance_all_m"}
PILOT_AOIS = list(oe.PILOT_AOIS)
COMPARISON = "mitrearth-flood-gistda"
BEYOND_CORRIDOR = "beyond_storage_corridor"  # the bottom tie (rank inf), which strict JSON cannot hold
BLOCK_M = int(oe.LATTICE_M * oe.BLOCK_NODES)
RANGE_THRESHOLD = 0.05  # correlogram level taken as the practical correlation range
_WET, _NOT_MAPPED, _UNKNOWN = 1, 0, -1
_UNDEFINED = ("auc", "toc", "median_distance_m", "null", "interval", "secondary_at_0_15m")

PROTOCOL: dict[str, Any] = {
    "protocol_version": oe.PROTOCOL_VERSION,
    "statistic": {"primary": "M2 ROC AUC, Mann-Whitney, ties count 1/2", "nearer_ranks_wetter": True,
                  "report": ["toc", "median_distance_m"]},
    "secondary": {"metric": "M1 with CSI_random", "depth_m": oe.SECONDARY_DEPTH_M,
                  "declared_wet_rule": "at least half of a block's evaluable points at or above depth_m"},
    "null": {"method": "toroidal_shift", "shift": "whole blocks round the block grid's torus",
             "n": 999, "seed": 20261020,
             "p": "(1 + k) / (1 + n) over defined shifts, k with AUC >= observed; k / n kept as the share"},
    "interval": {"method": "block_bootstrap", "n": 999, "seed": 20261021, "ci": "percentile 95%",
                 "block_length_rule": f"first lag, in {BLOCK_M} m steps up to half the shorter grid side, "
                                      f"at which the observed-wet correlogram is <= {RANGE_THRESHOLD}"},
    "definition": {"min_observed_wet_blocks": 30, "min_not_mapped_blocks": 30},  # below either: undefined
    "unit": {"crs": oe.ANALYSIS_CRS, "block_m": BLOCK_M, "observed_wet_rule": oe.OBSERVED_WET_RULE,
             "min_evaluable": oe.MIN_EVALUABLE},
    "masks": {"channel": "union of mitrearth-water-body and gsw-permanent-water",
              "detectability": "none in the primary row; building cover >= 50% as a sensitivity row"},
    "rows": {"primary": ROWS["primary"], "sensitivity": [
        f"sensitivity:{name}" for name in ("all_stored_points", "recomputed_distance", "unit_50m", "observed_wet_gt_0",
                                           "observed_wet_ge_0.25", "detectability_building_cover_ge_0.5")]},
    "layers": {layer: list(years) for layer, years in oe.OBSERVED_YEARS.items()},  # D1 as amended, 20 Oct 2026
    "areas": list(PILOT_AOIS),
    "observed_input": {"sha256": None, "pinned_by": "BKK-053c"},
    "seen_by_authors": [{"layer": COMPARISON, "year": year, "aoi_ids": list(PILOT_AOIS)}
                        for year in oe.OBSERVED_YEARS[COMPARISON]],
    "reserved": [{"layer": COMPARISON, "year": 2011, "area": "outside the four pilot AOIs",
                  "for": "BKK-036C held-out validation", "use": "none: no statistic, figure or inspection"}],
    "cases": [],  # (aoi_id, layer, year, bootstrap block_m), set by lock_protocol before any overlap
}


def _metres(value: float) -> float | str:
    return float(value) if np.isfinite(value) else BEYOND_CORRIDOR


def _ratio(numerator: float, denominator: float) -> float | None:
    return float(numerator / denominator) if denominator else None


def _span(values: Any) -> list[float] | None:
    return [np.min(values).item(), np.max(values).item()] if len(values) else None


def _tally(distance: Any, wet: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Observed-wet and not-mapped block counts at each distinct rank distance, nearest first."""
    distance, wet = np.asarray(distance, dtype=float), np.asarray(wet, dtype=bool)
    if np.isnan(distance).any():
        raise ValueError("block ranks must be distances or inf (the bottom tie), never NaN")
    values, inverse = np.unique(distance, return_inverse=True)
    pos = np.bincount(inverse, weights=wet, minlength=len(values))
    return values, pos, np.bincount(inverse, minlength=len(values)) - pos


def auc(distance: Any, wet: Any) -> float | None:
    """P(an observed-wet block ranks nearer than a not-mapped one), ties 1/2: U / (n1 n0); None if a class is empty."""
    _, pos, neg = _tally(distance, wet)
    n1, n0 = pos.sum(), neg.sum()
    if not (n1 and n0):
        return None
    return float((pos * (n0 - np.cumsum(neg) + neg / 2)).sum() / (n1 * n0))


def toc(distance: Any, wet: Any) -> list[dict[str, Any]]:
    """TOC points after the origin: blocks flagged (rank <= threshold) and the hits among them."""
    values, pos, neg = _tally(distance, wet)
    return [{"threshold_m": _metres(v), "flagged": int(f), "hits": int(h)}
            for v, f, h in zip(values, np.cumsum(pos + neg), np.cumsum(pos))]


def contingency(declared: Any, observed: Any) -> dict[str, Any]:
    """M1 scores beside the random-allocation CSI; a zero denominator gives None, never 0."""
    d, o = np.asarray(declared, dtype=bool), np.asarray(observed, dtype=bool)
    a, b, c = int((d & o).sum()), int((d & ~o).sum()), int((~d & o).sum())
    p_d, p_o = float(d.mean()), float(o.mean())
    return {"H": _ratio(a, a + c), "FAR": _ratio(b, a + b), "CSI": _ratio(a, a + b + c),
            "CSI_random": _ratio(p_d * p_o, p_d + p_o - p_d * p_o), "bias": _ratio(a + b, a + c),
            "p_d": p_d, "p_o": p_o, "table": {"A": a, "B": b, "C": c, "D": len(d) - a - b - c}}


def declared_wet(blocks: pd.DataFrame) -> pd.Series:
    """M1's declared-wet blocks: at least half their evaluable points at or above 0.15 m (2 of 4 when full)."""
    return (blocks["evaluable_points"] > 0) & (2 * blocks["wet_points_0_15m"] >= blocks["evaluable_points"])


def _grid(blocks: pd.DataFrame, rank: str | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Dense block grid: labels (1 observed wet, 0 not mapped, -1 unknown or absent) and ranks (inf: bottom tie)."""
    bi, bj = (blocks[axis] - blocks[axis].min() for axis in ("bi", "bj"))
    label = np.full((bi.max() + 1, bj.max() + 1), _UNKNOWN)
    label[bi, bj] = np.select([blocks["state"] == "observed_wet", blocks["state"] == "not_mapped_as_flooded"],
                              [_WET, _NOT_MAPPED], _UNKNOWN)
    distance = np.full(label.shape, np.inf)
    if rank is not None:
        distance[bi, bj] = blocks[rank]
    return label, distance


def toroidal_null(blocks: pd.DataFrame, row: str, n: int, seed: int) -> dict[str, Any]:
    """N2: the AUC with the observed states shifted round the block grid's torus; declared ranks stay put.

    A block whose shifted source is unknown leaves that shift (unknown is never dry), so
    prevalence and the evaluable count vary between shifts; their range is kept.
    """
    label, distance = _grid(blocks, ROWS[row])
    keep = label != _UNKNOWN
    observed = auc(distance[keep], label[keep] == _WET)
    if observed is None:
        raise ValueError("the AUC is undefined in this domain, so there is nothing to test")
    nx, ny = label.shape
    picks = np.random.default_rng(seed).choice(nx * ny - 1, size=min(n, nx * ny - 1), replace=False) + 1
    shifted = []
    for shift in zip(*np.divmod(picks, ny)):
        moved = np.roll(label, shift, axis=(0, 1))
        both = keep & (moved != _UNKNOWN)
        value = auc(distance[both], moved[both] == _WET)
        if value is not None:
            shifted.append((value, float((moved[both] == _WET).mean()), int(both.sum())))
    values, prevalence, evaluable = (np.array(column) for column in zip(*shifted)) if shifted else ([], [], [])
    k = int(np.sum(values >= observed - 1e-12)) if shifted else 0
    return {"method": "toroidal_shift", "seed": seed, "n": len(picks), "n_undefined": len(picks) - len(shifted),
            "p_ge_observed": (1 + k) / (1 + len(shifted)) if shifted else None,
            "share_ge_observed": k / len(shifted) if shifted else None,
            "prevalence_range": _span(prevalence), "evaluable_range": _span(evaluable)}


def _tile_side(block_m: Any) -> int:
    if not (isinstance(block_m, int) and not isinstance(block_m, bool) and block_m > 0 and block_m % BLOCK_M == 0):
        raise ValueError(f"a bootstrap block length must be a positive multiple of {BLOCK_M} m, not {block_m!r}")
    return block_m // BLOCK_M


def block_bootstrap(blocks: pd.DataFrame, row: str, block_m: int, n: int, seed: int) -> dict[str, Any]:
    """N3: percentile 95% interval of the AUC, resampling square tiles of side block_m with replacement."""
    side = _tile_side(block_m)
    label, distance = _grid(blocks, ROWS[row])
    bi, bj = np.nonzero(label != _UNKNOWN)
    _, tile = np.unique((bi // side) * (label.shape[1] // side + 1) + bj // side, return_inverse=True)
    members = [np.flatnonzero(tile == t) for t in range(tile.max() + 1)]
    d, wet, rng = distance[bi, bj], label[bi, bj] == _WET, np.random.default_rng(seed)
    values = []
    for _ in range(n):
        pick = np.concatenate([members[t] for t in rng.integers(len(members), size=len(members))])
        values.append(auc(d[pick], wet[pick]))
    defined = [value for value in values if value is not None]
    return {"method": "block_bootstrap", "seed": seed, "block_m": block_m, "n_tiles": len(members), "n": n,
            "n_undefined": n - len(defined),
            "ci95": [float(q) for q in np.quantile(defined, [0.025, 0.975])] if defined else None}


def correlogram(blocks: pd.DataFrame) -> list[float | None]:
    """Observed-wet correlation between in-domain blocks h apart on either axis, h = 1 .. half the shorter side.

    Reads observed states and positions only, never a declared rank, so it may run at lock time.
    """
    label, _ = _grid(blocks)
    out: list[float | None] = []
    for h in range(1, min(label.shape) // 2 + 1):
        a = np.concatenate([label[:-h].ravel(), label[:, :-h].ravel()])
        b = np.concatenate([label[h:].ravel(), label[:, h:].ravel()])
        both = (a != _UNKNOWN) & (b != _UNKNOWN)
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.corrcoef(a[both], b[both])[0, 1] if both.sum() > 1 else np.nan
        out.append(float(r) if np.isfinite(r) else None)
    return out


def correlation_range_m(blocks: pd.DataFrame) -> int:
    """oec-v1's bootstrap block length: the first lag at which the correlogram is at or below 0.05."""
    for h, r in enumerate(correlogram(blocks), start=1):
        if r is not None and r <= RANGE_THRESHOLD:
            return h * BLOCK_M
    raise ValueError("the observed mask's correlation range is not reached within half the block grid; "
                     "North must set the block length")


def lock_protocol(block_lengths_m: Mapping[tuple[str, str, int], int | None]) -> dict[str, Any]:
    """oec-v1 with its cases, (aoi_id, layer, year) -> bootstrap block length, fixed before any overlap.

    Each length comes from correlation_range_m on the observed mask. None is allowed only for a
    case the minimum counts leave undefined; evaluate refuses it if the case turns out defined.
    """
    cases = []
    for (aoi_id, layer, year), block_m in sorted(block_lengths_m.items()):
        if aoi_id not in PROTOCOL["areas"] or type(year) is not int or year not in PROTOCOL["layers"].get(layer, []):
            raise ValueError(f"{aoi_id} {layer} {year} is not an {oe.PROTOCOL_VERSION} pilot layer-year")
        if block_m is not None:
            _tile_side(block_m)
        cases.append({"aoi_id": aoi_id, "layer": layer, "year": year, "block_m": block_m})
    return {**copy.deepcopy(PROTOCOL), "cases": cases}


def _status(n_wet: int, n_not_mapped: int, definition: Mapping[str, int]) -> str:
    if not n_wet + n_not_mapped:
        return "undefined_no_evaluable_blocks"
    for count, minimum, name in ((n_wet, definition["min_observed_wet_blocks"], "observed_positives"),
                                 (n_not_mapped, definition["min_not_mapped_blocks"], "not_mapped_blocks")):
        if count < max(minimum, 1):
            return f"undefined_{'too_few' if count else 'no'}_{name}"
    return "ok"


def evaluate(
    blocks: pd.DataFrame, protocol: Mapping[str, Any], case: tuple[str, str, int], row: str = "primary"
) -> dict[str, Any]:
    """The section 8 metrics for one locked case (aoi_id, layer, year) and one row."""
    if protocol.get("protocol_version") != oe.PROTOCOL_VERSION or row not in ROWS:
        raise ValueError(f"metrics need the {oe.PROTOCOL_VERSION} protocol and one of the rows {sorted(ROWS)}")
    locked = {(c["aoi_id"], c["layer"], c["year"]): c["block_m"] for c in protocol["cases"]}
    if tuple(case) not in locked:
        raise ValueError(f"{case} is not a locked {oe.PROTOCOL_VERSION} case; lock before any overlap")
    if not set(blocks["state"]) <= {"observed_wet", "not_mapped_as_flooded", "unknown"}:
        raise ValueError("block states must come from block_table")
    domain = blocks[blocks["state"] != "unknown"]
    wet = (domain["state"] == "observed_wet").to_numpy()
    status = _status(int(wet.sum()), int((~wet).sum()), protocol["definition"])
    result: dict[str, Any] = {"status": status, "row": row, **dict.fromkeys(_UNDEFINED)}
    if status != "ok":
        return result
    block_m = locked[tuple(case)]
    if block_m is None:
        raise ValueError(f"the bootstrap block length for {case} is not locked in the protocol")
    distance, null = domain[ROWS[row]].to_numpy(dtype=float), protocol["null"]
    return {**result, "auc": auc(distance, wet), "toc": toc(distance, wet),
            "median_distance_m": {"observed_wet": _metres(np.median(distance[wet])),
                                  "not_mapped": _metres(np.median(distance[~wet]))},
            "null": toroidal_null(blocks, row, null["n"], null["seed"]),
            "interval": block_bootstrap(blocks, row, block_m, protocol["interval"]["n"], protocol["interval"]["seed"]),
            "secondary_at_0_15m": contingency(declared_wet(domain), wet)}
