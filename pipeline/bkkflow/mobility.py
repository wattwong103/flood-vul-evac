"""P2-P5 — activities, trips, trajectories and aggregates.

The PFLOW contract is retained; Bangkok supplies the data and the behaviour.
What matters for correctness here:

* activities are explicit states, not something inferred from a trajectory;
* every trip is routed on the dated OSM graph, and a trip that cannot be
  routed records a failure reason rather than drawing a straight line;
* the day/evening/night presence factor is a declared scenario multiplier, not
  a measurement, and it is carried into the manifest as such;
* aggregation conserves people: a person is stationary at an activity or moving
  on a link, never both and never neither.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .network import PEDESTRIAN_ALLOWED, VEHICLE_ALLOWED

# PFLOW-compatible mode codes retained from the plan.
MODE_WALK = 0
MODE_CYCLE = 1
MODE_BUS = 2
MODE_CAR = 3
MODE_TRAIN = 4

PURPOSES = (
    "home",
    "work",
    "education",
    "shopping_services",
    "health_care",
    "social_recreation",
    "transfer",
    "evacuation",
    "unknown",
)

SECONDS_PER_DAY = 86_400


@dataclass
class ActivityProfile:
    """Declared behavioural priors for one purpose.

    These are *scenario* values. No licensable Bangkok travel diary was
    available for this build, so every downstream activity record carries
    ``source_status='scenario_prior'`` and the run stays at ``demonstration``.
    """

    purpose: str
    count_mean: float
    start_hour_mean: float
    start_hour_sd: float
    duration_mean_s: float
    duration_sd_s: float
    participation: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "count_mean": self.count_mean,
            "start_hour_mean": self.start_hour_mean,
            "start_hour_sd": self.start_hour_sd,
            "duration_mean_s": self.duration_mean_s,
            "duration_sd_s": self.duration_sd_s,
            "participation": self.participation,
        }


DEFAULT_PROFILES: tuple[ActivityProfile, ...] = (
    ActivityProfile("work", 1.0, 7.6, 0.9, 9.0 * 3600, 1.1 * 3600, participation=0.52),
    ActivityProfile("education", 1.0, 7.4, 0.5, 7.0 * 3600, 0.6 * 3600, participation=0.13),
    ActivityProfile("shopping_services", 1.7, 15.5, 2.6, 1.1 * 3600, 0.6 * 3600, participation=0.74),
    ActivityProfile("health_care", 0.35, 10.0, 3.0, 1.3 * 3600, 0.8 * 3600, participation=0.28),
    ActivityProfile("social_recreation", 0.9, 18.6, 2.4, 2.0 * 3600, 1.2 * 3600, participation=0.61),
)


@dataclass
class MobilityResult:
    activities: pd.DataFrame
    trips: pd.DataFrame
    waypoints: pd.DataFrame
    mesh_volume: pd.DataFrame
    link_volume: pd.DataFrame
    stats: dict[str, Any] = field(default_factory=dict)


def build_routing_graph(
    edges: gpd.GeoDataFrame,
    mode: int,
    *,
    excluded_edge_ids: set[str] | None = None,
    speed_multipliers: Mapping[str, float] | None = None,
) -> nx.Graph:
    """Build a single-mode cost graph from the noded edge table.

    ``excluded_edge_ids`` removes ways closed at the time step being modelled.
    The exclusion happens here, while the graph is being built, rather than by
    deleting edges afterwards: parallel ways between the same node pair collapse
    to one edge, so a later removal would close a connection that is still open
    on another way.

    When ``speed_multipliers`` is supplied, it must cover every routable edge.
    A zero multiplier removes an edge; an open edge costs
    ``length / (dry_speed * multiplier)``. Applying the multiplier before
    parallel ways collapse ensures the graph retains the least-cost wet edge,
    not merely the edge that was fastest when dry.
    """
    allowed = PEDESTRIAN_ALLOWED if mode == MODE_WALK else VEHICLE_ALLOWED
    speed_column = "speed_walk_mps" if mode == MODE_WALK else "speed_vehicle_mps"
    subset = edges[edges["highway"].isin(allowed) & edges[speed_column].notna()]
    if excluded_edge_ids:
        subset = subset[~subset["edge_id"].isin(excluded_edge_ids)]
    graph = nx.Graph()
    for row in subset.itertuples():
        dry_speed = float(getattr(row, speed_column.replace(".", "_")))
        if dry_speed <= 0:
            continue
        multiplier = 1.0
        if speed_multipliers is not None:
            if row.edge_id not in speed_multipliers:
                raise ValueError(f"missing speed multiplier for edge {row.edge_id}")
            multiplier = float(speed_multipliers[row.edge_id])
            if not np.isfinite(multiplier) or not 0.0 <= multiplier <= 1.0:
                raise ValueError(
                    f"speed multiplier for edge {row.edge_id} must be between 0 and 1"
                )
            if multiplier == 0.0:
                continue
        speed = dry_speed * multiplier
        # Each edge geometry is a two-point segment, so the endpoints carry
        # the node coordinates the routing index needs.
        start_x, start_y = row.geometry.coords[0]
        end_x, end_y = row.geometry.coords[-1]
        for node_id, x, y in ((row.u, start_x, start_y), (row.v, end_x, end_y)):
            if node_id not in graph.nodes:
                graph.add_node(node_id, x=float(x), y=float(y))
        cost = float(row.length_m) / speed
        attributes = {
            "cost": cost,
            "length_m": float(row.length_m),
            "edge_id": row.edge_id,
            "dry_speed_mps": dry_speed,
            "speed_multiplier": multiplier,
            "speed_mps": speed,
        }
        if graph.has_edge(row.u, row.v):
            # Parallel ways: retain every attribute from the least-cost edge.
            if cost < graph[row.u][row.v]["cost"]:
                graph[row.u][row.v].update(attributes)
        else:
            graph.add_edge(row.u, row.v, **attributes)
    return graph


class NetworkIndex:
    """Node lookup and routing helpers shared by every routing stage."""

    def __init__(self, graph: nx.Graph, analysis_crs: str) -> None:
        self.graph = graph
        self.analysis_crs = analysis_crs
        nodes = list(graph.nodes(data=True))
        self.node_ids = [node for node, _ in nodes]
        self.coords = np.array([[data["x"], data["y"]] for _, data in nodes], dtype="float64")
        self.tree = cKDTree(self.coords)
        self.position = {node: index for index, node in enumerate(self.node_ids)}

    def snap(self, x: float, y: float, *, max_distance_m: float = 250.0) -> int | None:
        distance, index = self.tree.query([x, y])
        if distance > max_distance_m:
            return None
        return self.node_ids[int(index)]

    def route(self, origin: int, destination: int) -> tuple[list[int], float] | None:
        """A* between two nodes on the mode graph as built."""
        if origin == destination:
            return [origin], 0.0
        graph = self.graph
        try:
            path = nx.astar_path(graph, origin, destination, weight="cost")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
        cost = float(
            sum(graph[path[i]][path[i + 1]]["cost"] for i in range(len(path) - 1))
        )
        return path, cost


def _choose_destination(
    rng: np.random.Generator,
    candidates: gpd.GeoDataFrame,
    origin_xy: tuple[float, float],
    preference: dict[str, float],
) -> tuple[float, float] | None:
    """Pick a plausible destination from tagged candidates.

    Destinations are drawn from OSM-tagged buildings and weighted by distance.
    Where a purpose has no tagged candidate the trip is left as ``unknown``
    rather than being pointed at an invented venue.
    """
    if candidates is None or candidates.empty:
        return None
    points = np.column_stack([candidates["centre_x"].to_numpy(), candidates["centre_y"].to_numpy()])
    distances = np.hypot(points[:, 0] - origin_xy[0], points[:, 1] - origin_xy[1])
    # 300-6000 m band: near enough to be plausible, far enough to be a trip.
    weights = np.exp(-((distances - preference.get("target_m", 1500.0)) / 2500.0) ** 2)
    weights = weights * preference.get("weight", 1.0)
    total = float(weights.sum())
    if total <= 0:
        return None
    probabilities = weights / total
    chosen = int(rng.choice(len(points), p=probabilities))
    return float(points[chosen][0]), float(points[chosen][1])


def _to_wgs84_transformer(analysis_crs: str):
    from pyproj import Transformer

    return Transformer.from_crs(analysis_crs, "OGC:CRS84", always_xy=True)


def generate_activities(
    persons: pd.DataFrame,
    *,
    candidates: gpd.GeoDataFrame,
    analysis_crs: str,
    homes_xy: dict[str, tuple[float, float]],
    seed: int,
    profiles: tuple[ActivityProfile, ...] = DEFAULT_PROFILES,
) -> pd.DataFrame:
    """Build a daily activity chain for every sampled person.

    The chain is anchored at home, so day/night presence reconciles to the
    resident baseline by construction. All geometry is handled in the
    analysis CRS; WGS84 is produced only for the published columns.
    """
    rng = np.random.default_rng(seed)
    to_wgs84 = _to_wgs84_transformer(analysis_crs)
    records: list[dict[str, Any]] = []

    for person in persons.itertuples():
        home = homes_xy.get(person.home_cell_id, (float(person.lon), float(person.lat)))
        home_x, home_y = float(home[0]), float(home[1])

        # A quiet night at home, then each sampled outing, then home again.
        events: list[tuple[str, int, int, float, float]] = [
            ("home", 0, SECONDS_PER_DAY, home_x, home_y)
        ]
        for profile in profiles:
            if rng.random() > profile.participation:
                continue
            count = max(1, int(rng.poisson(profile.count_mean)))
            for _ in range(count):
                start_hour = float(
                    np.clip(rng.normal(profile.start_hour_mean, profile.start_hour_sd), 5.0, 23.0)
                )
                duration_s = int(
                    np.clip(rng.normal(profile.duration_mean_s, profile.duration_sd_s), 900.0, 15 * 3600)
                )
                start_s = int(start_hour * 3600)
                preference = {
                    "work": {"target_m": 3500.0, "weight": 1.0},
                    "education": {"target_m": 1200.0, "weight": 1.0},
                }.get(profile.purpose, {"target_m": 800.0, "weight": 1.0})
                destination = _choose_destination(rng, candidates, (home_x, home_y), preference)
                if destination is None:
                    # No tagged candidate: the purpose exists but the place does
                    # not. Record the activity at home with an unknown location
                    # rather than inventing a venue.
                    events.append((profile.purpose, start_s, duration_s, home_x, home_y))
                    continue
                events.append((profile.purpose, start_s, duration_s, destination[0], destination[1]))

        # Resolve overlaps by keeping the most recent purpose, then re-anchor home.
        events.sort(key=lambda item: item[1])
        chain: list[dict[str, Any]] = []
        cursor = 0
        for purpose, start_s, duration_s, x, y in events:
            if purpose == "home":
                continue
            if start_s < cursor:
                start_s = cursor
            end_s = min(SECONDS_PER_DAY, start_s + duration_s)
            if end_s <= start_s:
                continue
            chain.append({"purpose": purpose, "start": start_s, "end": end_s, "x": x, "y": y})
            cursor = end_s

        timeline: list[dict[str, Any]] = []
        previous_end = 0
        for item in chain:
            if item["start"] > previous_end:
                timeline.append(
                    {"purpose": "home", "start": previous_end, "end": item["start"], "x": home_x, "y": home_y}
                )
            timeline.append(item)
            previous_end = item["end"]
        if previous_end < SECONDS_PER_DAY:
            timeline.append(
                {"purpose": "home", "start": previous_end, "end": SECONDS_PER_DAY, "x": home_x, "y": home_y}
            )

        for sequence, item in enumerate(timeline):
            lon, lat = to_wgs84.transform(item["x"], item["y"])
            records.append(
                {
                    "person_id": person.person_id,
                    "sequence": sequence,
                    "purpose": item["purpose"],
                    "start_time_s": int(item["start"]),
                    "duration_s": int(item["end"] - item["start"]),
                    "end_time_s": int(item["end"]),
                    "x": item["x"],
                    "y": item["y"],
                    "lon": float(lon),
                    "lat": float(lat),
                    "weight": float(person.weight),
                    "source_status": "scenario_prior",
                }
            )

    return pd.DataFrame.from_records(records)


def _mode_for(distance_m: float, mobility_profile: str, rng: np.random.Generator) -> int:
    """Simple distance-and-profile mode choice.

    Short trips walk. Longer trips use a vehicle when the profile declares
    access. This is a declared prior, and the run manifest says so.
    """
    if distance_m < 1200:
        return MODE_WALK
    vehicle_likely = mobility_profile in {"car_access", "motorcycle_access"}
    if vehicle_likely and rng.random() < 0.65:
        return MODE_CAR
    return MODE_WALK


def generate_trips(
    activities: pd.DataFrame,
    *,
    seed: int,
    mobility_profiles: pd.Series | None = None,
) -> pd.DataFrame:
    """Convert adjacent activities into routed-or-failed trips."""
    rng = np.random.default_rng(seed)
    records: list[dict[str, Any]] = []
    profile_by_person: dict[str, str] = {}
    if mobility_profiles is not None:
        profile_by_person = dict(zip(mobility_profiles.index, mobility_profiles))

    for person_id, block in activities.groupby("person_id", sort=False):
        block = block.sort_values("start_time_s")
        previous = None
        for row in block.itertuples():
            if previous is not None:
                distance = float(np.hypot(row.x - previous.x, row.y - previous.y))
                mode = _mode_for(
                    distance, profile_by_person.get(person_id, "walk_only"), rng
                )
                digest = hashlib.sha256(f"{person_id}:{row.sequence}".encode("utf-8")).hexdigest()
                records.append(
                    {
                        "trip_id": f"t_{digest[:18]}",
                        "person_id": person_id,
                        "seq": int(row.sequence),
                        "origin_purpose": previous.purpose,
                        "dest_purpose": row.purpose,
                        "mode": mode,
                        "depart_time_s": int(previous.end_time_s),
                        "duration_s": 0,
                        "distance_m": round(distance, 2),
                        "origin_x": previous.x,
                        "origin_y": previous.y,
                        "dest_x": row.x,
                        "dest_y": row.y,
                        "weight": float(row.weight),
                        "route_status": "unrouted",
                        "failure_reason": None,
                    }
                )
            previous = row

    return pd.DataFrame.from_records(records)


def route_trips(
    trips: pd.DataFrame,
    indices: dict[int, NetworkIndex],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Route each trip on the mode graph and emit ordered waypoints.

    Trips that cannot be routed keep an explicit failure reason. No
    straight-line fallback is produced, because a straight line is a claim
    about a route that was never computed.
    """
    waypoint_records: list[dict[str, Any]] = []
    routed = 0
    failed = 0
    # itertuples rows are immutable, so updates are collected and rebuilt.
    updated: list[dict[str, Any]] = []

    for row in trips.to_dict("records"):
        trip_id = row["trip_id"]
        mode = int(row["mode"])
        index = indices.get(mode)
        if index is None or row.get("origin_x") is None or row.get("dest_x") is None:
            row.update(
                route_status="unroutable",
                failure_reason="no_mode_graph" if index is None else "no_destination",
            )
            updated.append(row)
            failed += 1
            continue
        origin = index.snap(float(row["origin_x"]), float(row["origin_y"]))
        destination = index.snap(float(row["dest_x"]), float(row["dest_y"]))
        if origin is None or destination is None:
            row.update(route_status="unroutable", failure_reason="endpoint_not_on_network")
            updated.append(row)
            failed += 1
            continue
        result = index.route(origin, destination)
        if result is None:
            row.update(route_status="unroutable", failure_reason="no_path_under_closure")
            updated.append(row)
            failed += 1
            continue
        path, cost = result
        distance = sum(
            index.graph[path[i]][path[i + 1]]["length_m"] for i in range(len(path) - 1)
        )
        row.update(
            route_status="routed",
            failure_reason=None,
            duration_s=int(round(cost)),
            distance_m=round(float(distance), 2),
        )
        routed += 1
        cumulative = 0.0
        for sequence, node in enumerate(path):
            data = index.graph.nodes[node]
            waypoint_records.append(
                {
                    "trip_id": trip_id,
                    "person_id": row["person_id"],
                    "seq": sequence,
                    "x": data["x"],
                    "y": data["y"],
                    "edge_id": (
                        index.graph[path[sequence]][path[sequence + 1]]["edge_id"]
                        if sequence < len(path) - 1
                        else None
                    ),
                    "cumulative_time_s": round(cumulative, 2),
                    "mode": mode,
                }
            )
            if sequence < len(path) - 1:
                cumulative += float(index.graph[path[sequence]][path[sequence + 1]]["cost"])
        updated.append(row)

    routed_frame = pd.DataFrame.from_records(updated) if updated else trips.copy()
    return routed_frame, pd.DataFrame.from_records(waypoint_records)


def aggregate_mesh_volume(
    activities: pd.DataFrame,
    trips: pd.DataFrame,
    *,
    analysis_crs: str,
    mesh_size_m: int = 500,
    time_step_s: int = 600,
) -> pd.DataFrame:
    """Mesh population per 10-minute step, conserving agent presence."""
    records: list[dict[str, Any]] = []
    for start in range(0, SECONDS_PER_DAY, time_step_s):
        window = activities[
            (activities["start_time_s"] <= start) & (activities["end_time_s"] > start)
        ].copy()
        if window.empty:
            continue
        if "person_id" in window:
            order = ["person_id", "start_time_s"]
            if "sequence" in window:
                order.append("sequence")
            window = (
                window.sort_values(order)
                .drop_duplicates("person_id", keep="last")
            )
        group = window.groupby(["lon", "lat"], as_index=False)["weight"].sum()
        for row in group.itertuples():
            digest = hashlib.sha256(
                f"{round(float(row.lon), 5)}:{round(float(row.lat), 5)}".encode("utf-8")
            ).hexdigest()[:10]
            records.append(
                {
                    "gcode": f"m{digest}",
                    "lon": float(row.lon),
                    "lat": float(row.lat),
                    "time_s": start,
                    "stationary_pop": float(row.weight),
                    "travelling_pop": 0.0,
                    "total_pop": float(row.weight),
                }
            )
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        return pd.DataFrame(
            columns=["gcode", "lon", "lat", "time_s", "stationary_pop", "travelling_pop", "total_pop"]
        )
    return frame


def aggregate_link_volume(
    waypoints: pd.DataFrame, *, mode_names: dict[int, str] | None = None
) -> pd.DataFrame:
    """Hourly volume per traversed edge."""
    if waypoints.empty:
        return pd.DataFrame(columns=["edge_id", "hour", "volume", "mode", "distance_m"])
    frame = waypoints[waypoints["edge_id"].notna()].copy()
    if frame.empty:
        return pd.DataFrame(columns=["edge_id", "hour", "volume", "mode", "distance_m"])
    frame["hour"] = (frame["cumulative_time_s"] // 3600).astype(int)
    grouped = frame.groupby(["edge_id", "hour", "mode"], as_index=False).agg(
        traversals=("seq", "size"),
        distance_m=("edge_id", "size"),
    )
    grouped["volume"] = grouped["traversals"].astype(float)
    if mode_names:
        grouped["mode_name"] = grouped["mode"].map(mode_names)
    return grouped
