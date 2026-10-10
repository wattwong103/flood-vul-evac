"""OpenStreetMap ingestion through the Overpass API.

OSM supplies the routable network, building footprints, and the water features
that constrain flooding. Everything fetched here is ODbL 1.0 and requires
attribution in any published product.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Point, Polygon, shape
from shapely.ops import unary_union

from ..http import HttpClient
from ..util import CURATED_DIR, REPO_ROOT, ensure_dir, utc_now_iso

SOURCE_ID = "osm-thailand-geofabrik"


@dataclass
class FetchRecord:
    """Provenance for one Overpass extract."""

    source_id: str
    query_sha256: str
    content_sha256: str
    retrieved_at: str
    feature_count: int
    bbox: tuple[float, float, float, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "query_sha256": self.query_sha256,
            "content_sha256": self.content_sha256,
            "retrieved_at": self.retrieved_at,
            "feature_count": self.feature_count,
            "bbox_wgs84": list(self.bbox),
        }


def _bbox_str(bbox: Iterable[float]) -> str:
    south, west, north, east = bbox
    return f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"


def _coords_to_line(points: list[dict[str, Any]]) -> Any:
    return LineString([(point["lon"], point["lat"]) for point in points])


def _ring_to_area(coordinates: list[list[float]] | list[dict[str, Any]]) -> Any:
    """Build a polygonal geometry from a way's ring.

    Overpass returns ways as inline coordinate lists, so a building arrives as
    a closed ring rather than a GeoJSON polygon. A closed ring becomes a
    Polygon; a multi-part building becomes a MultiPolygon.
    """
    if coordinates and isinstance(coordinates[0], dict):
        line = _coords_to_line(coordinates)
    else:
        line = LineString(coordinates)
    if line.is_empty:
        return line
    if not line.is_ring:
        return line.buffer(0)
    return Polygon(line)


def _element_geometry(element: dict[str, Any], geom_key: str = "geometry") -> Any:
    """Resolve one Overpass element to a shapely geometry.

    Handles the three forms this project actually receives: nodes as points,
    ways as inline coordinate rings, and relations whose members carry their
    own geometry.
    """
    if geom_key not in element and "lon" in element and "lat" in element:
        return Point(element["lon"], element["lat"])

    geometry = element.get(geom_key)
    if geometry is None:
        members = element.get("members") or []
        parts = []
        for member in members:
            member_geometry = member.get("geometry")
            if member_geometry is None:
                continue
            parts.append(_coords_to_line(member_geometry))
        if not parts:
            return None
        return MultiLineString([part for part in parts if not part.is_empty]) if len(parts) > 1 else parts[0]

    if isinstance(geometry, dict):
        return shape(geometry)
    if isinstance(geometry, list):
        if not geometry:
            return None
        if isinstance(geometry[0], dict):
            line = _coords_to_line(geometry)
            if line.is_ring and len(geometry) > 3:
                return Polygon(line)
            return line
        return shape(geometry)  # already GeoJSON coordinate nesting
    return None


def _elements_to_gdf(elements: list[dict[str, Any]], geom_key: str = "geometry") -> gpd.GeoDataFrame:
    """Convert Overpass ``out geom;`` elements into a GeoDataFrame in CRS84."""
    records: list[dict[str, Any]] = []
    geometries = []
    for element in elements:
        tags = element.get("tags") or {}
        try:
            geometry = _element_geometry(element, geom_key)
        except Exception:  # noqa: BLE001 - skip malformed geometry, keep the run
            continue
        if geometry is None or geometry.is_empty:
            continue
        record = {
            "osm_type": element.get("type"),
            "osm_id": int(element["id"]),
            **{key: value for key, value in tags.items()},
        }
        records.append(record)
        geometries.append(geometry)
    frame = gpd.GeoDataFrame(records, geometry=geometries, crs="OGC:CRS84")
    return frame


def fetch_admin_boundaries(
    client: HttpClient, bbox: Iterable[float], levels: tuple[str, ...] = ("7", "8", "9")
) -> tuple[gpd.GeoDataFrame, FetchRecord]:
    """Fetch administrative boundary relations (centres only) for AOI discovery."""
    level_filter = "|".join(levels)
    query = (
        f'[out:json][timeout:180];\n'
        f'rel["boundary"="administrative"]["admin_level"~"^({level_filter})$"]'
        f"({_bbox_str(bbox)});\n"
        f"out tags center 120;\n"
    )
    result = client.overpass(query, timeout=900)
    payload = json.loads(result.body.decode("utf-8"))
    elements = payload.get("elements", [])
    records, geometries = [], []
    for element in elements:
        tags = element.get("tags") or {}
        center = element.get("center") or {}
        if "lon" not in center:
            continue
        records.append(
            {
                "osm_type": "relation",
                "osm_id": int(element["id"]),
                "name": tags.get("name"),
                "name_en": tags.get("name:en"),
                "admin_level": tags.get("admin_level"),
                "boundary": tags.get("boundary"),
                "wikidata": tags.get("wikidata"),
                "population": tags.get("population"),
            }
        )
        geometries.append(shape({"type": "Point", "coordinates": [center["lon"], center["lat"]]}))
    frame = gpd.GeoDataFrame(records, geometry=geometries, crs="OGC:CRS84")
    record = FetchRecord(
        source_id=SOURCE_ID,
        query_sha256=result.request_parameters.get("query_sha256", ""),
        content_sha256=result.content_sha256,
        retrieved_at=result.retrieved_at,
        feature_count=len(frame),
        bbox=tuple(bbox),  # type: ignore[arg-type]
    )
    return frame, record


def fetch_relation_polygon(client: HttpClient, relation_id: int) -> gpd.GeoDataFrame:
    """Fetch one boundary relation and assemble it into a single polygon.

    Thai administrative relations are multipolygons: the outer ring and the
    inner rings arrive as separate ways, so the parts must be unioned with the
    correct roles before a usable area exists.
    """
    query = f"[out:json][timeout:300];rel({int(relation_id)});out geom;\n"
    result = client.overpass(query, timeout=900)
    payload = json.loads(result.body.decode("utf-8"))
    elements = payload.get("elements", [])
    if not elements:
        raise ValueError(f"relation {relation_id} returned no geometry")

    tags = elements[0].get("tags") or {}
    outer_parts: list[Any] = []
    inner_parts: list[Any] = []
    for member in elements[0].get("members", []):
        geometry = member.get("geometry")
        if not geometry:
            continue
        geometry_shape = shape(geometry)
        if geometry_shape.geom_type == "LineString":
            geometry_shape = geometry_shape.buffer(0)
        if member.get("role") == "inner":
            inner_parts.append(geometry_shape)
        else:
            outer_parts.append(geometry_shape)

    if not outer_parts:
        raise ValueError(f"relation {relation_id} has no outer members")
    outer = unary_union(outer_parts)
    if inner_parts:
        outer = outer.difference(unary_union(inner_parts))
    frame = gpd.GeoDataFrame(
        [
            {
                "osm_type": "relation",
                "osm_id": int(relation_id),
                "name": tags.get("name"),
                "name_en": tags.get("name:en"),
                "admin_level": tags.get("admin_level"),
            }
        ],
        geometry=[outer],
        crs="OGC:CRS84",
    )
    return frame


def fetch_roads(client: HttpClient, bbox: Iterable[float]) -> tuple[gpd.GeoDataFrame, FetchRecord]:
    """Fetch the highway network with the tags the routing stages need."""
    query = (
        f'[out:json][timeout:600];\n'
        f'way["highway"]({_bbox_str(bbox)});\n'
        f"out geom;\n"
    )
    result = client.overpass(query, timeout=900)
    payload = json.loads(result.body.decode("utf-8"))
    frame = _elements_to_gdf(payload.get("elements", []))
    if not frame.empty:
        frame["length_m_crs84"] = 0.0  # measured later in the analysis CRS
    record = FetchRecord(
        source_id=SOURCE_ID,
        query_sha256=result.request_parameters.get("query_sha256", ""),
        content_sha256=result.content_sha256,
        retrieved_at=result.retrieved_at,
        feature_count=len(frame),
        bbox=tuple(bbox),  # type: ignore[arg-type]
    )
    return frame, record


def fetch_buildings(client: HttpClient, bbox: Iterable[float]) -> tuple[gpd.GeoDataFrame, FetchRecord]:
    """Fetch building footprints plus any height/level tags present in OSM."""
    query = (
        f'[out:json][timeout:600];\n'
        f'(way["building"]({_bbox_str(bbox)});'
        f'relation["building"]({_bbox_str(bbox)}););\n'
        f"out geom;\n"
    )
    result = client.overpass(query, timeout=900)
    payload = json.loads(result.body.decode("utf-8"))
    elements = payload.get("elements", [])
    frame = _elements_to_gdf(elements)
    for column in ("height", "building:levels", "building:levels:underground", "building", "name"):
        if column not in frame.columns:
            frame[column] = None
    record = FetchRecord(
        source_id=SOURCE_ID,
        query_sha256=result.request_parameters.get("query_sha256", ""),
        content_sha256=result.content_sha256,
        retrieved_at=result.retrieved_at,
        feature_count=len(frame),
        bbox=tuple(bbox),  # type: ignore[arg-type]
    )
    return frame, record


def fetch_water(client: HttpClient, bbox: Iterable[float]) -> tuple[gpd.GeoDataFrame, FetchRecord]:
    """Fetch water bodies, waterways and landuse=floodprone for hazard context."""
    query = (
        f'[out:json][timeout:600];\n'
        f'(way["natural"="water"]({_bbox_str(bbox)});'
        f'relation["natural"="water"]({_bbox_str(bbox)});'
        f'way["waterway"~"^(river|canal|ditch|stream|drain)$"]({_bbox_str(bbox)});'
        f'way["landuse"="reservoir"]({_bbox_str(bbox)}););\n'
        f"out geom;\n"
    )
    result = client.overpass(query, timeout=900)
    payload = json.loads(result.body.decode("utf-8"))
    frame = _elements_to_gdf(payload.get("elements", []))
    if not frame.empty:
        frame["water_kind"] = frame.apply(
            lambda row: row.get("natural")
            or row.get("waterway")
            or row.get("landuse")
            or "unknown",
            axis=1,
        )
    record = FetchRecord(
        source_id=SOURCE_ID,
        query_sha256=result.request_parameters.get("query_sha256", ""),
        content_sha256=result.content_sha256,
        retrieved_at=result.retrieved_at,
        feature_count=len(frame),
        bbox=tuple(bbox),  # type: ignore[arg-type]
    )
    return frame, record


def save_layer(frame: gpd.GeoDataFrame, name: str, out_dir: str | Path | None = None) -> dict[str, Any]:
    """Persist a staged layer and return its provenance record."""
    target_dir = ensure_dir(Path(out_dir or CURATED_DIR / "osm"))
    path = target_dir / f"{name}.parquet"
    frame.to_parquet(path, index=False)
    try:
        shown = str(path.relative_to(REPO_ROOT))
    except ValueError:
        shown = str(path)
    return {
        "layer": name,
        "path": shown,
        "rows": int(len(frame)),
        "columns": [column for column in frame.columns],
        "crs": frame.crs.to_string() if frame.crs else None,
        "written_at": utc_now_iso(),
    }
