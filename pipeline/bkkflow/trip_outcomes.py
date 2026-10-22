"""Trip outcomes under a flood: unaffected, detour or no route (BKK-055d).

Every everyday trip is checked against the road states in force when it
departs (the latest ``edge_states`` time at or before its departure). A trip
whose dry route crosses no closed or slowed road is unaffected. Otherwise it
is re-routed on its mode's graph at that time, with closed roads removed and
slowed roads kept at their reduced speed (``build_routing_graph``'s rule, the
same as the evacuation step): a slower or longer route is a detour, and no
route is no route. Slowed means any speed reduction, as in the API and site
(North, 22 October 2026).

Trips departing outside the flood window, and trips that had no dry route,
are counted apart and never as flood effects.

These are the model's synthetic, uncalibrated trips, which stay inside the
district (design note section 4.3): never commutes, and never observed travel.
"""

from __future__ import annotations

import math
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from . import mobility as mobility_module
from .city_method import PUBLIC_GRID_M

OUTCOMES = ("unaffected", "detour", "no_route", "outside_flood_window", "not_routed_dry")
#: Outcomes that describe the flood's effect; the other two are counted apart.
FLOOD_OUTCOMES = ("unaffected", "detour", "no_route")
#: Why a trip has no route: every road at one of its ends is closed, or the
#: ends are open but no longer joined.
NO_ROUTE_REASONS = ("origin_cut_off", "destination_cut_off", "no_path")
#: ``route_trips`` stores the dry time rounded to 0.01 s, so a re-route within
#: that of it is the same trip, not a detour.
DETOUR_TOLERANCE_S = 0.01

COLUMNS = [
    "trip_id", "mode", "dest_purpose", "depart_time_s", "state_time_s", "origin_cell", "weight",
    "outcome", "dry_time_s", "flood_time_s", "extra_time_s", "blocking_edge_id", "no_route_reason",
]
# Fixed types, so the parquet schema never depends on which outcomes occur.
_DTYPES = {
    "trip_id": "string", "mode": "int64", "dest_purpose": "string", "depart_time_s": "int64",
    "state_time_s": "Int64", "origin_cell": "string", "weight": "float64", "outcome": "string",
    "dry_time_s": "float64", "flood_time_s": "float64", "extra_time_s": "float64",
    "blocking_edge_id": "string", "no_route_reason": "string",
}

# (state time, mode) -> (speed multiplier per edge, closed edge ids)
_StateKey = tuple[int, int]
_State = tuple[dict[str, float], frozenset[str]]
# A trip's output record, paired with its input row, waiting for a re-route.
_Pending = list[tuple[dict[str, Any], dict[str, Any]]]


def classify_trip_outcomes(
    trips: pd.DataFrame,
    waypoints: pd.DataFrame,
    edges: gpd.GeoDataFrame,
    edge_states: pd.DataFrame,
    *,
    analysis_crs: str,
    window: tuple[int, int],
    dry_indices: dict[int, mobility_module.NetworkIndex] | None = None,
) -> pd.DataFrame:
    """One row per trip with its outcome under the flood (see module docstring).

    Raises ``ValueError`` when a road state the trips need is missing or
    unknown, or a routed trip has no waypoints: those are never read as open.
    """
    if trips.empty:
        return pd.DataFrame(columns=COLUMNS).astype(_DTYPES)
    routes = _route_edges(waypoints)
    states = _state_lookup(edge_states)
    # Each mode's own state times, so one mode's clock never picks another's state.
    state_times = {
        mode: np.array(sorted(time for time, key_mode in states if key_mode == mode), dtype="int64")
        for mode in {mode for _, mode in states}
    }
    records: list[dict[str, Any]] = []
    reroutes: dict[_StateKey, _Pending] = {}
    for trip in trips.to_dict("records"):
        record = {**_base_record(trip), **_screen(trip, routes, states, state_times, window)}
        if record["outcome"] is None:
            reroutes.setdefault((record["state_time_s"], record["mode"]), []).append((record, trip))
        records.append(record)
    router = _Router(edges, analysis_crs, dict(dry_indices or {}))
    # Grouped by state, so only one flooded graph is held at a time.
    for key, pending in reroutes.items():
        router.reroute(key, states[key], pending)
    return pd.DataFrame.from_records(records, columns=COLUMNS).astype(_DTYPES)


def _base_record(trip: dict[str, Any]) -> dict[str, Any]:
    return {
        "trip_id": trip["trip_id"],
        "mode": int(trip["mode"]),
        "dest_purpose": trip.get("dest_purpose"),
        "depart_time_s": int(trip["depart_time_s"]),
        "state_time_s": None,
        "origin_cell": _cell_id(trip.get("origin_x"), trip.get("origin_y")),
        "weight": float(trip.get("weight", 1.0)),
    }


_EMPTY = {"outcome": None, "dry_time_s": None, "flood_time_s": None, "extra_time_s": None,
          "blocking_edge_id": None, "no_route_reason": None}


def _screen(
    trip: dict[str, Any],
    routes: dict[str, tuple[list[str], float]],
    states: dict[_StateKey, _State],
    state_times: dict[int, np.ndarray],
    window: tuple[int, int],
) -> dict[str, Any]:
    """Every outcome that needs no re-route; ``outcome`` None marks one that does."""
    if trip.get("route_status") != "routed":
        return {**_EMPTY, "outcome": "not_routed_dry"}
    depart, mode = int(trip["depart_time_s"]), int(trip["mode"])
    if not window[0] <= depart <= window[1]:
        return {**_EMPTY, "outcome": "outside_flood_window"}
    times = state_times.get(mode)
    position = -1 if times is None else int(np.searchsorted(times, depart, side="right")) - 1
    if position < 0:
        raise ValueError(f"edge_states has no road states for mode {mode} at or before {depart}")
    state_time = int(times[position])
    if trip["trip_id"] not in routes:
        raise ValueError(f"routed trip {trip['trip_id']!r} has no waypoints")
    speeds, closed = states[(state_time, mode)]
    route, dry_cost = routes[trip["trip_id"]]
    try:
        impacted = [edge for edge in route if edge in closed or speeds[edge] < 1.0]
    except KeyError as missing:
        raise ValueError(
            f"edge_states has no state for edge {missing.args[0]!r} (mode {mode}, time {state_time})"
        ) from None
    base = {**_EMPTY, "state_time_s": state_time, "dry_time_s": dry_cost}
    if not impacted:
        return {**base, "outcome": "unaffected", "flood_time_s": dry_cost, "extra_time_s": 0.0}
    return {**base, "blocking_edge_id": next((edge for edge in impacted if edge in closed), impacted[0])}


def _settle(record: dict[str, Any], flood_cost: float | None, reason: str | None) -> None:
    """Fill in a re-routed trip's outcome."""
    if flood_cost is None:
        record.update(outcome="no_route", no_route_reason=reason)
        return
    extra = flood_cost - record["dry_time_s"]
    if extra <= DETOUR_TOLERANCE_S:
        record.update(outcome="unaffected", flood_time_s=record["dry_time_s"], extra_time_s=0.0,
                      blocking_edge_id=None)
        return
    record.update(outcome="detour", flood_time_s=flood_cost, extra_time_s=extra)


class _Router:
    """Dry snapping per mode, and one flooded graph at a time."""

    def __init__(self, edges: gpd.GeoDataFrame, analysis_crs: str,
                 dry: dict[int, mobility_module.NetworkIndex]) -> None:
        self.edges, self.analysis_crs, self.dry = edges, analysis_crs, dry

    def reroute(self, key: _StateKey, state: _State, pending: _Pending) -> None:
        """Settle each pending record on the graph for ``key``, released on return."""
        mode = key[1]
        speeds, closed = state
        if mode not in self.dry:
            self.dry[mode] = mobility_module.NetworkIndex(
                mobility_module.build_routing_graph(self.edges, mode), self.analysis_crs
            )
        dry = self.dry[mode]
        multipliers = {edge: 0.0 if edge in closed else value for edge, value in speeds.items()}
        graph = mobility_module.build_routing_graph(self.edges, mode, speed_multipliers=multipliers)
        for record, trip in pending:
            # Both ends stay where the dry route snapped them, so it is the same trip.
            origin = dry.snap(float(trip["origin_x"]), float(trip["origin_y"]))
            destination = dry.snap(float(trip["dest_x"]), float(trip["dest_y"]))
            if origin is None or destination is None:
                raise ValueError(f"routed trip {trip['trip_id']!r} no longer snaps to its mode's network")
            _settle(record, *_least_cost(graph, origin, destination))


def _least_cost(graph: Any, origin: int, destination: int) -> tuple[float | None, str | None]:
    """Least travel time between the dry ends, or None with the reason there is none."""
    import networkx as nx

    # A node whose every road is closed is not in the flooded graph at all.
    if origin not in graph:
        return None, "origin_cut_off"
    if destination not in graph:
        return None, "destination_cut_off"
    try:
        cost, _ = nx.bidirectional_dijkstra(graph, origin, destination, weight="cost")
    except nx.NetworkXNoPath:
        return None, "no_path"
    return float(cost), None


def _route_edges(waypoints: pd.DataFrame) -> dict[str, tuple[list[str], float]]:
    """Each trip's dry route: its ordered edge ids and its stored travel time.

    The last waypoint's ``cumulative_time_s`` is the dry route's cost on the
    same graph and weights, so the dry route is never searched for again. A
    chain must be whole (``seq`` 0..n-1, an edge out of every point but the
    last) or its stored cost would be short.
    """
    if waypoints.empty or "edge_id" not in waypoints.columns:
        return {}
    ordered = waypoints.sort_values(["trip_id", "seq"], kind="stable")
    routes: dict[str, tuple[list[str], float]] = {}
    for trip_id, group in ordered.groupby("trip_id", sort=False):
        edge_ids = group["edge_id"].tolist()
        cost = float(group["cumulative_time_s"].iloc[-1])
        whole = (
            group["seq"].tolist() == list(range(len(group)))
            and all(isinstance(edge, str) and edge for edge in edge_ids[:-1])
            and not isinstance(edge_ids[-1], str)
            and math.isfinite(cost)
        )
        if not whole:
            raise ValueError(f"routed trip {trip_id!r} has an incomplete waypoint chain")
        routes[trip_id] = (edge_ids[:-1], cost)
    return routes


def _state_lookup(edge_states: pd.DataFrame) -> dict[_StateKey, _State]:
    """Road states by (time, mode), under the API and site rule.

    Closed only on a stored true flag; open or slowed only on a stored false
    flag with a speed multiplier in [0, 1]. Anything else is unknown and is
    refused rather than read as open.
    """
    # A text flag such as "false" is truthy, so only stored booleans are read.
    if not edge_states["closed"].isin([True, False]).all():
        raise ValueError("edge_states has rows without a true or false closed flag; an unknown road state is never open")
    closed = edge_states["closed"].astype(bool).to_numpy()
    speeds = pd.to_numeric(edge_states["speed_multiplier"], errors="coerce").to_numpy(dtype="float64")
    unknown = ~closed & ~((speeds >= 0.0) & (speeds <= 1.0))
    if unknown.any():
        raise ValueError(f"edge_states has {int(unknown.sum())} open rows without a speed multiplier in [0, 1]")
    frame = pd.DataFrame({
        "time_s": edge_states["time_s"].to_numpy(), "mode": edge_states["mode"].to_numpy(),
        "edge_id": edge_states["edge_id"].to_numpy(), "speed": speeds, "closed": closed,
    })
    lookup: dict[_StateKey, _State] = {}
    for (time_s, mode), group in frame.groupby(["time_s", "mode"], sort=True):
        lookup[(int(time_s), int(mode))] = (
            dict(zip(group["edge_id"], group["speed"])),
            frozenset(group.loc[group["closed"], "edge_id"]),
        )
    return lookup


def _cell_id(x: Any, y: Any) -> str | None:
    """The public 1 km cell a trip starts in, named by its lower-left corner."""
    if x is None or y is None or not (math.isfinite(float(x)) and math.isfinite(float(y))):
        return None
    gx = int(math.floor(float(x) / PUBLIC_GRID_M) * PUBLIC_GRID_M)
    gy = int(math.floor(float(y) / PUBLIC_GRID_M) * PUBLIC_GRID_M)
    return f"g1km_{gx}_{gy}"
