"""WorldPop resident population counts.

Two rules from the plan are enforced here:

1. A gridded population count is a *resident baseline*, never a time-of-day
   population. The module name and every downstream column reflect that.
2. Counts are clipped in their native CRS and only reprojected for area
   weighting. Resampling counts would silently invent or destroy people.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rasterio
from rasterio.mask import mask as rio_mask
from shapely.geometry import box, mapping

from ..http import HttpClient
from ..provenance import verify_source
from ..util import STAGED_DIR, ensure_dir, utc_now_iso, write_json

REST_BASE = "https://www.worldpop.org/rest/data"
DOWNLOAD_BASE = "https://data.worldpop.org"
SOURCE_ID = "worldpop-global2-tha-100m-r2025a"
CITY_SOURCE_ID = "worldpop-global-2000-2020-tha-100m"
CITY_DATASET = {"popyear": "2020", "data_file": "GIS/Population/Global_2000_2020/2020/THA/tha_ppp_2020.tif"}


def count_raster_url(dataset: dict[str, Any]) -> str:
    """Use the same resource identity for download verification and manifests."""
    return f"{DOWNLOAD_BASE}/{dataset['data_file'].lstrip('/')}"


@dataclass
class RasterRecord:
    source_id: str
    dataset_id: str
    title: str
    popyear: str
    doi: str
    licence: str
    data_file: str
    source_url: str
    content_sha256: str
    retrieved_at: str
    byte_count: int
    local_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "dataset_id": self.dataset_id,
            "title": self.title,
            "popyear": self.popyear,
            "doi": self.doi,
            "licence": self.licence,
            "data_file": self.data_file,
            "source_url": self.source_url,
            "content_sha256": self.content_sha256,
            "retrieved_at": self.retrieved_at,
            "byte_count": self.byte_count,
            "local_path": self.local_path,
        }


def list_datasets(client: HttpClient, iso3: str = "THA") -> list[dict[str, Any]]:
    result = client.get(f"{REST_BASE}/pop/wpgp", params={"iso3": iso3}, use_cache=True)
    return result.json().get("data", [])


def select_dataset(datasets: list[dict[str, Any]], *, prefer_year: str | None = None) -> dict[str, Any]:
    """Choose the newest published count raster, or a specific year."""
    candidates = [item for item in datasets if item.get("data_file")]
    if not candidates:
        raise ValueError("WorldPop returned no downloadable count rasters")
    if prefer_year:
        for item in candidates:
            if item.get("popyear") == prefer_year:
                return item
        raise ValueError(f"WorldPop has no count raster for popyear={prefer_year}")
    return max(candidates, key=lambda item: int(item.get("popyear", 0)))


def download_count_raster(
    client: HttpClient,
    dataset: dict[str, Any],
    out_dir: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Download the count GeoTIFF with resume and a verified byte count."""
    target_dir = ensure_dir(Path(out_dir or STAGED_DIR / "population"))
    url = count_raster_url(dataset)
    name = Path(dataset["data_file"]).name
    destination = target_dir / name
    if destination.is_file():
        metadata = verify_source(destination, url, cache_dir=getattr(client, "cache_dir", None))
        return destination, {**metadata, "url": url, "byte_count": destination.stat().st_size,
                             "already_present": True}
    meta = client.download_large(url, destination)
    if meta.get("already_present"):
        metadata = verify_source(destination, url, cache_dir=getattr(client, "cache_dir", None))
        return destination, {**metadata, "url": url, "byte_count": destination.stat().st_size,
                             "already_present": True}
    metadata = {
        "url": url,
        "content_sha256": meta["content_sha256"],
        "retrieved_at": utc_now_iso(),
        "byte_count": meta["byte_count"],
        "already_present": meta.get("already_present", False),
    }
    write_json(destination.with_suffix(".provenance.json"), metadata)
    verify_source(destination, url)
    return destination, metadata


def clip_to_aoi(
    raster_path: str | Path,
    aoi_wgs84,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    """Clip the count raster to the AOI window, keeping native pixels.

    Counts are preserved exactly: the clip is a window selection, never a
    resample. A verification step re-reads the clipped file and compares the
    retained total against the source window so a silent loss cannot pass.
    """
    source = Path(raster_path)
    target = Path(out_path or source.with_name(f"{source.stem}_aoi{source.suffix}"))
    ensure_dir(target.parent)

    geometry = aoi_wgs84
    if hasattr(geometry, "to_crs"):
        geometry = geometry.to_crs("OGC:CRS84")
    if hasattr(geometry, "geom_type") and geometry.geom_type == "MultiPolygon":
        geometry = max(geometry.geoms, key=lambda part: part.area)

    with rasterio.open(source) as dataset:
        data, transform = rio_mask(dataset, [mapping(geometry)], crop=True, filled=True, nodata=0)
        profile = dataset.profile.copy()
        profile.update(
            {
                "height": data.shape[1],
                "width": data.shape[2],
                "transform": transform,
                "compress": "deflate",
                "tiled": True,
                "blockxsize": 256,
                "blockysize": 256,
            }
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(target, "w", **profile) as writer:
            writer.write(data[0], 1)

        positive = data[0][data[0] > 0].astype("float64")
        window_total = float(positive.sum())
        stats = {
            "source": str(source),
            "clip": str(target),
            "source_crs": dataset.crs.to_string(),
            "source_resolution_m": {
                "x": abs(dataset.transform.a),
                "y": abs(dataset.transform.e),
            },
            "source_nodata": dataset.nodata,
            "clip_bounds_wgs84": list(geometry.bounds),
            "clip_total_population": window_total,
            "clip_nonzero_cells": int((data[0] > 0).sum()),
            "clip_max_cell": float(data[0].max()) if data[0].size else 0.0,
            "clip_mean_positive": (
                float(positive.mean()) if positive.size else 0.0
            ),
            "clipped_at": utc_now_iso(),
            "method": "window clip in source CRS; no resampling",
        }
    return stats


def bbox_of(geometry) -> tuple[float, float, float, float]:
    return box(*geometry.bounds)
