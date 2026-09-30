"""P4 support — build mode-specific routable graphs from OSM ways.

Two graphs are built from one node/edge pass: a pedestrian graph and a private
vehicle graph. Access rules are tag-driven and explicit, because an edge that
is implicitly usable is an edge that silently invents a route.

Edge identifiers are derived from the noded geometry, so a re-run over the same
extract produces the same ids and cached route results stay valid.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, unary_union
from shapely.strtree import STRtree

# Tag-driven access rules, stated rather than inferred.
PEDESTRIAN_ALLOWED = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "pedestrian",
    "footway",
    "path",
    "steps",
    "track",
    "service",
    "cycleway",
    "road",
    "bridleway",
}
VEHICLE_ALLOWED = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "service",
    "road",
}

# Free-flow speeds in km/h by OSM highway class, mode separated.
VEHICLE_SPEED_KMH = {
    "motorway": 80,
    "motorway_link": 40,
    "trunk": 60,
    "trunk_link": 40,
    "primary": 45,
    "primary_link": 35,
    "secondary": 40,
    "secondary_link": 30,
    "tertiary": 35,
    "tertiary_link": 30,
    "unclassified": 25,
    "residential": 20,
    "living_street": 15,
    "service": 15,
    "road": 20,
}
WALK_SPEED_KMH = 4.5
WALK_SPEED_SLOW_KMH = 2.5  # reduced-mobility profile


@dataclass
class NetworkBuild:
    graph: nx.MultiGraph
    edges: gpd.GeoDataFrame
    nodes: gpd.GeoDataFrame
    stats: dict[str, Any]


def _as_linestring(geometry: Any) -> Any:
    """Reduce polygonal ways to a routable line.

    OSM tags roundabouts and pedestrian squares as closed ways, which arrive
    as polygons. Dropping them would delete real connections, so the exterior
    ring becomes the walk line.
    """
    if geometry is None or geometry.is_empty:
        return geometry
    if geometry.geom_type == "LineString":
        return geometry
    if geometry.geom_type == "Polygon":
        ring = geometry.exterior
        if not ring.is_ring:
            ring = LineString(list(ring.coords) + [ring.coords[0]])
        # The exterior is a LinearRing; a LineString is required downstream,
        # and a closed way must stay closed so it remains a routable loop.
        return LineString(list(ring.coords))
    if geometry.geom_type == "MultiLineString":
        return max(geometry.geoms, key=lambda part: part.length)
    if geometry.geom_type == "MultiPolygon":
        return max(
            (_as_linestring(part) for part in geometry.geoms),
            key=lambda part: part.length if part is not None and not part.is_empty else -1.0,
        )
    return geometry


def _clean_ways(roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    frame = roads.copy()
    if frame.empty:
        return frame
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty]
    if "highway" not in frame.columns:
        frame["highway"] = "unclassified"
    frame["highway"] = frame["highway"].fillna("unclassified").astype(str)
    frame = frame[frame["highway"] != "nan"]
    frame["geometry"] = frame.geometry.apply(_as_linestring)
    frame = frame[frame.geom_type == "LineString"]
    # Length filtering happens after projection; degrees are not a metric.
    return frame.reset_index(drop=True)


def _edge_id(geometry: LineString) -> str:
    """Stable identifier from the geometry, independent of fetch order."""
    digest = hashlib.sha256(
        f"{geometry.wkb_hex}|{round(geometry.length, 3)}".encode("utf-8")
    ).hexdigest()
    return f"e_{digest[:18]}"


def _node_id(geometry: Point) -> int:
    return int(hashlib.sha256(f"{geometry.wkb_hex}".encode("utf-8")).hexdigest()[:15], 16)


def build_network(
    roads: gpd.GeoDataFrame,
    *,
    analysis_crs: str,
    network_version: str,
    aoi_geometry=None,
) -> NetworkBuild:
    """Node the way geometry and build a walking and driving graph."""
    ways = _clean_ways(roads)
    if ways.empty:
        raise ValueError("no usable highway geometry was supplied")

    # Project before measuring: lengths must be metric, not degrees.
    projected = ways.to_crs(analysis_crs)
    if aoi_geometry is not None:
        # Accept a GeoDataFrame/GeoSeries in any CRS, or a bare shapely geometry
        # that the caller has already expressed in the analysis CRS.
        if hasattr(aoi_geometry, "to_crs") and getattr(aoi_geometry, "crs", None) is not None:
            clip = aoi_geometry.to_crs(analysis_crs)
        else:
            clip = aoi_geometry
        if hasattr(clip, "geometry"):
            clip = clip.geometry.union_all() if hasattr(clip.geometry, "union_all") else clip.geometry.unary_union
        projected = projected[projected.intersects(clip)]
        projected = projected.copy()
        projected["geometry"] = projected.geometry.intersection(clip)
        projected = projected[~projected.geometry.is_empty]
        projected = projected[projected.geom_type.isin(["LineString", "MultiLineString"])]
        if projected.empty:
            raise ValueError("no way geometry intersects the area of interest")

    # linemerge requires a MultiLineString; unary_union returns a bare
    # LineString when the ways happen to form a single chain.
    merged_input = unary_union(projected.geometry.values)
    if merged_input.geom_type == "LineString":
        merged_input = MultiLineString([merged_input])
    merged = linemerge(merged_input)
    noded = linemerge(merged) if merged.geom_type != "LineString" else merged
    if noded.geom_type == "LineString":
        lines = [noded]
    elif noded.geom_type == "MultiLineString":
        lines = list(noded.geoms)
    else:
        lines = [part for part in getattr(noded, "geoms", []) if part.geom_type == "LineString"]

    graph = nx.MultiGraph()
    edge_records: list[dict[str, Any]] = []
    geometries: list[LineString] = []

    # Attribute each noded segment back to the highway class of its source way.
    # A spatial index keeps this linear in segments instead of quadratic.
    source_geoms = list(projected.geometry)
    source_classes = [str(value) for value in projected["highway"]]
    tree = STRtree(source_geoms) if source_geoms else None

    def _class_for(segment: LineString) -> str:
        if tree is None:
            return "unclassified"
        best = "unclassified"
        best_overlap = -1.0
        for index in tree.query(segment):
            way_geom = source_geoms[int(index)]
            if way_geom.is_empty:
                continue
            overlap = segment.intersection(way_geom).length
            if overlap > best_overlap:
                best_overlap, best = overlap, source_classes[int(index)]
        return best

    for line in lines:
        if line.is_empty or line.geom_type != "LineString" or line.length < 0.5:
            continue
        coordinates = list(line.coords)
        highway_class = _class_for(line)
        for start, end in zip(coordinates[:-1], coordinates[1:]):
            start_point, end_point = Point(start), Point(end)
            length_m = start_point.distance(end_point)
            if length_m <= 0:
                continue
            edge_id = _edge_id(LineString([start, end]))
            u, v = _node_id(start_point), _node_id(end_point)
            graph.add_node(u, x=start[0], y=start[1])
            graph.add_node(v, x=end[0], y=end[1])
            graph.add_edge(
                u,
                v,
                edge_id=edge_id,
                length_m=length_m,
                highway=highway_class,
            )
            edge_records.append(
                {
                    "edge_id": edge_id,
                    "u": u,
                    "v": v,
                    "length_m": length_m,
                    "highway": highway_class,
                    "network_version": network_version,
                }
            )
            geometries.append(LineString([start, end]))

    edges = gpd.GeoDataFrame(edge_records, geometry=geometries, crs=analysis_crs)
    if edges.empty:
        raise ValueError("noding produced no edges")

    # Access and speed attributes.
    edges["walk_allowed"] = edges["highway"].isin(PEDESTRIAN_ALLOWED)
    edges["vehicle_allowed"] = edges["highway"].isin(VEHICLE_ALLOWED)
    edges["speed_walk_mps"] = np.where(edges["walk_allowed"], WALK_SPEED_KMH / 3.6, np.nan)
    edges["speed_vehicle_mps"] = [
        VEHICLE_SPEED_KMH.get(str(cls), 20) / 3.6 if allowed else np.nan
        for cls, allowed in zip(edges["highway"], edges["vehicle_allowed"])
    ]
    edges["oneway"] = edges.get(
        "oneway", pd.Series([False] * len(edges))
    ).astype(str).str.lower().isin({"yes", "1", "true"})

    node_items = list(graph.nodes(data=True))
    node_frame = gpd.GeoDataFrame(
        [{"node_id": node, "x": data["x"], "y": data["y"]} for node, data in node_items],
        geometry=[Point(data["x"], data["y"]) for _, data in node_items],
        crs=analysis_crs,
    )

    total_length_km = float(edges["length_m"].sum() / 1000.0)
    stats = {
        "network_version": network_version,
        "analysis_crs": analysis_crs,
        "edges": int(len(edges)),
        "nodes": int(len(node_frame)),
        "total_length_km": round(total_length_km, 3),
        "walk_edges": int(edges["walk_allowed"].sum()),
        "vehicle_edges": int(edges["vehicle_allowed"].sum()),
        "walk_length_km": round(float(edges.loc[edges["walk_allowed"], "length_m"].sum() / 1000.0), 3),
        "vehicle_length_km": round(
            float(edges.loc[edges["vehicle_allowed"], "length_m"].sum() / 1000.0), 3
        ),
        "highway_class_counts": {
            str(key): int(value) for key, value in edges["highway"].value_counts().items()
        },
    }
    return NetworkBuild(graph=graph, edges=edges, nodes=node_frame, stats=stats)


def edge_lookup(edges: gpd.GeoDataFrame) -> dict[str, dict[str, Any]]:
    """Index edge attributes by the identifiers used in route output."""
    lookup: dict[str, dict[str, Any]] = {}
    for row in edges.itertuples():
        lookup[row.edge_id] = {
            "length_m": float(row.length_m),
            "highway": str(row.highway),
            "walk_allowed": bool(row.walk_allowed),
            "vehicle_allowed": bool(row.vehicle_allowed),
            "speed_walk_mps": float(row.speed_walk_mps) if pd.notna(row.speed_walk_mps) else None,
            "speed_vehicle_mps": (
                float(row.speed_vehicle_mps) if pd.notna(row.speed_vehicle_mps) else None
            ),
        }
    return lookup


def largest_component(graph: nx.MultiGraph) -> set[int]:
    if graph.number_of_nodes() == 0:
        return set()
    return set(max(nx.connected_components(graph.to_undirected()), key=len))
