"""Canonical evacuation-clearance definition shared by pipeline and API."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

EMPTY_CLEARANCE_MINUTES: dict[str, float | None] = {
    "p5": None,
    "median": None,
    "p95": None,
}
_QUANTILES = (("p5", 0.05), ("median", 0.50), ("p95", 0.95))


def weighted_clearance_minutes(
    states: pd.DataFrame, *, warning_time_s: Any
) -> dict[str, float | None]:
    """Return exact inverse weighted-ECDF clearance quantiles in minutes.

    Clearance is the arrival event time minus the saved warning time. Only
    arrived rows participate. Each quantile is the first observed clearance
    whose cumulative strictly-positive weight reaches ``q * total_weight``;
    values are never replicated, rounded by weight, or interpolated.
    """
    try:
        warning = float(warning_time_s)
    except (TypeError, ValueError) as exc:
        raise ValueError("warning_time_s must be a finite non-negative number") from exc
    if not np.isfinite(warning) or warning < 0:
        raise ValueError("warning_time_s must be a finite non-negative number")
    if "state" not in states.columns:
        raise ValueError("evacuation states must include state")

    arrived = states.loc[states["state"] == "arrived"]
    if arrived.empty:
        return dict(EMPTY_CLEARANCE_MINUTES)
    missing = {"event_time_s", "weight"} - set(arrived.columns)
    if missing:
        raise ValueError(f"arrived rows are missing required columns: {sorted(missing)}")

    weights = pd.to_numeric(arrived["weight"], errors="coerce").to_numpy(dtype=float)
    if np.any(~np.isfinite(weights)) or np.any(weights <= 0):
        raise ValueError("each arrived weight must be finite and strictly positive")
    events = pd.to_numeric(arrived["event_time_s"], errors="coerce").to_numpy(dtype=float)
    clearances = events - warning
    if np.any(~np.isfinite(clearances)) or np.any(clearances < 0):
        raise ValueError("each arrived clearance must be finite and non-negative")

    order = np.argsort(clearances, kind="stable")
    sorted_clearances = clearances[order]
    cumulative = np.cumsum(weights[order])
    total_weight = float(cumulative[-1])
    return {
        label: float(sorted_clearances[np.searchsorted(cumulative, q * total_weight)])
        / 60.0
        for label, q in _QUANTILES
    }
