"""BKK-053 observed-extent plausibility check: declared lattice, 100 m blocks, domains, record.

Extent only: the declared surface is a ranking by stored distance to waterway
centrelines, never depth, and observed extent never feeds the scenario builders.
Unknown is never dry. No declared-versus-observed statistic is computed here; that
is BKK-053b, after the oec-v1 protocol lock (bkkflow observed-extent design note, s7, s11).
"""

from __future__ import annotations

import math
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry.base import BaseGeometry

from .sources import gsw

CHECK_ID = "observed-extent-plausibility"
PROTOCOL_VERSION = "oec-v1"
RELEASE_ID = "bkkflow-four-area-2026-10-11"
ANALYSIS_CRS = "EPSG:32647"
LATTICE_M = 50.0
BLOCK_NODES = 2  # a 100 m block is an exact 2 x 2 group of lattice points (D4, R2)
STORAGE_FLOOR_M = 0.01  # the scenario stores only points deeper than this
OBSERVED_WET_RULE = 0.5  # observed-wet share of a block's evaluable area (D4)
MIN_EVALUABLE = 0.5  # share of a block evaluable on both sides to enter the domain (D4)
_LATTICE_TOL_M = 1e-3
_TOL = 1e-9
_FRACTIONS = ["observed_wet_frac", "channel_frac"]

LAYERS: dict[str, dict[str, str]] = {
    "mitrearth-flood-gistda": {
        "source_id": "mitrearth-provincial-geohazard-bangkok", "layer": "Flood GISTDA 0519",
        "use": "comparison", "source_role": "mapped", "feature_type": "unrecorded"},
    "mitrearth-water-body": {
        "source_id": "mitrearth-provincial-geohazard-bangkok", "layer": "water body",
        "use": "channel_mask", "source_role": "mapped", "feature_type": "water_body"},
    "gsw-permanent-water": {
        "source_id": gsw.SOURCE_ID, "layer": "waterClass 3",
        "use": "channel_mask", "source_role": "observed", "feature_type": "permanent_water"},
}  # channel_frac is the union of every channel_mask layer (D5)

ASSUMPTIONS = {
    "A1": "The 2006 mapping covered each pilot in full, so absence means not mapped as flooded (unverified).",
    "A2": "MitrEarth polygons are positionally faithful to the GISTDA source at about 100 m (accuracy unknown).",
    "A3": "The 2006 polygons represent inundation, not standing water (feature type unrecorded).",
    "A4": "2026 OSM waterway centrelines approximate the 2006 waterways in the pilots (unverified).",
    "A5": "The stage bundle's osm/water.parquet is the file each run read (the runner must hash-check it).",
    "A6": "Only waterways touching the AOI count, as in the declared surface (true by construction).",
    "A7": "The detectability proxy uses present-day buildings (sensitivity row only).",
}

LABELS: dict[str, Any] = {
    "measures": "extent_only", "depth_compared": False, "timing_compared": False,
    "is_validation": False, "is_calibration": False, "is_evacuation_simulation": False,
    "interpretation": "spatial-pattern plausibility of a declared scenario; not depth, timing or prediction",
}


def _require_role(frame: pd.DataFrame, allowed: str, side: str) -> None:
    if frame.empty:
        raise ValueError(f"{side} frame has no rows (a dry run has no declared extent)")
    roles = set(frame["source_role"].unique()) if "source_role" in frame.columns else set()
    if roles != {allowed}:
        raise ValueError(f"{side} frame has source_role {sorted(roles)}; expected only {allowed!r}")


def _comparison_spec(layer: str) -> dict[str, str]:
    spec = LAYERS[layer]
    if spec["use"] != "comparison":
        raise ValueError(f"{layer} is a {spec['use']} layer, not a comparison layer")
    return spec


def _drift(values: Any, offset: float, spacing: float) -> np.ndarray:
    return (np.asarray(values, dtype=float) - offset + spacing / 2) % spacing - spacing / 2


def recover_lattice(x: Any, y: Any, spacing: float = LATTICE_M) -> tuple[float, float]:
    """The (x, y) offset modulo ``spacing`` that every stored point shares, after checking the spacing.

    The manifest does not record the lattice origin, so it is read back from the
    stored points. The declared side is never re-gridded to a new origin. A coarser
    run also shares one offset modulo 50 m, so the spacing is checked separately:
    otherwise its never-evaluated midpoints would read as evaluated and low. A run
    whose stored points are never adjacent cannot show its spacing and is refused;
    its corridor would be narrower than one cell (every preset's is at least 306 m).
    """
    xs, ys = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if xs.size == 0 or not (np.isfinite(xs).all() and np.isfinite(ys).all()):
        raise ValueError("the declared lattice needs stored points with finite x and y")
    origin = []
    for values in (xs, ys):
        offset = float(values[0]) % spacing
        if spacing - offset <= _LATTICE_TOL_M:
            offset -= spacing  # 49.9999 and 0 are one offset; keep block parity stable, unrounded
        if not np.abs(_drift(values, offset, spacing)).max() <= _LATTICE_TOL_M:
            raise ValueError("stored points do not share one lattice offset")
        origin.append(offset)
    gaps = np.concatenate([np.diff(np.unique(np.round(values, 3))) for values in (xs, ys)])
    if not (gaps.size and abs(gaps.min() - spacing) <= _LATTICE_TOL_M):
        raise ValueError(f"stored points do not show a {spacing:g} m lattice spacing")
    return origin[0], origin[1]


def _lattice_box(water: gpd.GeoDataFrame, aoi_geometry: Any) -> tuple[float, float, float, float]:
    """The box the scenario evaluated: whole water features touching the AOI, bounds cut to the AOI's."""
    projected = water.to_crs(ANALYSIS_CRS)  # as the scenario does; a CRS-less layer raises
    kept = projected[projected.geometry.intersects(aoi_geometry)]
    if kept.empty:
        raise ValueError("no water feature intersects the area of interest")
    wx0, wy0, wx1, wy1 = kept.geometry.union_all().bounds
    ax0, ay0, ax1, ay1 = aoi_geometry.bounds
    return max(wx0, ax0), max(wy0, ay0), min(wx1, ax1), min(wy1, ay1)


def _index_span(low: float, high: float, box_lo: int, box_n: int, spacing: float) -> np.ndarray:
    """Lattice indices covering offsets [low, high] and the box, with a spare index each side for float noise."""
    first = min(math.floor(low / spacing), box_lo)
    return np.arange(first, max(math.ceil(high / spacing), box_lo + box_n - 1) + 1, dtype="int64")


def _axis(index: np.ndarray, box_lo: int, exact: np.ndarray, spacing: float) -> np.ndarray:
    """Coordinates along one axis: the scenario's own arange values inside its box, extended outside it."""
    k = np.asarray(index) - box_lo
    within = (k >= 0) & (k < len(exact))
    return np.where(within, exact[np.clip(k, 0, len(exact) - 1)], exact[0] + k * spacing)


def declared_nodes(
    slices: pd.DataFrame, water: gpd.GeoDataFrame, aoi_geometry: BaseGeometry, spacing: float = LATTICE_M
) -> tuple[pd.DataFrame, tuple[float, float]]:
    """Every lattice point inside the AOI, with its declared state, and the lattice offset.

    ``stored`` points carry their exact stored distance. ``evaluated_below_storage``
    points lie inside the evaluated box but were not stored. ``not_evaluated``
    points lie outside the box: unknown on the declared side, never declared dry.
    ``aoi_frac`` is the share of each point's 50 m square inside the AOI. ``peak_depth_m``
    is kept only for BKK-053b's 0.15 m secondary row; ranks use distance.
    """
    if not isinstance(aoi_geometry, BaseGeometry):
        raise TypeError(f"aoi_geometry must be one shapely geometry in {ANALYSIS_CRS}")
    _require_role(slices, "scenario", "declared")
    stored = slices.drop_duplicates(["x", "y"])
    ox, oy = recover_lattice(stored["x"], stored["y"], spacing)
    if not np.isfinite(stored["distance_to_water_m"].to_numpy(dtype=float)).all():
        raise ValueError("every stored point must carry a finite distance_to_water_m")
    if (shapely.distance(aoi_geometry, shapely.points(stored["x"], stored["y"])) > _LATTICE_TOL_M).any():
        raise ValueError("stored points lie outside the area of interest; is this the run's AOI?")
    x0, y0, x1, y1 = _lattice_box(water, aoi_geometry)
    if np.abs(_drift([x0 - ox, y0 - oy], 0.0, spacing)).max() > _LATTICE_TOL_M:
        raise ValueError("the water layer's evaluated box is off the stored lattice (A5)")
    # The scenario evaluated exactly np.arange(min, max + spacing, spacing) on each axis. Reuse
    # those values, so AOI boundary tests here agree with the scenario's bit for bit.
    xs_box, ys_box = np.arange(x0, x1 + spacing, spacing), np.arange(y0, y1 + spacing, spacing)
    i_lo, j_lo = round((x0 - ox) / spacing), round((y0 - oy) / spacing)
    i_hi, j_hi = i_lo + len(xs_box) - 1, j_lo + len(ys_box) - 1
    ax0, ay0, ax1, ay1 = aoi_geometry.bounds
    gi, gj = (grid.ravel() for grid in np.meshgrid(
        _index_span(ax0 - ox, ax1 - ox, i_lo, len(xs_box), spacing),
        _index_span(ay0 - oy, ay1 - oy, j_lo, len(ys_box), spacing)))
    inside = shapely.intersects_xy(
        aoi_geometry, _axis(gi, i_lo, xs_box, spacing), _axis(gj, j_lo, ys_box, spacing))
    stored_ij = pd.DataFrame({
        "i": np.rint((stored["x"].to_numpy() - ox) / spacing).astype("int64"),
        "j": np.rint((stored["y"].to_numpy() - oy) / spacing).astype("int64"),
        "distance_to_water_m": stored["distance_to_water_m"].to_numpy(dtype=float),
        "peak_depth_m": stored["peak_depth_m"].to_numpy(dtype=float),
    })
    # A stored point is inside the AOI (checked above), even if a boundary test here rounds it out.
    nodes = pd.DataFrame({"i": gi[inside], "j": gj[inside]}).merge(
        stored_ij, on=["i", "j"], how="outer", validate="one_to_one", indicator=True)
    in_box = nodes["i"].between(i_lo, i_hi) & nodes["j"].between(j_lo, j_hi)
    is_stored = nodes.pop("_merge") != "left_only"
    if (is_stored & ~in_box).any():
        raise ValueError("stored points lie outside the evaluated box (A5)")
    x, y = _axis(nodes["i"], i_lo, xs_box, spacing), _axis(nodes["j"], j_lo, ys_box, spacing)
    squares = shapely.box(x - spacing / 2, y - spacing / 2, x + spacing / 2, y + spacing / 2)
    nodes = nodes.assign(
        x=x, y=y, aoi_frac=shapely.area(shapely.intersection(squares, aoi_geometry)) / spacing**2,
        state=np.where(is_stored, "stored", np.where(in_box, "evaluated_below_storage", "not_evaluated")),
    )
    return nodes.sort_values(["j", "i"]).reset_index(drop=True), (ox, oy)


def declared_coverage(nodes: pd.DataFrame) -> dict[str, Any]:
    """The box-coverage check: how much of the AOI lattice the scenario never evaluated."""
    total = len(nodes)
    missing = int((nodes["state"] == "not_evaluated").sum())
    return {"aoi_points": total, "not_evaluated": missing,
            "not_evaluated_share": missing / total if total else None}


def gsw_channel(codes: Any) -> np.ndarray:
    """GSW yearly waterClass as channel evidence: only class 3 (permanent water) masks.

    JRC labels code 0 "no observations", though it mostly holds never-water land
    (BKK-054). Either way it is not channel evidence, and GSW never supplies a
    not-mapped state: it is a mask layer only (D1, D5).
    """
    codes = np.asarray(codes)
    gsw.is_water(codes)  # rejects any code outside the documented 0-3
    return codes == gsw.CODE_PERMANENT


def block_table(nodes: pd.DataFrame, observed: pd.DataFrame, layer: str) -> pd.DataFrame:
    """Group lattice points into 100 m blocks and give each block its observed-side state.

    ``observed`` holds, per lattice point (i, j), the share of its 50 m square that lies
    in the AOI and the comparison layer outside the channel mask (``observed_wet_frac``),
    and in the AOI and the union channel mask (``channel_frac``). Areas are true areas:
    a square's AOI share comes from ``aoi_frac``, and AOI slivers of squares centred
    outside the AOI were never stored, so they count as outside. A block's declared rank
    is its minimum stored distance; blocks with no stored point tie at the bottom (``inf``).
    Blocks below the evaluable rule are ``unknown``, with the reason that removed most
    area (ties go outside_aoi, then not_evaluated, then channel).
    """
    spec = _comparison_spec(layer)
    _require_role(observed, spec["source_role"], "observed")
    frame = nodes.merge(observed[["i", "j", *_FRACTIONS]], on=["i", "j"], how="left", validate="one_to_one")
    evaluated = frame["state"] != "not_evaluated"
    if frame.loc[evaluated, _FRACTIONS].isna().any(axis=None):
        raise ValueError("observed fractions are missing for evaluated points; unknown is never dry")
    wet = frame["observed_wet_frac"].where(evaluated, 0.0)
    channel = frame["channel_frac"].where(evaluated, 0.0)
    if ((wet < -_TOL) | (channel < -_TOL) | (wet + channel > frame["aoi_frac"] + _TOL)).any():
        raise ValueError("observed fractions must be disjoint shares of each square's AOI part")
    frame = frame.assign(
        bi=frame["i"] // BLOCK_NODES, bj=frame["j"] // BLOCK_NODES, wet=wet, channel=channel,
        open=(frame["aoi_frac"] - channel).where(evaluated, 0.0),
        not_evaluated=frame["aoi_frac"].where(~evaluated, 0.0),
    )
    blocks = frame.groupby(["bi", "bj"], as_index=False).agg(
        points=("i", "size"), in_aoi=("aoi_frac", "sum"), open=("open", "sum"), wet=("wet", "sum"),
        channel=("channel", "sum"), not_evaluated=("not_evaluated", "sum"),
        min_stored_distance_m=("distance_to_water_m", "min"),
    )
    cells = BLOCK_NODES ** 2
    in_domain = blocks["open"] >= MIN_EVALUABLE * cells - _TOL
    wet_share = blocks["wet"] / blocks["open"].where(blocks["open"] > 0)
    removed = pd.DataFrame({"outside_aoi": cells - blocks["in_aoi"],
                            "not_evaluated": blocks["not_evaluated"], "channel": blocks["channel"]})
    observed_state = np.where(wet_share >= OBSERVED_WET_RULE - _TOL, "observed_wet", "not_mapped_as_flooded")
    return blocks.assign(
        evaluable_share=blocks["open"] / cells,
        bottom_tie=blocks["min_stored_distance_m"].isna(),
        min_stored_distance_m=blocks["min_stored_distance_m"].fillna(np.inf),
        state=np.where(in_domain, observed_state, "unknown"),
        unknown_reason=removed.idxmax(axis=1).where(~in_domain),
    )


def domain_summary(blocks: pd.DataFrame) -> dict[str, Any]:
    """Block counts per state. Unknown blocks are counted by reason and sit outside every share.

    ``masked_channel`` counts blocks removed mainly by the channel mask, not every block it touches.
    """
    states = blocks["state"].value_counts()
    reasons = blocks["unknown_reason"].dropna().value_counts()
    return {
        "blocks_total": int(len(blocks)),
        "evaluable": int(len(blocks) - states.get("unknown", 0)),
        "observed_wet": int(states.get("observed_wet", 0)),
        "not_mapped_as_flooded": int(states.get("not_mapped_as_flooded", 0)),
        "unknown_by_reason": {str(reason): int(count) for reason, count in sorted(reasons.items())},
        "masked_channel": int(reasons.get("channel", 0)),
    }


def build_record(
    *, run_id: str, aoi_id: str, flood_scenario: dict[str, Any], declared_sha256: str, layer: str,
    year: int, observed_sha256: str, nodes: pd.DataFrame, origin: tuple[float, float],
    blocks: pd.DataFrame, row: str = "primary", code_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The design note section 8 record. ``metrics`` stays empty until BKK-053b, after the lock."""
    params = flood_scenario["parameters"]
    if params.get("source_role") != "scenario":
        raise ValueError("the declared flood scenario must carry source_role 'scenario'")
    spec = _comparison_spec(layer)
    if not params["peak_depth_m"] > STORAGE_FLOOR_M:
        raise ValueError("a declared peak at or below the storage floor stores no extent")
    corridor = params["decay_length_m"] * math.log(params["peak_depth_m"] / STORAGE_FLOOR_M)
    return {
        "check_id": CHECK_ID, "protocol_version": PROTOCOL_VERSION, "release_id": RELEASE_ID,
        "run_id": run_id, "aoi_id": aoi_id,
        "declared": {
            "source_role": "scenario",
            "model": f"{flood_scenario['model_name']} {flood_scenario['model_version']}",
            "severity": params["severity"], "rank_field": "distance_to_water_m",
            "block_rank": "min_stored_distance", "storage_corridor_m": round(corridor),
            "not_evaluated_share": declared_coverage(nodes)["not_evaluated_share"],
            "input_sha256": declared_sha256,
        },
        "observed": {
            "source_id": spec["source_id"], "layer": spec["layer"], "year": year,
            "source_role": spec["source_role"], "measures": "extent_only",
            "feature_type": spec["feature_type"], "input_sha256": observed_sha256,
        },
        "unit": {
            "crs": ANALYSIS_CRS, "block_m": int(LATTICE_M * BLOCK_NODES),
            "lattice_origin_mod50": [round(origin[0], 3), round(origin[1], 3)],
            "observed_wet_rule": f">={OBSERVED_WET_RULE} evaluable area",
            "min_evaluable_rule": f">={MIN_EVALUABLE} block area",
        },
        "domain": {**domain_summary(blocks), "row": row},
        "metrics": None,
        "assumptions": list(ASSUMPTIONS),
        "assumption_text": dict(ASSUMPTIONS),
        "labels": dict(LABELS),
        "code_identity": code_identity,
    }
