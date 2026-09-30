"""JRC Global Surface Water: observed surface-water extent from Landsat.

This is the first genuinely *observed* hazard layer in the project. Everything
else the pipeline can reach is either a modelled surface (WorldPop) or a
declared scenario, so this module closes the most important provenance gap:
flood extent is no longer only something the pipeline asserts.

What it is, stated precisely so it is not over-read:

* Derived by the European Commission's Joint Research Centre from Landsat 5, 7
  and 8, 1984-2021, at roughly 30 m, as a per-year water/non-water
  classification.
* **Extent, not depth.** A pixel classified as water carries no depth, no
  duration and no flow direction.
* Annual observations do not resolve a flood event or its peak. Missing
  observations must remain distinct from observed non-water.
* Because the year is a classification of a whole year, it cannot resolve
  within-year timing, so it cannot validate a 4-hour evacuation scenario
  directly. It can and does validate *spatial extent*.

Tiles are 10 degrees square, 40,000 x 40,000 pixels, in a 0.00025 degree grid.
They are named ``yearlyClassification<year>-<lat_offset>-<lon_offset>.tif``
where each offset advances 40,000 per 10 degrees: the first field counts
southward from 80N, the second eastward from 180W.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask as rio_mask

from ..http import HttpClient
from ..util import STAGED_DIR, ensure_dir, sha256_file, utc_now_iso, write_json

SOURCE_ID = "jrc-global-surface-water-v1.4"
BASE = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GSWE/"
    "YearlyClassification/LATEST/tiles"
)
TILE_DEGREES = 10
OFFSET_STEP = 40_000
TILE_SIZE_PX = 40_000
PIXEL_DEGREES = 0.00025

# JRC Data Users Guide v4, p15: waterClass (not MonthlyHistory or occurrence).
ENCODING_REFERENCE = (
    "https://storage.googleapis.com/global-surface-water/downloads_ancillary/"
    "DataUsersGuidev2021.pdf"
)
CODE_NO_OBSERVATIONS = 0
CODE_LAND = 1
CODE_SEASONAL = 2
CODE_PERMANENT = 3
CODE_NODATA = (CODE_NO_OBSERVATIONS,)
CODE_CODES = {
    0: "no_observations", 1: "non_water", 2: "seasonal_water", 3: "permanent_water",
}


def is_water(array: np.ndarray) -> np.ndarray:
    """Decode yearly waterClass and reject a different/unknown product encoding."""
    if not np.isin(array, list(CODE_CODES)).all():
        raise ValueError("unknown JRC waterClass code; expected 0, 1, 2 or 3")
    return np.isin(array, (CODE_SEASONAL, CODE_PERMANENT))


@dataclass
class GswRecord:
    year: int
    tile_name: str
    local_path: str
    content_sha256: str
    byte_count: int
    retrieved_at: str
    aoi_water_pixels: int
    aoi_total_pixels: int
    aoi_water_share: float | None
    aoi_water_km2: float
    aoi_area_km2: float
    aoi_seasonal_pixels: int
    aoi_permanent_pixels: int
    aoi_no_observation_pixels: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "tile_name": self.tile_name,
            "local_path": self.local_path,
            "content_sha256": self.content_sha256,
            "byte_count": self.byte_count,
            "retrieved_at": self.retrieved_at,
            "aoi_water_pixels": self.aoi_water_pixels,
            "aoi_total_pixels": self.aoi_total_pixels,
            "aoi_water_share": round(self.aoi_water_share, 6) if self.aoi_water_share is not None else None,
            "aoi_water_km2": round(self.aoi_water_km2, 4),
            "aoi_area_km2": round(self.aoi_area_km2, 4),
            "aoi_seasonal_pixels": self.aoi_seasonal_pixels,
            "aoi_permanent_pixels": self.aoi_permanent_pixels,
            "aoi_no_observation_pixels": self.aoi_no_observation_pixels,
        }


def tile_name_for(year: int, bounds: tuple[float, float, float, float]) -> str:
    """Resolve the 10-degree tile that contains the given WGS84 bounds.

    Raises when the bounds straddle a tile edge, because silently reading the
    wrong tile would produce a plausible-looking map of the wrong place.
    """
    west, south, east, north = bounds
    # Nudge the top edge inside its band so an AOI whose northern edge is
    # exactly on a tile boundary resolves to the tile below it, not the one
    # above.
    lat_band = int(np.floor((north - 1e-9) / TILE_DEGREES)) * TILE_DEGREES
    lon_band = int(np.floor(west / TILE_DEGREES)) * TILE_DEGREES
    if south < lat_band or east > lon_band + TILE_DEGREES:
        raise ValueError(
            f"bounds {bounds} straddle a {TILE_DEGREES}-degree tile edge; "
            "fetch each tile separately rather than assuming coverage"
        )
    # The offset counts from 80N southwards using the tile's TOP edge, not its
    # bottom. Using the bottom silently resolves to the tile one step too far
    # south, which downloads a real file for the wrong place.
    lat_offset = int((80 - (lat_band + TILE_DEGREES)) / TILE_DEGREES) * OFFSET_STEP
    lon_offset = int((lon_band + 180) / TILE_DEGREES) * OFFSET_STEP
    return f"yearlyClassification{year}-{lat_offset:010d}-{lon_offset:010d}.tif"


def fetch_year(
    client: HttpClient,
    year: int,
    bounds: tuple[float, float, float, float],
    *,
    cache_dir: str | Path | None = None,
) -> GswRecord:
    """Download one year's tile and measure observed water inside the AOI."""
    name = tile_name_for(year, bounds)
    target_dir = ensure_dir(Path(cache_dir or STAGED_DIR / "gsw"))
    destination = target_dir / name
    if not destination.is_file():
        result = client.get(f"{BASE}/yearlyClassification{year}/{name}", use_cache=True,
                            retries=3, timeout=900)
        destination.write_bytes(result.body)
        retrieved_at = result.retrieved_at
    else:
        retrieved_at = utc_now_iso()

    return measure_year(year, name, destination, bounds, aoi_geometry=None, retrieved_at=retrieved_at)


def measure_year(
    year: int,
    name: str,
    path: Path,
    bounds: tuple[float, float, float, float],
    *,
    aoi_geometry: Any = None,
    retrieved_at: str | None = None,
) -> GswRecord:
    """Read a tile, optionally clip to an AOI, and summarise observed water."""
    with rasterio.open(path) as dataset:
        geometries = None
        if aoi_geometry is not None:
            geometry = aoi_geometry
            if hasattr(geometry, "geometry"):
                series = geometry.geometry
                geometry = series.union_all() if hasattr(series, "union_all") else series.unary_union
            geometries = [geometry]
            data, _ = rio_mask(dataset, geometries, crop=True, filled=False)
            array = data[0].compressed()
        else:
            window = dataset.window(*bounds)
            array = dataset.read(1, window=window, boundless=True, masked=True).compressed()

        water = int(is_water(array).sum())
        pixel_area_km2 = (PIXEL_DEGREES * 111.32) ** 2 * np.cos(np.radians(np.mean(bounds[1::2])))
        # Coverage is observed pixels only; a zero code is not evidence of dry land.
        classified = int((~np.isin(array, CODE_NODATA)).sum())
        return GswRecord(
            year=year,
            tile_name=name,
            local_path=str(path),
            content_sha256=sha256_file(path),
            byte_count=path.stat().st_size,
            retrieved_at=retrieved_at or utc_now_iso(),
            aoi_water_pixels=water,
            aoi_total_pixels=classified,
            aoi_water_share=water / classified if classified else None,
            aoi_water_km2=water * float(pixel_area_km2),
            aoi_area_km2=classified * float(pixel_area_km2),
            aoi_seasonal_pixels=int((array == CODE_SEASONAL).sum()),
            aoi_permanent_pixels=int((array == CODE_PERMANENT).sum()),
            aoi_no_observation_pixels=int((array == CODE_NO_OBSERVATIONS).sum()),
        )


def observed_water_mask(path: Path, aoi_geometry: Any) -> np.ndarray:
    """Return a boolean water mask for the AOI, aligned to ``aoi_geometry``."""
    with rasterio.open(path) as dataset:
        if hasattr(aoi_geometry, "geometry"):
            series = aoi_geometry.geometry
            geometry = series.union_all() if hasattr(series, "union_all") else series.unary_union
        else:
            geometry = aoi_geometry
        data, transform = rio_mask(dataset, [geometry], crop=True, filled=True, nodata=CODE_NO_OBSERVATIONS)
    return is_water(data[0]), transform


def fetch_years(
    client: HttpClient,
    years: Iterable[int],
    bounds: tuple[float, float, float, float],
    aoi_frame: gpd.GeoDataFrame,
) -> dict[str, Any]:
    """Fetch a set of years and write a per-year observed extent summary.

    Preserve the annual classes; differences between years are not event-flood
    estimates, particularly when observation coverage differs.
    """
    target_dir = ensure_dir(STAGED_DIR / "gsw")
    records: list[GswRecord] = []
    unavailable: list[dict[str, Any]] = []
    for year in years:
        name = tile_name_for(year, bounds)
        destination = target_dir / name
        if not destination.is_file():
            try:
                result = client.get(
                    f"{BASE}/yearlyClassification{year}/{name}", use_cache=True, retries=2, timeout=900
                )
            except Exception as error:  # noqa: BLE001 - recorded, not fatal
                # The downloadable set does not necessarily span every year the
                # product is described as covering. Record the gap instead of
                # failing the whole multi-year comparison.
                unavailable.append({"year": year, "tile": name, "error": str(error)[:200]})
                continue
            destination.write_bytes(result.body)
            retrieved_at = result.retrieved_at
        else:
            retrieved_at = utc_now_iso()
        records.append(
            measure_year(
                year, name, destination, bounds,
                aoi_geometry=aoi_frame, retrieved_at=retrieved_at,
            )
        )

    if not records:
        raise RuntimeError("no GSW year could be retrieved for these bounds")

    # The anomaly signal: how much more water than the baseline year.
    baseline_year = min(record.year for record in records)
    baseline = next(record for record in records if record.year == baseline_year)
    years_payload: list[dict[str, Any]] = []
    for record in records:
        record_dict = record.as_dict()
        record_dict["excess_km2_vs_baseline"] = round(
            record.aoi_water_km2 - baseline.aoi_water_km2, 4
        )
        record_dict["baseline_year"] = baseline_year
        years_payload.append(record_dict)

    summary = {
        "source_id": SOURCE_ID,
        "licence": "CC BY 4.0 (Copernicus / European Commission JRC)",
        "product": "Global Surface Water v1.4 yearly classification, 1984-2021, Landsat 5/7/8",
        "encoding_reference": ENCODING_REFERENCE,
        "class_codes": CODE_CODES,
        "is_observation": True,
        "measures": "water extent, NOT depth, duration or direction",
        "baseline_year": baseline_year,
        "years": years_payload,
        "interpretation_notes": [
            "Annual water classes are not event-flood extent or flood peak estimates.",
            "Compare observation coverage alongside annual area; no observations is not dry land.",
            "A year cannot resolve within-year timing and therefore cannot validate a "
            "4-hour evacuation scenario directly; it can validate spatial extent.",
            "Permanent water (the river and canals) is included in every year, which is "
            "why the baseline year is non-zero.",
        ],
        "unavailable_years": unavailable,
        "retrieved_at": utc_now_iso(),
    }
    write_json(target_dir / "observed_extent_summary.json", summary)
    return summary
