"""Flood summary for one model time: how big, how deep, can people move.

Everything here is derived from artefacts a run already holds
(``flood_slices``, ``edge_states``, ``network_edges`` and ``stats.json``), so no
pipeline stage is involved (docs/SITE_FLOOD_VIEWS_DESIGN.md, section 5.1).

Missing evidence stays visible. A run without a flood layer returns nulls with
the reason it gives; an unreadable or malformed artefact returns nulls with a
warning, never a 500; a time the run never modelled, or depth that was never
recorded, returns nulls, not zeros; an edge with no state is counted as
unknown, never as open. Zero is reported only when it was measured or declared:
no flooded cell at a modelled time, or a dry scenario.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from api.models import (
    ApiWarning,
    FloodDepth,
    FloodMovement,
    FloodSize,
    FloodSummaryResponse,
    ModeMovement,
    ModeStopArea,
)
from api.runs import RunRef
from api.tables import artefact_path, load_stats_file, make_warning, read_parquet
from pipeline.bkkflow.flood import THRESHOLD_SETS

#: Depth at which a cell counts as flooded for "how big". It matches the
#: pipeline's own ``flooded_area_km2`` basis (pipeline/bkkflow/runner.py) and is
#: deliberately not the cohort's ``exposure_threshold``, which is 0.0 on dry runs.
FLOOD_AREA_THRESHOLD_M = 0.15

#: PFLOW mode codes summarised here and the network column that admits each.
MODE_NAMES: dict[int, str] = {0: "walk", 3: "car"}
MODE_ACCESS_COLUMNS: dict[int, str] = {0: "walk_allowed", 3: "vehicle_allowed"}

#: Decimal places for reported areas, lengths and shares; enough for a 50 m cell
#: or a 1 m road segment, without float noise such as 5.147500000000001.
REPORT_DECIMALS = 6
#: A flooded share of the AOI above 1 by more than this is a data inconsistency.
SHARE_TOLERANCE = 1e-6

FLOOD_COLUMNS = ["cell_id", "x", "y", "time_s", "depth_m", "source_role"]
STATE_COLUMNS = frozenset({"edge_id", "mode", "speed_multiplier", "closed"})
EDGE_COLUMNS = frozenset({"edge_id", "length_m"})

DRY_REASON = "declared dry scenario"
NO_STATES_REASON = "this run has no road states (edge_states.parquet is absent)"
NO_NETWORK_REASON = "this run has no road network (network_edges.parquet is absent)"
UNMEASURED_REASON = "no flood cell at this time has a recorded depth"
NO_CELL_SIZE_REASON = "the flood grid's cell size could not be inferred from its coordinates"


def build_flood_summary(run: RunRef, time: int | None) -> FloodSummaryResponse:
    """Assemble the summary for ``time``, defaulting to the flood peak."""
    warnings: list[ApiWarning] = []
    stats = load_stats_file(run)[0] or {}
    slices, no_flood_reason = _read_slices(run, stats, warnings)
    state_times, no_states_reason = _read_state_times(run, warnings)
    available_times = sorted(set(_times(slices)) | set(state_times or []))
    peak_time_s = _peak_time(slices)
    time_s = time if time is not None else _default_time(run, peak_time_s, available_times)
    summary = FloodSummaryResponse(
        run_id=run.run_id,
        validation_status=run.validation_status,
        available=slices is not None or state_times is not None,
        time_s=time_s,
        time_defaulted=time is None and time_s is not None,
        available_times=available_times,
        peak_time_s=peak_time_s,
        flood_area_threshold_m=FLOOD_AREA_THRESHOLD_M,
    )
    if time_s is not None and summary.available and time_s not in available_times:
        return _unmodelled_time(summary, time_s, warnings)

    states = _states_at(run, time_s, warnings) if state_times is not None else None
    version = _single_value(states, "threshold_set_version")
    summary.threshold_set_version = version
    closing = _closing_depths(version, warnings)

    at_time = _slice_at(slices, time_s)
    summary.source_role = _single_value(at_time, "source_role") or _declared(run, "source_role")
    missing_reason = no_flood_reason or _unmeasured_depth(at_time, warnings)
    if missing_reason is not None:
        at_time = None
    dry = _is_dry(run)
    cell_size_m = _cell_size(slices)
    summary.how_big = _how_big(
        at_time, cell_size_m, _aoi_area(stats), warnings, dry=dry, missing_reason=missing_reason
    )
    summary.how_deep = _how_deep(
        at_time, cell_size_m, closing, version, dry=dry, missing_reason=missing_reason
    )
    summary.movement = _movement(run, states, no_states_reason, closing, warnings)
    # Pydantic copies lists on construction, so warnings are attached last.
    summary.warnings = warnings
    return summary


def _unmodelled_time(
    summary: FloodSummaryResponse, time_s: int, warnings: list[ApiWarning]
) -> FloodSummaryResponse:
    """A time the run never modelled is unknown, not dry: every reading is null."""
    reason = f"this run has no model state at time {time_s} s"
    warnings.append(make_warning("time_not_available", reason))
    summary.how_big = FloodSize(reason=reason)
    summary.how_deep = FloodDepth(reason=reason)
    summary.movement = FloodMovement(reason=reason)
    summary.warnings = warnings
    return summary


def _default_time(run: RunRef, peak_time_s: int | None, available: list[int]) -> int | None:
    """The flood peak, else the declared peak, else the first modelled time.

    A dry run has no flood cells, so its declared peak keeps the default on the
    same clock time as its moderate pair.
    """
    if peak_time_s is not None:
        return peak_time_s
    declared = _declared(run, "peak_time_s")
    if isinstance(declared, (int, float)) and int(declared) in available:
        return int(declared)
    return min(available, default=None)


# ------------------------------------------------------------------ reading


def _was_absent(read_warnings: list[ApiWarning]) -> bool:
    return any(warning.code == "missing_artefact" for warning in read_warnings)


def _read_failure(
    name: str, read_warnings: list[ApiWarning], warnings: list[ApiWarning]
) -> str:
    """Report a present-but-unusable artefact; its own message becomes the reason."""
    warnings.extend(read_warnings)
    return read_warnings[0].message if read_warnings else f"{name} could not be read"


def _read_slices(
    run: RunRef, stats: dict[str, Any], warnings: list[ApiWarning]
) -> tuple[pd.DataFrame | None, str | None]:
    """The flood cells, or None and the reason they cannot be used."""
    name = "flood_slices.parquet"
    slices, read_warnings = read_parquet(artefact_path(run, name), columns=FLOOD_COLUMNS)
    if slices is None:
        if _was_absent(read_warnings):
            return None, _no_flood_reason(stats)
        return None, _read_failure(name, read_warnings, warnings)
    columns = set(slices.columns)
    missing = [column for column in ("depth_m", "time_s") if column not in columns]
    if "cell_id" not in columns and not {"x", "y"} <= columns:
        missing.append("cell_id or x/y")
    if missing:
        reason = f"{name} lacks {', '.join(missing)}"
        warnings.append(make_warning("schema_mismatch", reason, name))
        return None, reason
    return slices, None


def _read_state_times(
    run: RunRef, warnings: list[ApiWarning]
) -> tuple[list[int] | None, str | None]:
    """Modelled road-state times, or None and the reason there are none."""
    name = "edge_states.parquet"
    frame, read_warnings = read_parquet(artefact_path(run, name), columns=["time_s"])
    if frame is not None:
        return _times(frame), None
    if _was_absent(read_warnings):
        return None, NO_STATES_REASON
    return None, _read_failure(name, read_warnings, warnings)


def _times(frame: pd.DataFrame | None) -> list[int]:
    if frame is None or frame.empty or "time_s" not in frame.columns:
        return []
    values = pd.to_numeric(frame["time_s"], errors="coerce").dropna().unique()
    return [int(value) for value in values]


def _states_at(
    run: RunRef, time_s: int | None, warnings: list[ApiWarning]
) -> pd.DataFrame | None:
    if time_s is None:
        return None
    frame, read_warnings = read_parquet(
        artefact_path(run, "edge_states.parquet"),
        columns=["edge_id", "time_s", "mode", "speed_multiplier", "closed", "threshold_set_version"],
        filters=[("time_s", "==", int(time_s))],
    )
    warnings.extend(read_warnings)
    if frame is None or "time_s" not in frame.columns:
        return frame
    return frame.loc[pd.to_numeric(frame["time_s"], errors="coerce") == time_s]


def _slice_at(slices: pd.DataFrame | None, time_s: int | None) -> pd.DataFrame | None:
    if slices is None:
        return None
    if time_s is None:
        return slices.iloc[0:0]
    return slices.loc[pd.to_numeric(slices["time_s"], errors="coerce") == time_s]


def _peak_time(slices: pd.DataFrame | None) -> int | None:
    """The earliest time at which the deepest recorded cell occurs."""
    if slices is None or slices.empty:
        return None
    depth = pd.to_numeric(slices["depth_m"], errors="coerce")
    times = pd.to_numeric(slices["time_s"], errors="coerce")
    valid = depth.notna() & times.notna()
    if not valid.any():
        return None
    deepest = depth[valid].max()
    return int(times[valid & (depth == deepest)].min())


def _unmeasured_depth(at_time: pd.DataFrame | None, warnings: list[ApiWarning]) -> str | None:
    """A reason when cells exist at this time but none records a depth."""
    if at_time is None or at_time.empty:
        return None
    unrecorded = int(pd.to_numeric(at_time["depth_m"], errors="coerce").isna().sum())
    if unrecorded == 0:
        return None
    if unrecorded == len(at_time):
        warnings.append(make_warning("null_depth", UNMEASURED_REASON, "flood_slices.parquet"))
        return UNMEASURED_REASON
    warnings.append(
        make_warning(
            "null_depth",
            f"{unrecorded} flood cells at this time have no recorded depth and are not counted",
            "flood_slices.parquet",
        )
    )
    return None


def _single_value(frame: pd.DataFrame | None, column: str) -> str | None:
    """The one value of a provenance column; mixed values are named, not hidden."""
    if frame is None or column not in frame.columns:
        return None
    values = sorted({str(value) for value in frame[column].dropna()})
    if not values:
        return None
    return values[0] if len(values) == 1 else "mixed:" + ",".join(values)


def _declared(run: RunRef, key: str) -> Any:
    """A value the run's manifest declares for its flood scenario."""
    scenario = run.manifest.get("flood_scenario")
    parameters = scenario.get("parameters") if isinstance(scenario, dict) else None
    return parameters.get(key) if isinstance(parameters, dict) else None


def _is_dry(run: RunRef) -> bool:
    """A dry run declares a zero peak depth; it is a scenario, not missing data."""
    peak = _declared(run, "peak_depth_m")
    return isinstance(peak, (int, float)) and float(peak) == 0.0


def _no_flood_reason(stats: dict[str, Any]) -> str:
    """The run's own explanation for having no flood layer, when it gives one."""
    flood = stats.get("flood")
    reason = flood.get("depth_reason") if isinstance(flood, dict) else None
    if isinstance(reason, str) and reason:
        return reason
    return "this run has no flood layer (flood_slices.parquet is absent)"


def _aoi_area(stats: dict[str, Any]) -> float | None:
    geography = stats.get("geography")
    area = geography.get("area_km2") if isinstance(geography, dict) else None
    if isinstance(area, (int, float)) and area > 0:
        return float(area)
    return None


def _cell_size(slices: pd.DataFrame | None) -> float | None:
    """The flood grid's spacing, read from the cells themselves.

    The cell size is not in the manifest, and today's configuration may differ
    from the one an immutable run used, so the stored coordinates are the only
    trustworthy source. A grid with a single cell has no spacing to read.
    """
    if slices is None or slices.empty or not {"x", "y"} <= set(slices.columns):
        return None
    spacings: list[float] = []
    for column in ("x", "y"):
        values = np.sort(pd.to_numeric(slices[column], errors="coerce").dropna().unique())
        steps = np.diff(values)
        steps = steps[steps > 1e-6]
        if steps.size:
            spacings.append(float(steps.min()))
    return round(min(spacings), 6) if spacings else None


def _closing_depths(
    version: str | None, warnings: list[ApiWarning]
) -> dict[int, float | None]:
    thresholds = THRESHOLD_SETS.get(version or "")
    if thresholds is None:
        if version is not None:
            warnings.append(
                make_warning(
                    "unknown_threshold_set",
                    f"threshold set {version!r} is not known to this service; "
                    "closing depths are null",
                    "edge_states.parquet",
                )
            )
        return {mode: None for mode in MODE_NAMES}
    return {
        mode: float(thresholds[mode]["closed_depth_m"]) if mode in thresholds else None
        for mode in MODE_NAMES
    }


# ---------------------------------------------------------------- readings


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), REPORT_DECIMALS)


def _cell_area_km2(cell_size_m: float) -> float:
    return (cell_size_m / 1000.0) ** 2


def _wet_cells(at_time: pd.DataFrame, min_depth_m: float) -> int:
    depth = pd.to_numeric(at_time["depth_m"], errors="coerce")
    wet = at_time.loc[depth >= min_depth_m]
    key = ["cell_id"] if "cell_id" in wet.columns else ["x", "y"]
    return int(wet.drop_duplicates(subset=key).shape[0])


def _area_km2(at_time: pd.DataFrame, min_depth_m: float, cell_size_m: float | None) -> float | None:
    """Area at or above a depth; zero needs no cell size, a positive area does."""
    cells = _wet_cells(at_time, min_depth_m) if not at_time.empty else 0
    if cells == 0:
        return 0.0
    return None if cell_size_m is None else cells * _cell_area_km2(cell_size_m)


def _how_big(
    at_time: pd.DataFrame | None,
    cell_size_m: float | None,
    aoi_area_km2: float | None,
    warnings: list[ApiWarning],
    *,
    dry: bool,
    missing_reason: str | None,
) -> FloodSize:
    if at_time is None:
        return FloodSize(aoi_area_km2=aoi_area_km2, reason=missing_reason)
    area = _area_km2(at_time, FLOOD_AREA_THRESHOLD_M, cell_size_m)
    if area is None:
        return FloodSize(aoi_area_km2=aoi_area_km2, reason=NO_CELL_SIZE_REASON)
    share = area / aoi_area_km2 if aoi_area_km2 else None
    if share is not None and share > 1.0 + SHARE_TOLERANCE:
        warnings.append(
            make_warning(
                "inconsistent_aoi",
                f"flooded area {area:.4f} km2 exceeds the AOI area {aoi_area_km2:.4f} km2; "
                "the flood grid extends beyond the AOI, so its share is withheld",
                "flood_slices.parquet",
            )
        )
        share = None
    return FloodSize(
        flooded_area_km2=_rounded(area),
        share_of_aoi=_rounded(share),
        aoi_area_km2=aoi_area_km2,
        cell_size_m=cell_size_m,
        reason=DRY_REASON if dry else None,
    )


def _how_deep(
    at_time: pd.DataFrame | None,
    cell_size_m: float | None,
    closing: dict[int, float | None],
    version: str | None,
    *,
    dry: bool,
    missing_reason: str | None,
) -> FloodDepth:
    if at_time is None:
        return FloodDepth(reason=missing_reason)
    depth = pd.to_numeric(at_time["depth_m"], errors="coerce").dropna()
    stops = [
        ModeStopArea(
            mode=mode,
            mode_name=name,
            closed_depth_m=closing.get(mode),
            area_km2=_rounded(
                None if closing.get(mode) is None
                else _area_km2(at_time, closing[mode], cell_size_m)
            ),
        )
        for mode, name in MODE_NAMES.items()
    ]
    reason = DRY_REASON if dry else None
    if any(stop.closed_depth_m is None for stop in stops):
        reason = f"closing depths are unknown for threshold set {version!r}"
    elif any(stop.area_km2 is None for stop in stops):
        reason = NO_CELL_SIZE_REASON
    return FloodDepth(
        max_depth_m=float(depth.max()) if not depth.empty else 0.0,
        at_or_above_closing_depth=stops,
        reason=reason,
    )


def _movement(
    run: RunRef,
    states: pd.DataFrame | None,
    no_states_reason: str | None,
    closing: dict[int, float | None],
    warnings: list[ApiWarning],
) -> FloodMovement:
    if states is None:
        return FloodMovement(reason=no_states_reason or "edge_states.parquet could not be read")
    missing = STATE_COLUMNS - set(states.columns)
    if missing:
        reason = f"edge_states.parquet lacks {sorted(missing)}"
        warnings.append(make_warning("schema_mismatch", reason, "edge_states.parquet"))
        return FloodMovement(reason=reason)
    edges, reason = _usable_network(run, warnings)
    if edges is None:
        return FloodMovement(reason=reason)
    states = states.assign(edge_id=states["edge_id"].astype(str))
    modes = [
        _mode_movement(mode, name, edges, states, closing.get(mode), warnings)
        for mode, name in MODE_NAMES.items()
    ]
    return FloodMovement(modes=modes)


def _usable_network(
    run: RunRef, warnings: list[ApiWarning]
) -> tuple[pd.DataFrame | None, str | None]:
    """Network edges keyed by text id, deduplicated, with known lengths only."""
    name = "network_edges.parquet"
    edges, read_warnings = read_parquet(
        artefact_path(run, name), columns=["edge_id", "length_m", *MODE_ACCESS_COLUMNS.values()]
    )
    if edges is None:
        if _was_absent(read_warnings):
            return None, NO_NETWORK_REASON
        return None, _read_failure(name, read_warnings, warnings)
    missing = EDGE_COLUMNS - set(edges.columns)
    if missing:
        reason = f"{name} lacks {sorted(missing)}"
        warnings.append(make_warning("schema_mismatch", reason, name))
        return None, reason
    edges = edges.assign(edge_id=edges["edge_id"].astype(str))
    duplicated = int(edges["edge_id"].duplicated().sum())
    if duplicated:
        warnings.append(
            make_warning("duplicate_rows", f"{duplicated} duplicate edge ids were counted once", name)
        )
        edges = edges.drop_duplicates(subset=["edge_id"], keep="first")
    lengths = pd.to_numeric(edges["length_m"], errors="coerce")
    if lengths.isna().any():
        warnings.append(
            make_warning(
                "missing_length",
                f"{int(lengths.isna().sum())} edges have no length and are not counted",
                name,
            )
        )
    return edges.loc[lengths.notna()].assign(length_m=lengths[lengths.notna()]), None


def _mode_movement(
    mode: int,
    name: str,
    edges: pd.DataFrame,
    states: pd.DataFrame,
    closed_depth_m: float | None,
    warnings: list[ApiWarning],
) -> ModeMovement:
    access = MODE_ACCESS_COLUMNS[mode]
    if access not in edges.columns:
        reason = f"network_edges.parquet has no {access} column, so the roads {name} may use are unknown"
        warnings.append(make_warning("schema_mismatch", reason, "network_edges.parquet"))
        return ModeMovement(mode=mode, mode_name=name, closed_depth_m=closed_depth_m, reason=reason)
    flags = edges[access].astype("boolean")
    if flags.isna().any():
        warnings.append(
            make_warning(
                "missing_access_flag",
                f"{int(flags.isna().sum())} edges have no {access} value and are not counted for {name}",
                "network_edges.parquet",
            )
        )
    usable = edges.loc[flags.fillna(False).astype(bool), ["edge_id", "length_m"]]
    mode_states = states.loc[pd.to_numeric(states["mode"], errors="coerce") == mode]
    mode_states = mode_states.drop_duplicates(subset=["edge_id"], keep="last")
    joined = usable.merge(
        mode_states[["edge_id", "speed_multiplier", "closed"]], on="edge_id", how="left"
    )
    return _classify(mode, name, closed_depth_m, joined)


def _classify(
    mode: int, name: str, closed_depth_m: float | None, joined: pd.DataFrame
) -> ModeMovement:
    """Road length by state; shares are null when no usable edge has a state."""
    length_km = joined["length_m"] / 1000.0
    closed = joined["closed"].astype("boolean").fillna(False).astype(bool)
    speed = pd.to_numeric(joined["speed_multiplier"], errors="coerce")
    masks = {
        "open": ~closed & (speed >= 1.0),
        "slowed": ~closed & (speed < 1.0),
        "closed": closed,
        "unknown": ~closed & speed.isna(),
    }
    km = {state: float(length_km[mask].sum()) for state, mask in masks.items()}
    total = float(length_km.sum())
    no_states = total > 0 and km["unknown"] >= total - 1e-9
    shares = {
        state: None if total <= 0 or no_states else _rounded(value / total)
        for state, value in km.items()
    }
    return ModeMovement(
        mode=mode,
        mode_name=name,
        closed_depth_m=closed_depth_m,
        total_km=_rounded(total),
        open_km=_rounded(km["open"]),
        slowed_km=_rounded(km["slowed"]),
        closed_km=_rounded(km["closed"]),
        unknown_km=_rounded(km["unknown"]),
        open_share=shares["open"],
        slowed_share=shares["slowed"],
        closed_share=shares["closed"],
        unknown_share=shares["unknown"],
        reason=f"no road state for {name} at this time" if no_states else None,
    )
