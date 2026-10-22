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
#: A re-route no slower than this is the same trip, not a detour.
DETOUR_TOLERANCE_S = 1e-6

COLUMNS = [
    "trip_id", "mode", "dest_purpose", "depart_time_s", "state_time_s", "origin_cell",
    "weight", "outcome", "dry_time_s", "flood_time_s", "extra_time_s", "blocking_edge_id",
]

# (state time, mode) -> (speed multiplier per edge, closed edge ids)
_StateKey = tuple[int, int]
_State = tuple[dict[str, float], frozenset[str]]


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
    """One row per trip with its outcome under the flood (see module docstring)."""
    if trips.empty:
        return pd.DataFrame(columns=COLUMNS)
    router = _Router(edges, analysis_crs, dict(dry_indices or {}))
    routes = _route_edges(waypoints)
    states = _state_lookup(edge_states)
    state_times = np.array(sorted({time for time, _ in states}), dtype="int64")
    records = []
    for trip in trips.to_dict("records"):
        record = _base_record(trip)
        record.update(_outcome(trip, routes, states, state_times, window, router))
        records.append(record)
    return pd.DataFrame.from_records(records, columns=COLUMNS)


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
          "blocking_edge_id": None}


def _outcome(
    trip: dict[str, Any],
    routes: dict[str, tuple[list[str], float]],
    states: dict[_StateKey, _State],
    state_times: np.ndarray,
    window: tuple[int, int],
    router: "_Router",
) -> dict[str, Any]:
    if trip.get("route_status") != "routed":
        return {**_EMPTY, "outcome": "not_routed_dry"}
    depart, mode = int(trip["depart_time_s"]), int(trip["mode"])
    position = int(np.searchsorted(state_times, depart, side="right")) - 1
    if not window[0] <= depart <= window[1] or position < 0:
        return {**_EMPTY, "outcome": "outside_flood_window"}
    state_time = int(state_times[position])
    speeds, closed = states.get((state_time, mode), ({}, frozenset()))
    route, stored_cost = routes.get(trip["trip_id"], ([], float(trip["duration_s"])))
    impacted = [edge for edge in route if edge in closed or speeds.get(edge, 1.0) < 1.0]
    base = {**_EMPTY, "state_time_s": state_time, "dry_time_s": stored_cost}
    if not impacted:
        return {**base, "outcome": "unaffected", "flood_time_s": stored_cost, "extra_time_s": 0.0}

    blocking = next((edge for edge in impacted if edge in closed), impacted[0])
    flood_cost = router.flood_cost(trip, (state_time, mode), speeds, closed)
    if flood_cost is None:
        return {**base, "outcome": "no_route", "blocking_edge_id": blocking}
    extra = flood_cost - stored_cost
    if extra <= DETOUR_TOLERANCE_S:
        return {**base, "outcome": "unaffected", "flood_time_s": stored_cost, "extra_time_s": 0.0}
    return {**base, "outcome": "detour", "flood_time_s": flood_cost, "extra_time_s": extra,
            "blocking_edge_id": blocking}


class _Router:
    """Dry snapping and flooded graphs, built once per mode and state time."""

    def __init__(self, edges: gpd.GeoDataFrame, analysis_crs: str,
                 dry: dict[int, mobility_module.NetworkIndex]) -> None:
        self.edges, self.analysis_crs, self.dry = edges, analysis_crs, dry
        self.flooded: dict[_StateKey, Any] = {}

    def flood_cost(self, trip: dict[str, Any], key: _StateKey,
                   speeds: dict[str, float], closed: frozenset[str]) -> float | None:
        """Least travel time on the flooded graph, or None when there is no way."""
        import networkx as nx

        mode = key[1]
        if mode not in self.dry:
            self.dry[mode] = _index(mobility_module.build_routing_graph(self.edges, mode), self.analysis_crs)
        dry = self.dry[mode]
        if dry is None:
            return None
        # Snap on the dry graph, as the dry routing did, so both use the same ends.
        origin = dry.snap(float(trip["origin_x"]), float(trip["origin_y"]))
        destination = dry.snap(float(trip["dest_x"]), float(trip["dest_y"]))
        if origin is None or destination is None:
            return None
        if key not in self.flooded:
            multipliers = {edge: 0.0 if edge in closed else value for edge, value in speeds.items()}
            self.flooded[key] = mobility_module.build_routing_graph(
                self.edges, mode, speed_multipliers=multipliers
            )
        try:
            cost, _ = nx.bidirectional_dijkstra(self.flooded[key], origin, destination, weight="cost")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
        return float(cost)


def _index(graph: Any, analysis_crs: str) -> mobility_module.NetworkIndex | None:
    """A routing index, or None when every edge of the mode is closed."""
    if graph.number_of_nodes() == 0:
        return None
    return mobility_module.NetworkIndex(graph, analysis_crs)


def _route_edges(waypoints: pd.DataFrame) -> dict[str, tuple[list[str], float]]:
    """Each trip's dry route: its ordered edge ids and its stored travel time.

    The last waypoint's ``cumulative_time_s`` is the dry route's cost on the
    same graph and weights, so the dry route is never searched for again.
    """
    if waypoints.empty or "edge_id" not in waypoints.columns:
        return {}
    ordered = waypoints.sort_values(["trip_id", "seq"], kind="stable")
    routes: dict[str, tuple[list[str], float]] = {}
    for trip_id, group in ordered.groupby("trip_id", sort=False):
        edges = [edge for edge in group["edge_id"] if isinstance(edge, str) and edge]
        routes[trip_id] = (edges, float(group["cumulative_time_s"].max()))
    return routes


def _state_lookup(edge_states: pd.DataFrame) -> dict[_StateKey, _State]:
    lookup: dict[_StateKey, _State] = {}
    for (time_s, mode), group in edge_states.groupby(["time_s", "mode"], sort=True):
        closed_flags = group["closed"].fillna(False).astype(bool)
        lookup[(int(time_s), int(mode))] = (
            dict(zip(group["edge_id"], group["speed_multiplier"].astype(float))),
            frozenset(group.loc[closed_flags, "edge_id"]),
        )
    return lookup


def _cell_id(x: Any, y: Any) -> str | None:
    """The public 1 km cell a trip starts in, named by its lower-left corner."""
    if x is None or y is None or not (math.isfinite(float(x)) and math.isfinite(float(y))):
        return None
    gx = int(math.floor(float(x) / PUBLIC_GRID_M) * PUBLIC_GRID_M)
    gy = int(math.floor(float(y) / PUBLIC_GRID_M) * PUBLIC_GRID_M)
    return f"g1km_{gx}_{gy}"
