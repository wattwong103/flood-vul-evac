"""City-scale ingestion from a regional OSM PBF extract.

The pilot used tiled Overpass queries, which is the right tool for one district
and the wrong tool for a 1,643 km2 metropolitan area. A single regional extract
covers everything in one download, and GDAL's OSM driver reads it without an
osmium dependency.

One GDAL quirk matters throughout: the driver exposes a fixed set of columns
(``osm_id``, ``name``, ``highway``, ``waterway``, ``building``, ``amenity``, ...)
and packs every other tag into ``other_tags`` as a Ruby-style hash fragment.
``building:levels`` and the address tags live there, so they are parsed out
explicitly rather than being silently lost.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd

from ..http import HttpClient
from ..util import CURATED_DIR, REPO_ROOT, ensure_dir, read_json, sha256_file, utc_now_iso, write_json
from .registry import load_registry

SOURCE_ID = "geofabrik-thailand-osm-20260929"
DEFAULT_PBF = "data/staged/osm/thailand-260929.osm.pbf"
DEFAULT_COVERAGE = "data/staged/osm/thailand.poly"
COVERAGE_URL = "https://download.geofabrik.de/asia/thailand.poly"

# GDAL emits other_tags as a Ruby hash fragment: "k"=>"v","k2"=>12
_OTHER_TAG = re.compile(r'"([^"]+)"=>(?:"([^"]*)"|(-?[0-9.]+))')


def parse_other_tags(fragment: Any) -> dict[str, str]:
    """Parse one ``other_tags`` value into a plain dict."""
    if not isinstance(fragment, str) or not fragment:
        return {}
    parsed: dict[str, str] = {}
    for match in _OTHER_TAG.finditer(fragment):
        key = match.group(1)
        value = match.group(2) if match.group(2) is not None else match.group(3)
        parsed[key] = value
    return parsed


def extract_tag(frame: gpd.GeoDataFrame, tag: str) -> gpd.GeoSeries:
    """Pull a tag that GDAL may have put in ``other_tags``."""
    if tag in frame.columns:
        return frame[tag]
    if "other_tags" not in frame.columns:
        return pd_series_of_nones(frame)
    return frame["other_tags"].map(lambda fragment: parse_other_tags(fragment).get(tag))


def pd_series_of_nones(frame: gpd.GeoDataFrame):
    import pandas as pd

    return pd.Series([None] * len(frame), index=frame.index, dtype="object")


@dataclass
class CityIngestRecord:
    source_id: str
    pbf_path: str
    content_sha256: str
    byte_count: int
    retrieved_at: str
    road_ways: int
    waterway_features: int
    buildings: int
    layers: dict[str, dict[str, Any]]
    coverage: dict[str, Any]
    resource_url: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "pbf_path": self.pbf_path,
            "content_sha256": self.content_sha256,
            "byte_count": self.byte_count,
            "retrieved_at": self.retrieved_at,
            "road_ways": self.road_ways,
            "waterway_features": self.waterway_features,
            "buildings": self.buildings,
            "layers": self.layers,
            "coverage": self.coverage,
            "resource_url": self.resource_url,
        }


def _save(frame: gpd.GeoDataFrame, name: str, out_dir: Path) -> dict[str, Any]:
    path = out_dir / f"{name}.parquet"
    frame.to_parquet(path, index=False)
    return {
        "layer": name,
        "path": str(path),
        "rows": int(len(frame)),
        "crs": frame.crs.to_string() if frame.crs else None,
        "sha256": sha256_file(path),
    }


def source_coverage(path: Path, aoi: gpd.GeoDataFrame) -> dict[str, Any]:
    """Check the publisher's actual .poly boundary, including exclusion rings."""
    from shapely import union_all
    from shapely.geometry import Polygon
    positive, negative = [], []
    lines = iter(line.strip() for line in path.read_text(encoding="utf-8").splitlines()[1:] if line.strip())
    try:
        while (label := next(lines)) != "END":
            coordinates = []
            while (line := next(lines)) != "END":
                coordinate = tuple(map(float, line.split()))
                if len(coordinate) != 2:
                    raise ValueError("expected longitude latitude")
                coordinates.append(coordinate)
            ring = Polygon(coordinates)
            if not ring.is_valid or ring.is_empty:
                raise ValueError("invalid ring")
            (negative if label.startswith("!") else positive).append(ring)
        if not positive or list(lines):
            raise ValueError("missing exterior or trailing data")
    except (StopIteration, ValueError) as error:
        raise ValueError(f"Malformed OSM coverage polygon: {path.name}") from error
    polygon = union_all(positive).difference(union_all(negative))
    if polygon.is_empty or not polygon.is_valid or not polygon.covers(aoi.to_crs("EPSG:4326").geometry.union_all()):
        raise ValueError("OSM source polygon does not cover the complete city AOI")
    return {"covers_aoi": True, "sha256": sha256_file(path),
            "path": os.path.relpath(path.resolve(), REPO_ROOT).replace(os.sep, "/"),
            "polygon_wkt": polygon.wkt, "crs": "EPSG:4326",
            "note": "Source coverage, not proof of mapping completeness."}


def source_provenance(source: Path, resource_url: str) -> dict[str, Any]:
    """A staged file must match its download record; extraction is not retrieval."""
    sidecar = source.with_suffix(".provenance.json")
    if not sidecar.is_file():
        raise ValueError("OSM file lacks download provenance; move the staged file aside "
                         "and re-download with ingest_city to record its origin")
    metadata = read_json(sidecar)
    if (metadata.get("url") != resource_url or not metadata.get("retrieved_at")
            or metadata.get("content_sha256") != sha256_file(source)):
        raise ValueError("OSM download provenance does not match the staged source")
    return metadata


def validate_cached_ingest(record: dict, aoi: gpd.GeoDataFrame, target: Path) -> None:
    """Do not silently reuse the former incomplete extract or changed layers."""
    if record.get("source_id") != SOURCE_ID:
        raise ValueError("OSM source changed; re-ingest the complete city extract")
    load_registry().require_approved([SOURCE_ID])
    metadata = source_provenance(Path(record["pbf_path"]), record["resource_url"])
    coverage_path = Path(record["coverage"].get("path", REPO_ROOT / DEFAULT_COVERAGE))
    if not coverage_path.is_absolute():
        coverage_path = REPO_ROOT / coverage_path
    coverage = source_coverage(coverage_path, aoi)
    if (metadata["content_sha256"] != record["content_sha256"]
            or coverage["sha256"] != record["coverage"]["sha256"]):
        raise ValueError("OSM inputs changed; re-ingest the city extract")
    for name, layer in record["layers"].items():
        path = target / f"{name}.parquet"
        if not path.is_file() or sha256_file(path) != layer["sha256"]:
            raise ValueError(f"OSM cached {name} changed; re-ingest the city extract")


def ingest_city(
    *,
    pbf_path: str | Path = DEFAULT_PBF,
    out_dir: str | Path | None = None,
    download_if_missing: bool = True,
    coverage_path: str | Path = DEFAULT_COVERAGE,
) -> CityIngestRecord:
    """Extract city road, water and building layers from a regional PBF.

    The extract is downloaded once if absent; the download is resumable, so a
    multi-hundred-megabyte city extract does not restart on interruption.
    """
    import pyogrio
    from ..aoi import load_aoi

    registered = load_registry().require_approved([SOURCE_ID])[0]
    aoi = load_aoi("bangkok-bma").to_crs("EPSG:4326")
    coverage_file = Path(coverage_path)
    if not coverage_file.is_file():
        if not download_if_missing:
            raise FileNotFoundError(coverage_file)
        ensure_dir(coverage_file.parent)
        coverage_file.write_bytes(HttpClient().get(COVERAGE_URL).body)
    coverage = source_coverage(coverage_file, aoi)
    coverage["resource_url"] = COVERAGE_URL
    source = Path(pbf_path)
    if not source.is_file():
        if not download_if_missing:
            raise FileNotFoundError(source)
        client = HttpClient(timeout=900)
        metadata = client.download_large(registered.resource_url, source)
        metadata["retrieved_at"] = utc_now_iso()
        write_json(source.with_suffix(".provenance.json"), metadata)

    metadata = source_provenance(source, registered.resource_url)
    target = ensure_dir(Path(out_dir or CURATED_DIR / "city"))
    bounds = tuple(aoi.total_bounds)

    lines = pyogrio.read_dataframe(
        source, layer="lines", use_arrow=True, columns=["osm_id", "name", "highway", "waterway"], bbox=bounds
    )
    roads = lines[lines["highway"].notna()].copy()
    # Water features arrive as mapped waterway lines plus a `natural=water`
    # class that GDAL surfaces in the multipolygon layer; keep the lines here.
    water_lines = lines[lines["waterway"].notna()].copy()
    water_lines["water_kind"] = water_lines["waterway"].astype(str)

    multipolygons = pyogrio.read_dataframe(
        source,
        layer="multipolygons",
        use_arrow=True,
        columns=["osm_id", "name", "building", "amenity", "other_tags"],
        bbox=bounds,
    )
    buildings = multipolygons[multipolygons["building"].notna()].copy()
    # Height evidence lives in other_tags, not in a dedicated column.
    buildings["building:levels"] = extract_tag(buildings, "building:levels")
    buildings["height"] = extract_tag(buildings, "height")
    buildings["addr:subdistrict"] = extract_tag(buildings, "addr:subdistrict")
    buildings["addr:district"] = extract_tag(buildings, "addr:district")
    natural_water = multipolygons[multipolygons["building"].isna()].copy()
    if "other_tags" in natural_water.columns:
        natural_water["water_kind"] = natural_water["other_tags"].map(
            lambda fragment: parse_other_tags(fragment).get("natural", "unknown")
        )
        natural_water = natural_water[natural_water["water_kind"] == "water"]

    layers = {
        "roads": _save(roads, "roads", target),
        "water_lines": _save(water_lines, "water_lines", target),
        "buildings": _save(buildings, "buildings", target),
    }
    if len(natural_water):
        layers["water_areas"] = _save(natural_water, "water_areas", target)

    record = CityIngestRecord(
        source_id=SOURCE_ID,
        pbf_path=str(source),
        content_sha256=metadata["content_sha256"],
        byte_count=source.stat().st_size,
        retrieved_at=metadata["retrieved_at"],
        road_ways=int(len(roads)),
        waterway_features=int(len(water_lines)) + int(len(natural_water)),
        buildings=int(len(buildings)),
        layers=layers,
        coverage=coverage,
        resource_url=registered.resource_url,
    )
    write_json(target / "provenance.json", record.as_dict())
    return record
