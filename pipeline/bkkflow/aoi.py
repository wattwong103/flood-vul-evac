"""Area-of-interest resolution.

The pilot boundary is a real administrative polygon, not a hand-drawn box, so
that population controls, reporting geographies and the published map all refer
to the same place. The boundary is fetched from OpenStreetMap (ODbL 1.0), which
passes the project's data gate, and is stored with the query that produced it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import shape

from .http import HttpClient
from .util import CURATED_DIR, ensure_dir, sha256_bytes, utc_now_iso, write_json

NOMINATIM_LOOKUP = "https://nominatim.openstreetmap.org/lookup"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
SOURCE_ID = "osm-thailand-geofabrik"


@dataclass
class AoiRecord:
    aoi_id: str
    name: str
    name_en: str
    admin_level: str
    osm_type: str
    osm_id: int
    attribution: str
    content_sha256: str
    retrieved_at: str
    area_km2: float
    analysis_crs: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "aoi_id": self.aoi_id,
            "name": self.name,
            "name_en": self.name_en,
            "admin_level": self.admin_level,
            "osm_type": self.osm_type,
            "osm_id": self.osm_id,
            "attribution": self.attribution,
            "content_sha256": self.content_sha256,
            "retrieved_at": self.retrieved_at,
            "area_km2": self.area_km2,
            "analysis_crs": self.analysis_crs,
        }


def search_place(client: HttpClient, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Look up a place and return candidate OSM identifiers."""
    result = client.get(
        NOMINATIM_SEARCH,
        params={
            "q": query,
            "format": "json",
            "limit": limit,
            "polygon_geojson": 0,
            "addressdetails": 1,
        },
    )
    return result.json()


def fetch_boundary(
    client: HttpClient,
    *,
    osm_type: str,
    osm_id: int,
    aoi_id: str,
    analysis_crs: str,
    name: str | None = None,
    name_en: str | None = None,
    admin_level: str | None = None,
) -> tuple[gpd.GeoDataFrame, AoiRecord]:
    """Fetch one OSM relation boundary as a polygon and record its provenance."""
    result = client.get(
        NOMINATIM_LOOKUP,
        params={
            "osm_ids": f"{osm_type[0].upper()}{int(osm_id)}",
            "format": "json",
            "polygon_geojson": 1,
        },
    )
    payload = result.json()
    if not payload:
        raise ValueError(f"{osm_type}/{osm_id} returned no geometry from Nominatim")
    entry = payload[0]
    geometry = shape(entry["geojson"])
    frame = gpd.GeoDataFrame(
        [
            {
                "aoi_id": aoi_id,
                "name": name or entry.get("name") or entry.get("display_name", ""),
                "name_en": name_en,
                "admin_level": admin_level,
                "osm_type": osm_type,
                "osm_id": int(osm_id),
            }
        ],
        geometry=[geometry],
        crs="OGC:CRS84",
    )
    projected = frame.to_crs(analysis_crs)
    record = AoiRecord(
        aoi_id=aoi_id,
        name=str(frame["name"].iloc[0]),
        name_en=name_en or "",
        admin_level=admin_level or "",
        osm_type=osm_type,
        osm_id=int(osm_id),
        attribution="(c) OpenStreetMap contributors, ODbL 1.0",
        content_sha256=result.content_sha256,
        retrieved_at=result.retrieved_at,
        area_km2=round(float(projected.geometry.area.iloc[0]) / 1e6, 4),
        analysis_crs=analysis_crs,
    )
    return frame, record


def save_aoi(frame: gpd.GeoDataFrame, record: AoiRecord) -> dict[str, Any]:
    """Persist the AOI geometry and its provenance next to the curated data."""
    target_dir = ensure_dir(CURATED_DIR / "aoi")
    parquet_path = target_dir / f"{record.aoi_id}.parquet"
    geojson_path = target_dir / f"{record.aoi_id}.geojson"
    frame.to_parquet(parquet_path, index=False)
    frame.to_file(geojson_path, driver="GeoJSON")
    write_json(target_dir / f"{record.aoi_id}.provenance.json", record.as_dict())
    return {
        "aoi_id": record.aoi_id,
        "parquet": str(parquet_path),
        "geojson": str(geojson_path),
        "area_km2": record.area_km2,
        "content_sha256": record.content_sha256,
        "retrieved_at": record.retrieved_at,
    }


def load_aoi(aoi_id: str) -> gpd.GeoDataFrame:
    path = CURATED_DIR / "aoi" / f"{aoi_id}.parquet"
    if not path.is_file():
        raise FileNotFoundError(
            f"AOI {aoi_id!r} has not been resolved; run the sources stage first ({path})"
        )
    return gpd.read_parquet(path)


def bbox(aoi_id: str, *, pad_degrees: float = 0.002) -> tuple[float, float, float, float]:
    """Return (south, west, north, east) for Overpass queries.

    A small pad captures ways whose geometry extends just beyond the boundary;
    the router clips them back to the AOI afterwards.
    """
    frame = load_aoi(aoi_id)
    minx, miny, maxx, maxy = frame.total_bounds
    return (
        float(miny - pad_degrees),
        float(minx - pad_degrees),
        float(maxy + pad_degrees),
        float(maxx + pad_degrees),
    )
