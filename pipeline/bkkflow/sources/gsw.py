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

The water *share* needs a denominator, and yearly code 0 is not one. JRC
computes the yearly layers only inside the Maximum Water Extent, so code 0
mixes pixels never detected as water in 1984-2021 (most of the land) with
pixels that went unobserved that year (BKK-054). ``share_support`` recodes code 0
with the extent tile; without it the share is null, never water / classified.

Tiles are 10 degrees square, 40,000 x 40,000 pixels, in a 0.00025 degree grid.
They are named ``yearlyClassification<year>-<lat_offset>-<lon_offset>.tif``
where each offset advances 40,000 per 10 degrees: the first field counts
southward from 80N, the second eastward from 180W.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask as rio_mask

from ..http import HttpClient
from ..provenance import verify_source
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
CODE_CODES = {
    0: "no_observations", 1: "non_water", 2: "seasonal_water", 3: "permanent_water",
}

# Maximum Water Extent, the same 0.00025 degree grid; guide p12.
EXTENT_SOURCE_ID = "jrc-global-surface-water-max-extent-v1.4"
EXTENT_BASE = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GSWE/"
    "Aggregated/LATEST/extent/tiles"
)
EXTENT_NOT_WATER = 0
EXTENT_NODATA = 255
EXTENT_CODES = {0: "not_water", 1: "water_detected", 255: "no_data"}
# Both products share one grid exactly; affine's default 1e-5 would admit a
# 4% pixel-size error (review, BKK-054b).
GRID_TOLERANCE_DEGREES = 1e-9
SHARE_BASIS = (
    "water / (AOI - unknown). Unknown is yearly code 0 inside the JRC Maximum Water "
    "Extent (unobserved that year) or under its no-data; yearly code 0 outside it "
    "was never detected as water in 1984-2021 and counts as not water."
)


def is_water(array: np.ndarray) -> np.ndarray:
    """Decode yearly waterClass and reject a different/unknown product encoding."""
    if not np.isin(array, list(CODE_CODES)).all():
        raise ValueError("unknown JRC waterClass code; expected 0, 1, 2 or 3")
    return np.isin(array, (CODE_SEASONAL, CODE_PERMANENT))


def share_support(
    yearly: np.ndarray, extent: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray | None]:
    """Return ``(water, known)`` masks: the one share decoder for every consumer.

    A pixel's water status is known when the year classified it (codes 1-3) or
    when it is code 0 outside the Maximum Water Extent. Code 0 inside the
    extent, or under extent no-data, stays unknown and is never counted as dry.
    Without the extent nothing separates the two, so ``known`` is None.
    """
    water = is_water(yearly)
    if extent is None:
        return water, None
    if extent.shape != yearly.shape:
        raise ValueError("Maximum Water Extent and yearly arrays differ in shape")
    if not np.isin(extent, list(EXTENT_CODES)).all():
        raise ValueError("unknown JRC Maximum Water Extent code; expected 0, 1 or 255")
    return water, (yearly != CODE_NO_OBSERVATIONS) | (extent == EXTENT_NOT_WATER)


@dataclass
class GswRecord:
    year: int
    tile_name: str
    local_path: str
    content_sha256: str
    byte_count: int
    retrieved_at: str
    aoi_pixels: int
    aoi_water_pixels: int
    classified_pixels: int
    never_water_pixels: int | None
    unknown_pixels: int | None
    known_pixels: int | None
    aoi_water_share: float | None
    share_status: str
    aoi_water_km2: float
    classified_km2: float
    known_km2: float | None
    aoi_seasonal_pixels: int
    aoi_permanent_pixels: int
    aoi_no_observation_pixels: int

    def as_dict(self) -> dict[str, Any]:
        record = asdict(self)
        if self.aoi_water_share is not None:
            record["aoi_water_share"] = round(self.aoi_water_share, 6)
        for key in ("aoi_water_km2", "classified_km2", "known_km2"):
            if record[key] is not None:
                record[key] = round(record[key], 4)
        return record


def tile_name_for(year: int, bounds: tuple[float, float, float, float]) -> str:
    """Resolve the yearly tile that contains the given WGS84 bounds."""
    lat_offset, lon_offset = _tile_offsets(bounds)
    return f"yearlyClassification{year}-{lat_offset:010d}-{lon_offset:010d}.tif"


def extent_tile_name_for(bounds: tuple[float, float, float, float]) -> str:
    """Resolve the Maximum Water Extent tile; it shares the yearly offsets."""
    lat_offset, lon_offset = _tile_offsets(bounds)
    return f"extent-{lat_offset:010d}-{lon_offset:010d}.tif"


def _tile_offsets(bounds: tuple[float, float, float, float]) -> tuple[int, int]:
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
    return lat_offset, lon_offset


def staged_tile(year: int, bounds: tuple[float, float, float, float]) -> tuple[Path, dict]:
    """One gate for standalone raster consumers, including cached masks."""
    name = tile_name_for(year, bounds)
    path = STAGED_DIR / "gsw" / name
    return path, verify_source(path, f"{BASE}/yearlyClassification{year}/{name}")


def staged_extent_tile(bounds: tuple[float, float, float, float]) -> tuple[Path, dict]:
    """The same provenance gate for the Maximum Water Extent tile."""
    name = extent_tile_name_for(bounds)
    path = STAGED_DIR / "gsw" / name
    return path, verify_source(path, f"{EXTENT_BASE}/{name}")


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
        write_json(destination.with_suffix(".provenance.json"), {
            "resource_url": f"{BASE}/yearlyClassification{year}/{name}",
            "retrieved_at": result.retrieved_at, "content_sha256": sha256_file(destination)})
    retrieved_at = verify_source(destination, f"{BASE}/yearlyClassification{year}/{name}",
                                cache_dir=getattr(client, "cache_dir", None))["retrieved_at"]

    return measure_year(year, name, destination, bounds, aoi_geometry=None, retrieved_at=retrieved_at)


def measure_year(
    year: int,
    name: str,
    path: Path,
    bounds: tuple[float, float, float, float],
    *,
    aoi_geometry: Any = None,
    retrieved_at: str | None = None,
    extent_path: Path | None = None,
) -> GswRecord:
    """Read a tile, optionally clip to an AOI, and summarise observed water.

    ``extent_path`` is the Maximum Water Extent tile on the same grid. Without
    it the share is null with ``share_status`` ``max_extent_unavailable``.
    """
    with rasterio.open(path) as dataset:
        if aoi_geometry is not None:
            geometry = aoi_geometry
            if hasattr(geometry, "geometry"):
                series = geometry.geometry
                geometry = series.union_all() if hasattr(series, "union_all") else series.unary_union
            from rasterio.mask import raster_geometry_mask
            outside, _, window = raster_geometry_mask(dataset, [geometry], crop=True)

            def read(source):
                return source.read(1, window=window, masked=False)[~outside]
        else:
            window = dataset.window(*bounds)

            # Read in-bounds source codes without applying the TIFF nodata tag:
            # class zero is a reportable no-observation class, not outside AOI.
            def read(source):
                return source.read(1, window=window, masked=False).ravel()

        array = read(dataset)
        extent = None
        if extent_path is not None:
            with rasterio.open(extent_path) as extent_dataset:
                if (extent_dataset.crs != dataset.crs or extent_dataset.shape != dataset.shape
                        or not extent_dataset.transform.almost_equals(
                            dataset.transform, precision=GRID_TOLERANCE_DEGREES)):
                    raise ValueError(f"{Path(extent_path).name} is not on the yearly tile's grid")
                extent = read(extent_dataset)

    water_mask, known_mask = share_support(array, extent)
    water = int(water_mask.sum())
    classified = int((array != CODE_NO_OBSERVATIONS).sum())
    pixel_area_km2 = float((PIXEL_DEGREES * 111.32) ** 2 * np.cos(np.radians(np.mean(bounds[1::2]))))
    known = never_water = unknown = None
    share, status = None, "max_extent_unavailable"
    if known_mask is not None:
        known = int(known_mask.sum())
        never_water, unknown = known - classified, int(array.size) - known
        share, status = (water / known, "ok") if known else (None, "no_known_pixels")
    return GswRecord(
        year=year,
        tile_name=name,
        local_path=str(path),
        content_sha256=sha256_file(path),
        byte_count=path.stat().st_size,
        retrieved_at=retrieved_at or utc_now_iso(),
        aoi_pixels=int(array.size),
        aoi_water_pixels=water,
        classified_pixels=classified,
        never_water_pixels=never_water,
        unknown_pixels=unknown,
        known_pixels=known,
        aoi_water_share=share,
        share_status=status,
        aoi_water_km2=water * pixel_area_km2,
        classified_km2=classified * pixel_area_km2,
        known_km2=None if known is None else known * pixel_area_km2,
        aoi_seasonal_pixels=int((array == CODE_SEASONAL).sum()),
        aoi_permanent_pixels=int((array == CODE_PERMANENT).sum()),
        aoi_no_observation_pixels=int((array == CODE_NO_OBSERVATIONS).sum()),
    )


EXTENT_WATER = 1
#: Public aggregation grid, the same as the yearly observed-water cells.
EXTENT_GRID_M = 1000


#: A window larger than this is refused before it is read (a whole province
#: would need gigabytes); Bangkok's is about 3.5 million pixels.
EXTENT_MAX_WINDOW_PIXELS = 50_000_000


def measure_extent(path: Path, aoi_geometry: Any) -> dict[str, Any]:
    """Summarise the 1984-2021 Maximum Water Extent tile at ``path`` inside an AOI."""
    with rasterio.open(path, driver="GTiff") as dataset:
        return measure_extent_dataset(dataset, aoi_geometry)


def measure_extent_dataset(dataset: Any, aoi_geometry: Any) -> dict[str, Any]:
    """Summarise an open Maximum Water Extent raster inside an AOI.

    Code 1 was detected as water at least once, 0 never, and 255 has no data,
    which stays unknown and out of the share. The raster must be the JRC
    product on its 0.00025 degree EPSG:4326 grid, hold only those codes, and
    cover the whole AOI; anything else raises ``ValueError`` rather than being
    measured wrongly or truncated.

    Areas use ``measure_year``'s pixel area, so the total is comparable with
    the yearly water areas; the yearly 1 km cells use a slightly different
    footprint (about 0.7 percent). A cell's share is over its pixels inside
    the AOI, so a sliver at the boundary can be wholly wet. Read-only.
    """
    from rasterio import mask as rasterio_mask
    from rasterio.features import geometry_window

    raster_geometry_mask = rasterio_mask.raster_geometry_mask
    geometry = aoi_geometry
    if hasattr(geometry, "geometry"):
        series = geometry.geometry
        geometry = series.union_all() if hasattr(series, "union_all") else series.unary_union
    _check_extent_grid(dataset, geometry)
    # Size the window before anything is allocated for it.
    window = geometry_window(dataset, [geometry])
    if window.width * window.height > EXTENT_MAX_WINDOW_PIXELS:
        raise ValueError(f"the AOI window of {window.width} x {window.height} pixels exceeds the cap")
    outside, transform, window = raster_geometry_mask(dataset, [geometry], crop=True)
    data = dataset.read(1, window=window, masked=False)
    inside = ~outside
    if not np.isin(data[inside], list(EXTENT_CODES)).all():
        raise ValueError("the extent holds codes other than 0, 1 and 255")
    water = (data == EXTENT_WATER) & inside
    observed = inside & (data != EXTENT_NODATA)
    bounds = geometry.bounds
    pixel_area_km2 = float((PIXEL_DEGREES * 111.32) ** 2 * np.cos(np.radians((bounds[1] + bounds[3]) / 2)))
    aoi_pixels, water_pixels = int(inside.sum()), int(water.sum())
    observed_pixels = int(observed.sum())
    no_data_pixels = aoi_pixels - observed_pixels
    cells = _extent_cells(water, observed, transform, dataset.crs, pixel_area_km2) if water_pixels else []
    return {
        "aoi_pixels": aoi_pixels,
        "ever_water_pixels": water_pixels,
        "no_data_pixels": no_data_pixels,
        "pixel_area_km2": pixel_area_km2,
        "aoi_km2": aoi_pixels * pixel_area_km2,
        "ever_water_km2": water_pixels * pixel_area_km2,
        "no_data_km2": no_data_pixels * pixel_area_km2,
        "ever_water_share_of_observed": water_pixels / observed_pixels if observed_pixels else None,
        "cells": cells,
    }


def _check_extent_grid(dataset: Any, geometry: Any) -> None:
    """The JRC grid, a 255 nodata tag (or none), and an AOI inside the tile."""
    if dataset.nodata not in (None, EXTENT_NODATA):
        raise ValueError(f"the extent has nodata tag {dataset.nodata}, not {EXTENT_NODATA}")
    a, b, _, d, e, _ = tuple(dataset.transform)[:6]
    north_up = b == 0 and d == 0 and a > 0 and e < 0
    on_grid = (
        _is_wgs84(dataset.crs)
        and north_up
        and abs(a - PIXEL_DEGREES) <= GRID_TOLERANCE_DEGREES
        and abs(-e - PIXEL_DEGREES) <= GRID_TOLERANCE_DEGREES
    )
    if not on_grid:
        raise ValueError("the extent is not on the JRC 0.00025 degree EPSG:4326 grid")
    left, bottom, right, top = dataset.bounds
    west, south, east, north = geometry.bounds
    slack = PIXEL_DEGREES / 2
    if west < left - slack or east > right + slack or south < bottom - slack or north > top + slack:
        raise ValueError("the AOI reaches beyond the extent tile, so it would be truncated")


def _is_wgs84(crs: Any) -> bool:
    """EPSG:4326 by comparing the stored WKT with pyproj's own database.

    rasterio's EPSG lookup returns None where PROJ_LIB points at an older
    proj.db, although the tile's WKT is intact; pyproj ships its own.
    """
    import pyproj

    if crs is None:
        return False
    try:
        return pyproj.CRS.from_user_input(crs.to_wkt()).equals(
            pyproj.CRS.from_epsg(4326), ignore_axis_order=True
        )
    except pyproj.exceptions.CRSError:
        return False


def _transform(transformer: Any, xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Transform arrays of any length; pyproj's single-point path is deprecated for arrays."""
    if np.size(xs) == 1:
        x, y = transformer.transform(float(np.ravel(xs)[0]), float(np.ravel(ys)[0]))
        return np.array([x]), np.array([y])
    x, y = transformer.transform(xs, ys)
    return np.asarray(x), np.asarray(y)


def _extent_cells(
    water: np.ndarray, observed: np.ndarray, transform: Any, crs: Any, pixel_area_km2: float
) -> list[dict[str, Any]]:
    """Bin observed extent pixels into the public 1 km grid (yearly cells' ids)."""
    from pyproj import Transformer

    rows, cols = np.nonzero(observed)
    lons = transform.c + transform.a * (cols + 0.5)
    lats = transform.f + transform.e * (rows + 0.5)
    x, y = _transform(Transformer.from_crs(crs, "EPSG:32647", always_xy=True), lons, lats)
    grid = pd.DataFrame({
        "gx": (np.floor(np.asarray(x) / EXTENT_GRID_M) * EXTENT_GRID_M).astype("int64"),
        "gy": (np.floor(np.asarray(y) / EXTENT_GRID_M) * EXTENT_GRID_M).astype("int64"),
        "w": water[rows, cols].astype("int64"),
        "v": 1,
    }).groupby(["gx", "gy"])[["w", "v"]].sum().reset_index()
    grid = grid[grid["w"] > 0]
    centres_x = grid["gx"] + EXTENT_GRID_M / 2.0
    centres_y = grid["gy"] + EXTENT_GRID_M / 2.0
    lon_c, lat_c = _transform(
        Transformer.from_crs("EPSG:32647", "OGC:CRS84", always_xy=True),
        centres_x.to_numpy(),
        centres_y.to_numpy(),
    )
    return [
        {
            "cell_id": f"ow_{int(row.gx)}_{int(row.gy)}",
            "x": float(x_c),
            "y": float(y_c),
            "lon": float(lon),
            "lat": float(lat),
            "water_px": int(row.w),
            "valid_px": int(row.v),
            "water_share": float(row.w) / float(row.v),
            "water_km2": float(row.w) * pixel_area_km2,
        }
        for row, x_c, y_c, lon, lat in zip(grid.itertuples(), centres_x, centres_y, lon_c, lat_c)
    ]


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


def fetch_extent(
    client: HttpClient, bounds: tuple[float, float, float, float], target_dir: Path
) -> tuple[Path | None, dict[str, Any]]:
    """Stage the Maximum Water Extent tile once for every year.

    A failed download is recorded and leaves the shares null; it never brings
    back water / classified. Bytes that fail provenance still raise.
    """
    name = extent_tile_name_for(bounds)
    destination = target_dir / name
    resource_url = f"{EXTENT_BASE}/{name}"
    if not destination.is_file():
        try:
            result = client.get(resource_url, use_cache=True, retries=2, timeout=900)
        except Exception as error:  # noqa: BLE001 - recorded, not fatal
            return None, {"source_id": EXTENT_SOURCE_ID, "status": "unavailable",
                          "tile_name": name, "reason": str(error)[:200]}
        destination.write_bytes(result.body)
        write_json(destination.with_suffix(".provenance.json"), {"resource_url": resource_url,
            "retrieved_at": result.retrieved_at, "content_sha256": sha256_file(destination)})
    metadata = verify_source(destination, resource_url, cache_dir=getattr(client, "cache_dir", None))
    return destination, {"source_id": EXTENT_SOURCE_ID, "status": "ok", "tile_name": name,
                         "byte_count": destination.stat().st_size, **metadata}


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
    extent_path, max_extent = fetch_extent(client, bounds, target_dir)
    records: list[GswRecord] = []
    unavailable: list[dict[str, Any]] = []
    for year in years:
        name = tile_name_for(year, bounds)
        destination = target_dir / name
        sidecar = destination.with_suffix(".provenance.json")
        resource_url = f"{BASE}/yearlyClassification{year}/{name}"
        if not destination.is_file():
            try:
                result = client.get(
                    resource_url, use_cache=True, retries=2, timeout=900
                )
            except Exception as error:  # noqa: BLE001 - recorded, not fatal
                # The downloadable set does not necessarily span every year the
                # product is described as covering. Record the gap instead of
                # failing the whole multi-year comparison.
                unavailable.append({"year": year, "tile": name, "error": str(error)[:200]})
                continue
            destination.write_bytes(result.body)
            write_json(sidecar, {"resource_url": resource_url,
                "retrieved_at": result.retrieved_at, "content_sha256": sha256_file(destination)})
        metadata = verify_source(destination, resource_url, cache_dir=getattr(client, "cache_dir", None))
        retrieved_at = metadata["retrieved_at"]
        records.append(
            measure_year(
                year, name, destination, bounds,
                aoi_geometry=aoi_frame, retrieved_at=retrieved_at, extent_path=extent_path,
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
        "max_extent": max_extent,
        "max_extent_codes": EXTENT_CODES,
        "share_basis": SHARE_BASIS,
        "is_observation": True,
        "measures": "water extent, NOT depth, duration or direction",
        "baseline_year": baseline_year,
        "years": years_payload,
        "interpretation_notes": [
            "Annual water classes are not event-flood extent or flood peak estimates.",
            "Yearly code 0 outside the JRC Maximum Water Extent was never detected as water "
            "and counts as not water. Code 0 inside it is unobserved that year; no observations "
            "is not dry land, so it stays out of the share. Without the extent the share is null.",
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
