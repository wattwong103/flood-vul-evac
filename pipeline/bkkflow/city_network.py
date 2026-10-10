"""Vectorised network construction for city-scale road geometry.

The pilot's noder works on a few thousand ways and builds edges in a Python
loop. At metropolitan scale the same loop would run 1.7 million times, so this
module does the whole node/edge derivation with numpy: the noding itself is
GEOS (``unary_union`` + ``linemerge``), and everything after it is array work.

Identities are derived, not generated, so a re-run over the same extract
produces the same edge ids:

* a node id is its coordinate pair packed into an integer at millimetre
  precision in the analysis CRS;
* an edge id is the packed id of its two endpoints, so it is order-independent
  and independent of the order ways were read in.

Routing at this scale is handled by :class:`CityRoutingIndex`, which keeps the
graph in compressed-sparse-row form. A ``networkx`` graph of 1.7 million edges
is slow to query and expensive to hold; a CSR array plus a heap-based Dijkstra
answers the same question in a fraction of the time and memory.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any

import geopandas as gpd
import numpy as np
import shapely
from shapely.ops import linemerge, unary_union

VEHICLE_SPEED_KMH = {
    "motorway": 80, "motorway_link": 40, "trunk": 60, "trunk_link": 40,
    "primary": 45, "primary_link": 35, "secondary": 40, "secondary_link": 30,
    "tertiary": 35, "tertiary_link": 30, "unclassified": 25, "residential": 20,
    "living_street": 15, "service": 15, "road": 20,
}
WALK_SPEED_MPS = 4.5 / 3.6
from .city_method import SNAP_TOLERANCE_M  # noqa: E402

PEDESTRIAN_ALLOWED = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
    "residential", "living_street", "pedestrian", "footway", "path", "steps",
    "track", "service", "cycleway", "road", "bridleway",
}
VEHICLE_ALLOWED = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
    "residential", "living_street", "service", "road",
}

# Coordinate packing: millimetre precision is far below any network tolerance
# and keeps the packed value inside int64 for any plausible projected CRS.
COORD_SCALE = 1000.0
NODE_BIAS = 10_000_000  # keeps packed values positive


@dataclass
class CityNetwork:
    edges: gpd.GeoDataFrame
    nodes: gpd.GeoDataFrame
    stats: dict[str, Any] = field(default_factory=dict)


def _pack_nodes(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Pack coordinates into a single stable integer per node."""
    px = np.rint(np.asarray(x, dtype="float64") * COORD_SCALE).astype("int64")
    py = np.rint(np.asarray(y, dtype="float64") * COORD_SCALE).astype("int64")
    return px * NODE_BIAS + py + NODE_BIAS


def node_segments(merged: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Explode a merged MultiLineString into arrays of segment endpoints.

    Returns (x0, y0, x1, y1) for every segment that lies inside a single part.
    Pairs that straddle a part boundary are not segments and are dropped.
    """
    parts = shapely.get_parts(merged) if merged.geom_type == "MultiLineString" else [merged]
    parts = np.asarray(parts, dtype=object)
    coordinates = shapely.get_coordinates(parts)
    counts = shapely.get_num_coordinates(parts)
    if coordinates.shape[0] == 0:
        empty = np.zeros(0, dtype="float64")
        return empty, empty, empty, empty

    part_index = np.repeat(np.arange(len(parts), dtype="int64"), counts)
    flat_index = np.arange(coordinates.shape[0], dtype="int64")
    same_part = part_index[:-1] == part_index[1:]
    start_index = flat_index[:-1][same_part]
    end_index = start_index + 1

    return (
        coordinates[start_index, 0],
        coordinates[start_index, 1],
        coordinates[end_index, 0],
        coordinates[end_index, 1],
    )


def build_city_network(
    roads: gpd.GeoDataFrame,
    *,
    analysis_crs: str,
    network_version: str,
    aoi_geometry=None,
    min_length_m: float = 0.5,
) -> CityNetwork:
    """Node city-scale road geometry into a routable edge table."""
    ways = roads.copy()
    if ways.empty:
        raise ValueError("no road geometry supplied")
    if "highway" not in ways.columns:
        ways["highway"] = "unclassified"
    ways = ways[ways.geometry.notna() & ~ways.geometry.is_empty]
    ways = ways.to_crs(analysis_crs)
    if aoi_geometry is not None:
        clip = aoi_geometry
        if getattr(aoi_geometry, "crs", None) is not None and str(aoi_geometry.crs) != analysis_crs:
            clip = aoi_geometry.to_crs(analysis_crs)
        if hasattr(clip, "geometry"):
            geometry = clip.geometry
            clip = geometry.union_all() if hasattr(geometry, "union_all") else geometry.unary_union
        ways = ways[ways.geometry.intersects(clip)].copy()
        ways["geometry"] = ways.geometry.intersection(clip)
        ways = ways[~ways.geometry.is_empty]

    geometries = np.asarray(ways.geometry.values, dtype=object)
    # Closed ways arrive as polygons; reduce them to their exterior ring so
    # roundabouts and pedestrian squares stay routable.
    geometries = np.array([_as_line(geometry) for geometry in geometries], dtype=object)
    geometries = geometries[shapely.get_type_id(geometries) == 1]  # LineString
    if geometries.size == 0:
        raise ValueError("no line geometry survived cleaning")

    dissolved = unary_union(geometries)
    merged = linemerge(dissolved) if dissolved.geom_type != "LineString" else dissolved
    if merged.geom_type == "LineString":
        merged = shapely.multilinestrings(np.array([merged], dtype=object))
    elif merged.geom_type == "MultiLineString":
        pass
    else:
        merged = shapely.multilinestrings(
            np.array([part for part in shapely.get_parts(merged)
                      if shapely.get_type_id(part) == 1], dtype=object)
        )

    x0, y0, x1, y1 = node_segments(merged)
    lengths = np.hypot(x1 - x0, y1 - y0)
    keep = lengths >= min_length_m
    x0, y0, x1, y1, lengths = x0[keep], y0[keep], x1[keep], y1[keep], lengths[keep]

    start_nodes = _pack_nodes(x0, y0)
    end_nodes = _pack_nodes(x1, y1)
    # Drop zero-length self loops that survived rounding.
    non_loop = start_nodes != end_nodes
    x0, y0, x1, y1 = x0[non_loop], y0[non_loop], x1[non_loop], y1[non_loop]
    lengths = lengths[non_loop]
    start_nodes, end_nodes = start_nodes[non_loop], end_nodes[non_loop]

    # Classify each segment by the highway class of the nearest source way.
    segment_coords = np.column_stack([x0, y0, x1, y1]).reshape(-1, 2, 2)
    highway = _classify_segments(ways, shapely.linestrings(segment_coords))

    node_ids = np.unique(np.concatenate([start_nodes, end_nodes]))
    node_index = np.searchsorted(node_ids, np.concatenate([start_nodes, end_nodes]))
    half = len(start_nodes)
    u = node_index[:half].astype("int64")
    v = node_index[half:].astype("int64")

    edge_ids = _edge_ids(node_ids[u], node_ids[v])
    edges = gpd.GeoDataFrame(
        {
            "edge_id": edge_ids,
            "u": u,
            "v": v,
            "length_m": np.round(lengths, 3),
            "highway": highway,
            "network_version": network_version,
        },
        geometry=shapely.linestrings(segment_coords),
        crs=analysis_crs,
    )
    edges["walk_allowed"] = edges["highway"].isin(PEDESTRIAN_ALLOWED).to_numpy()
    vehicle_mask = edges["highway"].isin(VEHICLE_ALLOWED).to_numpy()
    edges["vehicle_allowed"] = vehicle_mask
    edges["speed_walk_mps"] = np.where(edges["walk_allowed"].to_numpy(), WALK_SPEED_MPS, np.nan)
    vehicle_speeds = np.array(
        [VEHICLE_SPEED_KMH.get(str(cls), 20) / 3.6 for cls in edges["highway"]], dtype="float64"
    )
    edges["speed_vehicle_mps"] = np.where(vehicle_mask, vehicle_speeds, np.nan)

    node_frame = gpd.GeoDataFrame(
        {"node_id": node_ids},
        geometry=gpd.points_from_xy(
            (node_ids // NODE_BIAS) / COORD_SCALE, (node_ids % NODE_BIAS) / COORD_SCALE - NODE_BIAS / COORD_SCALE
        ),
        crs=analysis_crs,
    )

    stats = {
        "network_version": network_version,
        "analysis_crs": analysis_crs,
        "source_ways": int(len(ways)),
        "edges": int(len(edges)),
        "nodes": int(len(node_frame)),
        "total_length_km": round(float(lengths.sum() / 1000.0), 2),
        "walk_edges": int(edges["walk_allowed"].sum()),
        "vehicle_edges": int(vehicle_mask.sum()),
        "walk_length_km": round(
            float(lengths[edges["walk_allowed"].to_numpy()].sum() / 1000.0), 2
        ),
        "vehicle_length_km": round(float(lengths[vehicle_mask].sum() / 1000.0), 2),
        "highway_class_counts": {
            str(key): int(value) for key, value in edges["highway"].value_counts().items()
        },
    }
    return CityNetwork(edges=edges, nodes=node_frame, stats=stats)


def _as_line(geometry: Any) -> Any:
    if geometry.geom_type == "LineString":
        return geometry
    if geometry.geom_type in {"LinearRing", "Polygon"}:
        ring = (
            geometry
            if geometry.geom_type == "LinearRing"
            else shapely.get_exterior_ring(geometry)
        )
        # shapely returns a LinearRing (type 2); the caller filters on
        # LineString (type 1), so rebuild it explicitly.
        return shapely.linestrings(np.asarray(ring.coords))
    if geometry.geom_type in {"MultiLineString", "MultiPolygon", "GeometryCollection"}:
        parts = [part for part in shapely.get_parts(geometry) if part.geom_type in {"LineString", "LinearRing"}]
        if not parts:
            return shapely.linestrings(np.zeros((0, 2)))
        return max(parts, key=lambda part: shapely.length(part))
    return geometry


def _classify_segments(ways: gpd.GeoDataFrame, segments: np.ndarray) -> np.ndarray:
    """Assign a highway class to each segment from its nearest source way."""
    from shapely.strtree import STRtree

    classes = np.asarray(ways["highway"].astype(str).to_numpy(), dtype=object)
    way_geoms = np.asarray(ways.geometry.values, dtype=object)
    tree = STRtree(way_geoms)
    result = np.full(len(segments), "unclassified", dtype=object)
    if len(segments) == 0 or len(way_geoms) == 0:
        return result

    pairs = tree.query(segments, predicate="intersects")
    if len(pairs):
        seg_index, way_index = pairs[0], pairs[1]
        lengths = shapely.length(shapely.intersection(segments[seg_index], way_geoms[way_index]))
        # Longest overlap wins the classification for each segment.
        order = np.lexsort((-lengths, seg_index))
        seg_sorted, class_sorted = seg_index[order], classes[way_index[order]]
        first = np.ones(len(seg_sorted), dtype=bool)
        first[1:] = seg_sorted[1:] != seg_sorted[:-1]
        result[seg_sorted[first]] = class_sorted[first]
    return result


def _edge_ids(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Order-independent, geometry-derived edge identifiers."""
    low = np.minimum(u, v)
    high = np.maximum(u, v)
    packed = low.astype("object") * 10_000_000_000_000 + high.astype("object")
    return np.array([f"e_{int(value):x}" for value in packed], dtype=object)


class CityRoutingIndex:
    """CSR routing index with heap-based Dijkstra.

    Holds the graph as flat arrays rather than a ``networkx`` structure. At
    metropolitan scale that is the difference between a few hundred megabytes
    and a few gigabytes, and Dijkstra from a destination then gives travel time
    to *every* origin in one pass instead of one pass per person.
    """

    def __init__(self, edges: gpd.GeoDataFrame, allowed_mask: np.ndarray, speed_mps: np.ndarray,
                 *, anchor_mask: np.ndarray | None = None) -> None:
        subset = edges[allowed_mask]
        anchors = edges[allowed_mask if anchor_mask is None else anchor_mask]
        self.speed_mps = np.asarray(speed_mps[allowed_mask], dtype="float64")
        self.length_m = np.asarray(subset["length_m"].to_numpy(), dtype="float64")
        self.edge_ids = subset["edge_id"].to_numpy()

        nodes = np.unique(np.concatenate([anchors["u"].to_numpy(), anchors["v"].to_numpy()]))
        if not np.isin(subset[["u", "v"]].to_numpy(), nodes).all():
            raise ValueError("every open edge must belong to the anchor graph")
        self.node_ids = nodes
        index = np.searchsorted(nodes, np.concatenate([subset["u"].to_numpy(), subset["v"].to_numpy()]))
        half = len(subset)
        source = index[:half].astype("int64")
        target = index[half:].astype("int64")
        costs = self.length_m / np.maximum(self.speed_mps, 1e-6)

        # Both directions: a street network is traversable either way unless
        # OSM says otherwise, and oneway handling is a declared simplification.
        src = np.concatenate([source, target])
        dst = np.concatenate([target, source])
        cost = np.concatenate([costs, costs])
        edge = np.concatenate([np.arange(half), np.arange(half)])

        order = np.argsort(src, kind="stable")
        src, dst, cost, edge = src[order], dst[order], cost[order], edge[order]
        counts = np.bincount(src, minlength=len(nodes))
        self.indptr = np.zeros(len(nodes) + 1, dtype="int64")
        np.cumsum(counts, out=self.indptr[1:])
        self.indices = dst
        self.edge_costs = cost
        self.edge_ref = edge
        # Node coordinates come from the edge geometry, never from unpacking the
        # node id. The packed id is millimetre-precision in the analysis CRS, so
        # recovering coordinates from it needs a modulus larger than the
        # coordinate range, which overflows int64 for full UTM. Deriving the
        # coordinates directly is exact and costs nothing.
        coordinates = np.zeros((len(nodes), 2), dtype="float64")
        anchor_u = np.searchsorted(nodes, anchors["u"].to_numpy())
        anchor_v = np.searchsorted(nodes, anchors["v"].to_numpy())
        for u, v, geometry in zip(anchor_u, anchor_v, anchors.geometry):
            coordinates_pair = shapely.get_coordinates(geometry)
            coordinates[u] = coordinates_pair[0]
            coordinates[v] = coordinates_pair[-1]
        self.coords = coordinates
        # Endpoints in index space, so a traced path can be walked back.
        self.edge_source = source
        self.edge_target = target

    @property
    def node_count(self) -> int:
        return len(self.node_ids)

    @property
    def edge_count(self) -> int:
        return len(self.edge_ids)

    def nearest_node(self, x: float, y: float, coords: np.ndarray) -> int | None:
        if not len(coords):
            return None
        distances = np.hypot(coords[:, 0] - x, coords[:, 1] - y)
        index = int(np.argmin(distances))
        if distances[index] > SNAP_TOLERANCE_M:
            return None
        return index

    def dijkstra(self, source: int, *, cutoff: float | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Single-source shortest travel times over the whole network.

        Returns (costs, predecessors-as-edge-refs). One call covers every origin
        in the city, which is the only tractable approach at this scale.
        """
        node_count = self.node_count
        costs = np.full(node_count, np.inf, dtype="float64")
        prev_edge = np.full(node_count, -1, dtype="int64")
        if source < 0 or source >= node_count:
            return costs, prev_edge
        costs[source] = 0.0
        indptr, indices, edge_costs = self.indptr, self.indices, self.edge_costs
        queue: list[tuple[float, int]] = [(0.0, source)]
        while queue:
            cost, node = heapq.heappop(queue)
            if cost > costs[node]:
                continue
            if cutoff is not None and cost > cutoff:
                break
            for position in range(indptr[node], indptr[node + 1]):
                neighbour = indices[position]
                step = cost + edge_costs[position]
                if cutoff is not None and step > cutoff:
                    continue
                if step < costs[neighbour]:
                    costs[neighbour] = step
                    prev_edge[neighbour] = self.edge_ref[position]
                    heapq.heappush(queue, (step, int(neighbour)))
        return costs, prev_edge

    def trace_path(self, source: int, target: int, prev_edge: np.ndarray) -> list[int] | None:
        """Walk predecessors back from target to source, returning edge refs."""
        if source == target:
            return []
        path: list[int] = []
        node = target
        guard = 0
        limit = self.node_count * 2
        while node != source and guard < limit:
            reference = int(prev_edge[node])
            if reference < 0:
                return None
            path.append(reference)
            node = self._other_end(reference, node)
            guard += 1
        if node != source:
            return None
        path.reverse()
        return path

    def _other_end(self, edge_index: int, node: int) -> int:
        """Step from node along edge_index to the other endpoint."""
        source = int(self.edge_source[edge_index])
        target = int(self.edge_target[edge_index])
        return target if node == source else source

    def edge_geometry_xy(self, edge_index: int) -> np.ndarray:
        source = int(self.edge_source[edge_index])
        target = int(self.edge_target[edge_index])
        return np.vstack([self.coords[source], self.coords[target]])
