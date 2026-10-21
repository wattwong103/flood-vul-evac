"""Flood summary for one model time: how big, how deep, can people move.

Everything here is derived from artefacts a run already holds
(``flood_slices``, ``edge_states``, ``network_edges`` and ``stats.json``), so no
pipeline stage is involved (docs/SITE_FLOOD_VIEWS_DESIGN.md, section 5.1).

Missing evidence stays visible. A run without a flood layer returns nulls with
the reason it gives; a time the run never modelled returns nulls, not zeros;
an edge with no state is counted as unknown, never as open. Zero is reported
only when it was measured or declared: no flooded cell at a modelled time, or a
dry scenario.
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

DRY_REASON = "declared dry scenario"
NO_STATES_REASON = "this run has no road states (edge_states.parquet is absent)"
NO_NETWORK_REASON = "this run has no road network (network_edges.parquet is absent)"
STATE_COLUMNS = frozenset({"edge_id", "mode", "speed_multiplier", "closed"})


def build_flood_summary(run: RunRef, time: int | None) -> FloodSummaryResponse:
    """Assemble the summary for ``time``, defaulting to the flood peak."""
    warnings: list[ApiWarning] = []
    stats, _ = load_stats_file(run)
    stats = stats or {}
    slices, _ = read_parquet(
        artefact_path(run, "flood_slices.parquet"),
        columns=["cell_id", "x", "y", "time_s", "depth_m", "source_role"],
    )
    no_flood_reason = None if slices is not None else _no_flood_reason(stats)
    if slices is not None and "depth_m" not in slices.columns:
        no_flood_reason = "flood_slices.parquet has no depth_m column"
        warnings.append(make_warning("schema_mismatch", no_flood_reason, "flood_slices.parquet"))
        slices = None
    state_times = _state_times(run)
    available_times = sorted(set(_times(slices)) | set(state_times or []))
    peak_time_s = _peak_time(slices)

    time_s = time
    if time_s is None:
        time_s = peak_time_s if peak_time_s is not None else min(available_times, default=None)
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

    if time_s is not None and available_times and time_s not in available_times:
        reason = f"this run has no model state at time {time_s} s"
        warnings.append(make_warning("time_not_available", reason))
        summary.how_big = FloodSize(reason=reason)
        summary.how_deep = FloodDepth(reason=reason)
        summary.movement = FloodMovement(reason=reason)
        # Pydantic copies lists on construction, so warnings are attached last.
        summary.warnings = warnings
        return summary

    states = _states_at(run, time_s, warnings) if state_times is not None else None
    version = _single_value(states, "threshold_set_version")
    summary.threshold_set_version = version
    closing = _closing_depths(version, warnings)

    at_time = _slice_at(slices, time_s)
    summary.source_role = _single_value(at_time, "source_role")
    dry = _is_dry(run)
    cell_size_m = _cell_size(slices)
    summary.how_big = _how_big(
        at_time, cell_size_m, _aoi_area(stats), dry=dry, missing_reason=no_flood_reason
    )
    summary.how_deep = _how_deep(
        at_time, cell_size_m, closing, dry=dry, missing_reason=no_flood_reason
    )
    summary.movement = _movement(run, states, closing, warnings)
    summary.warnings = warnings
    return summary


# ------------------------------------------------------------------ reading


def _times(frame: pd.DataFrame | None) -> list[int]:
    if frame is None or frame.empty or "time_s" not in frame.columns:
        return []
    values = pd.to_numeric(frame["time_s"], errors="coerce").dropna().unique()
    return [int(value) for value in values]


def _state_times(run: RunRef) -> list[int] | None:
    """Modelled road-state times, or None when the run has no road states."""
    frame, _ = read_parquet(artefact_path(run, "edge_states.parquet"), columns=["time_s"])
    return None if frame is None else _times(frame)


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
    if frame is None:
        return None
    return frame.loc[pd.to_numeric(frame["time_s"], errors="coerce") == time_s]


def _slice_at(slices: pd.DataFrame | None, time_s: int | None) -> pd.DataFrame | None:
    if slices is None:
        return None
    if time_s is None or "time_s" not in slices.columns:
        return slices.iloc[0:0]
    return slices.loc[pd.to_numeric(slices["time_s"], errors="coerce") == time_s]


def _peak_time(slices: pd.DataFrame | None) -> int | None:
    if slices is None or slices.empty or not {"time_s", "depth_m"} <= set(slices.columns):
        return None
    depth = pd.to_numeric(slices["depth_m"], errors="coerce")
    if depth.notna().sum() == 0:
        return None
    return int(slices.loc[depth.idxmax(), "time_s"])


def _single_value(frame: pd.DataFrame | None, column: str) -> str | None:
    """The one value of a provenance column; mixed values are named, not hidden."""
    if frame is None or column not in frame.columns:
        return None
    values = sorted({str(value) for value in frame[column].dropna()})
    if not values:
        return None
    return values[0] if len(values) == 1 else "mixed:" + ",".join(values)


def _flood_parameters(run: RunRef) -> dict[str, Any]:
    scenario = run.manifest.get("flood_scenario")
    parameters = scenario.get("parameters") if isinstance(scenario, dict) else None
    return parameters if isinstance(parameters, dict) else {}


def _is_dry(run: RunRef) -> bool:
    """A dry run declares a zero peak depth; it is a scenario, not missing data."""
    peak = _flood_parameters(run).get("peak_depth_m")
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


#: Decimal places for reported areas, lengths and shares; enough for a 50 m cell
#: or a 1 m road segment, without float noise such as 5.147500000000001.
REPORT_DECIMALS = 6


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), REPORT_DECIMALS)


def _cell_area_km2(cell_size_m: float) -> float:
    return (cell_size_m / 1000.0) ** 2


def _wet_cells(at_time: pd.DataFrame, min_depth_m: float) -> int:
    depth = pd.to_numeric(at_time["depth_m"], errors="coerce")
    wet = at_time.loc[depth >= min_depth_m]
    key = ["cell_id"] if "cell_id" in wet.columns else ["x", "y"]
    return int(wet.drop_duplicates(subset=key).shape[0])


def _how_big(
    at_time: pd.DataFrame | None,
    cell_size_m: float | None,
    aoi_area_km2: float | None,
    *,
    dry: bool,
    missing_reason: str | None,
) -> FloodSize:
    if at_time is None:
        return FloodSize(aoi_area_km2=aoi_area_km2, reason=missing_reason)
    cells = _wet_cells(at_time, FLOOD_AREA_THRESHOLD_M) if not at_time.empty else 0
    reason = DRY_REASON if dry else None
    if cells == 0:
        area = 0.0
    elif cell_size_m is None:
        return FloodSize(
            aoi_area_km2=aoi_area_km2,
            reason="the flood grid's cell size could not be inferred from its coordinates",
        )
    else:
        area = cells * _cell_area_km2(cell_size_m)
    share = area / aoi_area_km2 if aoi_area_km2 else None
    return FloodSize(
        flooded_area_km2=_rounded(area),
        share_of_aoi=_rounded(share),
        aoi_area_km2=aoi_area_km2,
        cell_size_m=cell_size_m,
        reason=reason,
    )


def _how_deep(
    at_time: pd.DataFrame | None,
    cell_size_m: float | None,
    closing: dict[int, float | None],
    *,
    dry: bool,
    missing_reason: str | None,
) -> FloodDepth:
    if at_time is None:
        return FloodDepth(reason=missing_reason)
    depth = pd.to_numeric(at_time["depth_m"], errors="coerce").dropna() if not at_time.empty else None
    max_depth = float(depth.max()) if depth is not None and not depth.empty else 0.0
    stops: list[ModeStopArea] = []
    for mode, name in MODE_NAMES.items():
        closed_depth = closing.get(mode)
        area: float | None = None
        if closed_depth is not None:
            cells = _wet_cells(at_time, closed_depth) if not at_time.empty else 0
            if cells == 0:
                area = 0.0
            elif cell_size_m is not None:
                area = cells * _cell_area_km2(cell_size_m)
        stops.append(
            ModeStopArea(
                mode=mode, mode_name=name, closed_depth_m=closed_depth, area_km2=_rounded(area)
            )
        )
    return FloodDepth(
        max_depth_m=max_depth,
        at_or_above_closing_depth=stops,
        reason=DRY_REASON if dry else None,
    )


def _movement(
    run: RunRef,
    states: pd.DataFrame | None,
    closing: dict[int, float | None],
    warnings: list[ApiWarning],
) -> FloodMovement:
    if states is None:
        return FloodMovement(reason=NO_STATES_REASON)
    missing = STATE_COLUMNS - set(states.columns)
    if missing:
        reason = f"edge_states.parquet lacks {sorted(missing)}"
        warnings.append(make_warning("schema_mismatch", reason, "edge_states.parquet"))
        return FloodMovement(reason=reason)
    edges, edge_warnings = read_parquet(
        artefact_path(run, "network_edges.parquet"),
        columns=["edge_id", "length_m", *MODE_ACCESS_COLUMNS.values()],
    )
    warnings.extend(edge_warnings)
    if edges is None or "length_m" not in edges.columns:
        return FloodMovement(reason=NO_NETWORK_REASON)
    modes = [
        _mode_movement(mode, name, edges, states, closing.get(mode), warnings)
        for mode, name in MODE_NAMES.items()
    ]
    return FloodMovement(modes=modes)


def _mode_movement(
    mode: int,
    name: str,
    edges: pd.DataFrame,
    states: pd.DataFrame,
    closed_depth_m: float | None,
    warnings: list[ApiWarning],
) -> ModeMovement:
    access = MODE_ACCESS_COLUMNS[mode]
    if access in edges.columns:
        usable = edges.loc[edges[access].fillna(False).astype(bool)]
    else:
        usable = edges
        warnings.append(
            make_warning(
                "schema_mismatch",
                f"network_edges.parquet has no {access} column; every edge is counted for {name}",
                "network_edges.parquet",
            )
        )
    mode_states = states.loc[pd.to_numeric(states["mode"], errors="coerce") == mode]
    mode_states = mode_states.drop_duplicates(subset=["edge_id"], keep="last")
    joined = usable[["edge_id", "length_m"]].merge(
        mode_states[["edge_id", "speed_multiplier", "closed"]], on="edge_id", how="left"
    )
    length_km = pd.to_numeric(joined["length_m"], errors="coerce").fillna(0.0) / 1000.0
    closed = joined["closed"].astype("boolean").fillna(False).astype(bool)
    speed = pd.to_numeric(joined["speed_multiplier"], errors="coerce")
    slowed = ~closed & (speed < 1.0)
    opened = ~closed & (speed >= 1.0)
    unknown = ~closed & speed.isna()
    total = float(length_km.sum())

    def km(mask: pd.Series) -> float:
        return round(float(length_km[mask].sum()), REPORT_DECIMALS)

    def share(mask: pd.Series) -> float | None:
        return _rounded(float(length_km[mask].sum()) / total) if total > 0 else None

    return ModeMovement(
        mode=mode,
        mode_name=name,
        closed_depth_m=closed_depth_m,
        total_km=round(total, REPORT_DECIMALS),
        open_km=km(opened),
        slowed_km=km(slowed),
        closed_km=km(closed),
        unknown_km=km(unknown),
        open_share=share(opened),
        slowed_share=share(slowed),
        closed_share=share(closed),
    )
