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
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd

from ..http import HttpClient
from ..util import CURATED_DIR, ensure_dir, sha256_file, utc_now_iso, write_json

SOURCE_ID = "bbbike-bangkok-osm-extract"
DEFAULT_PBF = "data/staged/osm/Bangkok.osm.pbf"
BBBIKE_URL = "https://download.bbbike.org/osm/bbbike/Bangkok/Bangkok.osm.pbf"

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


def ingest_city(
    *,
    pbf_path: str | Path = DEFAULT_PBF,
    out_dir: str | Path | None = None,
    download_if_missing: bool = True,
) -> CityIngestRecord:
    """Extract city road, water and building layers from a regional PBF.

    The extract is downloaded once if absent; the download is resumable, so a
    multi-hundred-megabyte city extract does not restart on interruption.
    """
    import pyogrio

    source = Path(pbf_path)
    if not source.is_file():
        if not download_if_missing:
            raise FileNotFoundError(source)
        client = HttpClient(timeout=900)
        client.download_large(BBBIKE_URL, source)

    target = ensure_dir(Path(out_dir or CURATED_DIR / "city"))

    lines = pyogrio.read_dataframe(
        source, layer="lines", use_arrow=True, columns=["osm_id", "name", "highway", "waterway"]
    )
    roads = lines[lines["highway"].notna()].copy()
    water = lines[lines["waterway"].notna() | lines["waterway"].isna()].copy()
    # Water features arrive as mapped waterway lines plus a `natural=water`
    # class that GDAL surfaces in the multipolygon layer; keep the lines here.
    water_lines = lines[lines["waterway"].notna()].copy()
    water_lines["water_kind"] = water_lines["waterway"].astype(str)
    water_polys = gpd.GeoDataFrame(columns=lines.columns, crs=lines.crs)

    multipolygons = pyogrio.read_dataframe(
        source,
        layer="multipolygons",
        use_arrow=True,
        columns=["osm_id", "name", "building", "amenity", "other_tags"],
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
        content_sha256=sha256_file(source),
        byte_count=source.stat().st_size,
        retrieved_at=utc_now_iso(),
        road_ways=int(len(roads)),
        waterway_features=int(len(water_lines)) + int(len(natural_water)),
        buildings=int(len(buildings)),
        layers=layers,
    )
    write_json(target / "provenance.json", record.as_dict())
    return record
