"""Terrain acquisition: terrarium tiles to a clipped digital elevation model.

Why this module exists
----------------------
At pilot scale the flood surface could be a distance-to-water decay, because a
5.96 km2 district is small enough that "near water" and "flooded" are roughly
the same thing. Across the whole Bangkok Metropolitan Administration that stops
being true: the city has thousands of mapped canals, so a proximity model marks
almost everywhere as exposed and answers no useful question.

With terrain, flooding can be derived from elevation instead: a water-surface
elevation for the river and canal network, and depth wherever the ground lies
below it. Low-lying basins away from canals are then represented, which is the
plan's drainage-blindness risk.

What this is not
----------------
This is a screening terrain surface assembled from an aggregated open tile
service, not a survey DEM. Bangkok is famously flat, so a small vertical error
maps to a large change in flooded area. Every consumer of this module must
treat the flooded area as sensitive to the water-surface level and report that
sensitivity rather than a single number.
"""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..http import HttpClient
from ..util import STAGED_DIR, ensure_dir, sha256_file, utc_now_iso, write_json

SOURCE_ID = "aws-terrain-tiles-terrarium"
TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
TILE_SIZE = 256

# Bangkok sits at roughly 1-2 m above mean sea level across a wide floodplain.
# These are the stage levels the screening surface is evaluated at, in metres
# relative to the same vertical datum as the tiles.
SUGGESTED_STAGES_M = (0.9, 1.2, 1.5, 1.8, 2.1)


@dataclass
class TerrainRecord:
    source_id: str
    zoom: int
    tile_count: int
    byte_count: int
    content_sha256: str
    retrieved_at: str
    resolution_m: float
    dem_path: str
    bounds_wgs84: tuple[float, float, float, float]
    elevation_min_m: float
    elevation_max_m: float
    elevation_p05_m: float
    elevation_p95_m: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "zoom": self.zoom,
            "tile_count": self.tile_count,
            "byte_count": self.byte_count,
            "content_sha256": self.content_sha256,
            "retrieved_at": self.retrieved_at,
            "resolution_m": round(self.resolution_m, 3),
            "dem_path": self.dem_path,
            "bounds_wgs84": [round(value, 6) for value in self.bounds_wgs84],
            "elevation_min_m": round(self.elevation_min_m, 3),
            "elevation_max_m": round(self.elevation_max_m, 3),
            "elevation_p05_m": round(self.elevation_p05_m, 3),
            "elevation_p95_m": round(self.elevation_p95_m, 3),
        }


def lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    """Standard XYZ tile index for a WGS84 coordinate."""
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2.0**zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def tile_to_bounds(x: int, y: int, zoom: int) -> tuple[float, float, float, float]:
    """WGS84 bounds (west, south, east, north) of an XYZ tile."""
    n = 2.0**zoom
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2.0 * y / n)))
    north = math.degrees(lat_rad)
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2.0 * (y + 1) / n)))
    south = math.degrees(lat_rad)
    return west, south, east, north


def tiles_for_bounds(bounds: tuple[float, float, float, float], zoom: int) -> list[tuple[int, int]]:
    west, south, east, north = bounds
    # In XYZ, north has the SMALLER y index and south the larger, so the
    # north-west corner yields (x_min, y_min) and the south-east corner
    # yields (x_max, y_max). Getting this pairing backwards yields an empty
    # range and silently downloads nothing.
    x_min, y_min = lonlat_to_tile(west, north, zoom)
    x_max, y_max = lonlat_to_tile(east, south, zoom)
    return [(x, y) for x in range(x_min, x_max + 1) for y in range(y_min, y_max + 1)]


def decode_terrarium(payload: bytes) -> np.ndarray:
    """Decode a terrarium PNG tile into metres above the tile datum.

    Terrarium encoding: elevation_m = (R * 256 + G + B / 256) - 32768.
    Decoding needs only zlib and the PNG scanline filter reconstruction, so the
    module has no image-library dependency.
    """
    rgb = _decode_png_to_rgb(payload)
    return _terrarium_to_metres(rgb)


def _terrarium_to_metres(rgb: np.ndarray) -> np.ndarray:
    red = rgb[:, :, 0].astype("float64")
    green = rgb[:, :, 1].astype("float64")
    blue = rgb[:, :, 2].astype("float64")
    return (red * 256.0 + green + blue / 256.0) - 32768.0


def _decode_png_to_rgb(payload: bytes) -> np.ndarray:
    """Minimal PNG reader returning an (H, W, 3) uint8 RGB array."""
    if payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG tile")
    position = 8
    width = height = bit_depth = colour_type = interlace = None
    idat = bytearray()
    while position < len(payload):
        (length,) = struct.unpack(">I", payload[position : position + 4])
        chunk_type = payload[position + 4 : position + 8]
        chunk_data = payload[position + 8 : position + 8 + length]
        position += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, colour_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
        elif chunk_type == b"IDAT":
            idat += chunk_data
        elif chunk_type == b"IEND":
            break
    if bit_depth != 8 or interlace != 0:
        raise ValueError(f"unsupported PNG (bit_depth={bit_depth}, interlace={interlace})")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(colour_type)
    if channels is None:
        raise ValueError(f"unsupported PNG colour type {colour_type}")

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = np.zeros((height, stride), dtype="uint8")
    previous = np.zeros(stride, dtype="uint8")
    cursor = 0
    for row in range(height):
        filter_type = raw[cursor]
        cursor += 1
        line = np.frombuffer(raw[cursor : cursor + stride], dtype="uint8").astype("int32").copy()
        cursor += stride
        if filter_type == 1:  # Sub
            for index in range(channels, stride):
                line[index] = (line[index] + line[index - channels]) & 0xFF
        elif filter_type == 2:  # Up
            line = (line + previous.astype("int32")) & 0xFF
        elif filter_type == 3:  # Average
            for index in range(stride):
                left = line[index - channels] if index >= channels else 0
                line[index] = (line[index] + ((left + int(previous[index])) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for index in range(stride):
                left = int(line[index - channels]) if index >= channels else 0
                up = int(previous[index])
                up_left = int(previous[index - channels]) if index >= channels else 0
                estimate = left + up - up_left
                da, db, dc = abs(estimate - left), abs(estimate - up), abs(estimate - up_left)
                if da <= db and da <= dc:
                    predictor = left
                elif db <= dc:
                    predictor = up
                else:
                    predictor = up_left
                line[index] = (line[index] + predictor) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"unsupported PNG filter {filter_type}")
        out[row] = line.astype("uint8")
        previous = out[row]

    array = out.reshape(height, width, channels)
    if channels == 1:
        return np.repeat(array, 3, axis=2)
    if channels == 2:
        return np.repeat(array[:, :, :1], 3, axis=2)
    if channels == 4:
        return array[:, :, :3]
    return array[:, :, :3]


def tile_url(x: int, y: int, zoom: int) -> str:
    return TILE_URL.format(z=zoom, x=x, y=y)


def download_tiles(
    client: HttpClient,
    bounds: tuple[float, float, float, float],
    zoom: int,
    cache_dir: str | Path | None = None,
) -> tuple[list[Path], dict[str, Any]]:
    """Fetch every terrarium tile covering the bounds, with on-disk caching.

    Tiles are cached individually so an interrupted city-scale fetch resumes
    instead of restarting.
    """
    target = ensure_dir(Path(cache_dir or STAGED_DIR / "terrain" / f"z{zoom}"))
    tiles = tiles_for_bounds(bounds, zoom)
    paths: list[Path] = []
    downloaded = 0
    total_bytes = 0
    for x, y in tiles:
        path = target / f"{zoom}_{x}_{y}.png"
        if not path.is_file():
            url = tile_url(x, y, zoom)
            result = client.get(url, use_cache=False, retries=4, timeout=120)
            path.write_bytes(result.body)
            downloaded += 1
            total_bytes += len(result.body)
        else:
            total_bytes += path.stat().st_size
        paths.append(path)
    return paths, {
        "zoom": zoom,
        "tiles_required": len(tiles),
        "tiles_downloaded": downloaded,
        "tile_bytes": total_bytes,
        "retrieved_at": utc_now_iso(),
    }


def mosaic_dem(
    tile_paths: list[Path], bounds: tuple[float, float, float, float], zoom: int
) -> tuple[np.ndarray, tuple[float, float, float, float], float]:
    """Assemble tiles into one elevation array over the requested bounds.

    Returns the array, the WGS84 bounds it covers, and the per-pixel ground
    resolution in metres at the mosaic centre latitude.
    """
    west, south, east, north = bounds
    cols = max(int(round((east - west) / 360.0 * 2.0**zoom * TILE_SIZE)), 1)
    rows = max(int(round((north - south) / 360.0 * 2.0**zoom * TILE_SIZE)), 1)
    mosaic = np.full((rows, cols), np.nan, dtype="float64")

    for path in tile_paths:
        name = path.stem
        try:
            _, x_text, y_text = name.split("_")
            x, y = int(x_text), int(y_text)
        except ValueError:
            continue
        tile_west, tile_south, tile_east, tile_north = tile_to_bounds(x, y, zoom)
        # Pixel offsets of this tile within the mosaic grid.
        col0 = int(round((tile_west - west) / 360.0 * 2.0**zoom * TILE_SIZE))
        row0 = int(round((north - tile_north) / 360.0 * 2.0**zoom * TILE_SIZE))
        decoded = decode_terrarium(path.read_bytes())
        tile_rows, tile_cols = decoded.shape
        col1 = min(col0 + tile_cols, cols)
        row1 = min(row0 + tile_rows, rows)
        src_col0 = max(0, -col0)
        src_row0 = max(0, -row0)
        if col1 <= 0 or row1 <= 0:
            continue
        block = decoded[src_row0 : src_row0 + (row1 - row0), src_col0 : src_col0 + (col1 - col0)]
        mosaic[row0:row1, col0:col1] = block

    mid_lat = (south + north) / 2.0
    resolution_m = 156543.03392 * math.cos(math.radians(mid_lat)) / 2.0**zoom
    return mosaic, (west, south, east, north), resolution_m


def clip_mask_for_aoi(
    shape_geometry, mosaic_bounds: tuple[float, float, float, float], shape: tuple[int, int]
) -> np.ndarray:
    """Boolean mask of mosaic cells inside an AOI polygon."""
    # `import rasterio.features as rfeatures` binds only `rfeatures`, so the
    # submodule name `rasterio` is still unbound here. Import it explicitly or
    # the transform lookup below raises NameError on every DEM fetch.
    import rasterio.features as rfeatures
    import rasterio.transform

    rows, cols = shape
    west, south, east, north = mosaic_bounds
    transform = rasterio.transform.from_bounds(west, south, east, north, cols, rows)
    if shape_geometry.geom_type == "MultiPolygon":
        geometry = max(shape_geometry.geoms, key=lambda part: part.area)
    else:
        geometry = shape_geometry
    return rfeatures.geometry_mask(
        [geometry], out_shape=(rows, cols), transform=transform, invert=True
    )


def write_dem(
    array: np.ndarray,
    bounds: tuple[float, float, float, float],
    out_path: str | Path,
    *,
    nodata: float = -32768.0,
) -> dict[str, Any]:
    """Write the mosaic as a compressed GeoTIFF in EPSG:4326."""
    import rasterio

    path = Path(out_path)
    ensure_dir(path.parent)
    west, south, east, north = bounds
    rows, cols = array.shape
    transform = rasterio.transform.from_bounds(west, south, east, north, cols, rows)
    data = np.where(np.isnan(array), nodata, array).astype("float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as writer:
        writer.write(data, 1)
    return {
        "path": str(path),
        "rows": int(rows),
        "cols": int(cols),
        "bounds_wgs84": [round(value, 6) for value in bounds],
        "sha256": sha256_file(path),
        "written_at": utc_now_iso(),
    }


def terrain_summary(array: np.ndarray) -> dict[str, float]:
    """Distribution of terrain, which is what a flat floodplain needs shown as."""
    valid = array[np.isfinite(array)]
    if valid.size == 0:
        return {}
    return {
        "min_m": float(valid.min()),
        "max_m": float(valid.max()),
        "mean_m": float(valid.mean()),
        "p05_m": float(np.percentile(valid, 5)),
        "p25_m": float(np.percentile(valid, 25)),
        "median_m": float(np.median(valid)),
        "p75_m": float(np.percentile(valid, 75)),
        "p95_m": float(np.percentile(valid, 95)),
    }


def build_city_dem(
    client: HttpClient,
    *,
    bounds: tuple[float, float, float, float],
    aoi_geometry_wgs84,
    zoom: int = 13,
    out_path: str | Path | None = None,
) -> tuple[np.ndarray, dict[str, Any], TerrainRecord]:
    """Fetch, mosaic, clip and summarise the terrain for an area.

    This is the single entry point the pipeline uses, so the tile maths, caching
    and provenance live in one place.
    """
    tile_paths, fetch_report = download_tiles(client, bounds, zoom)
    mosaic, mosaic_bounds, resolution_m = mosaic_dem(tile_paths, bounds, zoom)
    mask = clip_mask_for_aoi(aoi_geometry_wgs84, mosaic_bounds, mosaic.shape)
    mosaic = np.where(mask, mosaic, np.nan)

    target = Path(out_path or STAGED_DIR / "terrain" / f"bangkok_dem_z{zoom}.tif")
    write_report = write_dem(mosaic, mosaic_bounds, target)
    summary = terrain_summary(mosaic)
    record = TerrainRecord(
        source_id=SOURCE_ID,
        zoom=zoom,
        tile_count=fetch_report["tiles_required"],
        byte_count=fetch_report["tile_bytes"],
        content_sha256=write_report["sha256"],
        retrieved_at=fetch_report["retrieved_at"],
        resolution_m=resolution_m,
        dem_path=str(target),
        bounds_wgs84=mosaic_bounds,
        elevation_min_m=summary.get("min_m", float("nan")),
        elevation_max_m=summary.get("max_m", float("nan")),
        elevation_p05_m=summary.get("p05_m", float("nan")),
        elevation_p95_m=summary.get("p95_m", float("nan")),
    )
    provenance = {
        "record": record.as_dict(),
        "terrain_summary": summary,
        "write": write_report,
        "vertical_datum_note": (
            "Terrarium tiles encode metres relative to the upstream source datums. "
            "Absolute stage levels must be treated as approximate for a floodplain this flat."
        ),
    }
    write_json(target.with_suffix(".provenance.json"), provenance)
    return mosaic, provenance, record
