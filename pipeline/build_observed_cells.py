"""Build a 1 km observed-water cell layer from the cached GSW tiles.

The observed extent is the only measured hazard layer in the project, so it
should be visible on the map rather than only as a table of numbers. Rendering
it at the source 30 m would mean serving hundreds of thousands of points, so it
is aggregated to the same fixed 1 km public grid the population uses.

This reads tiles that are already staged, so it does not require re-running the
city pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask as rio_mask

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bkkflow import aoi as aoi_module  # noqa: E402
from bkkflow.sources import gsw  # noqa: E402
from bkkflow.util import CURATED_DIR, ensure_dir, sha256_file, utc_now_iso  # noqa: E402

GRID_M = 1000.0
YEARS = (2010, 2011, 2012, 2020)


def cell_id(x: float, y: float) -> str:
    return f"ow_{int(x)}_{int(y)}"


def build(*, out_dir: Path | None = None) -> dict:
    aoi = aoi_module.load_aoi("bangkok-bma")
    aoi_wgs84 = aoi.geometry.iloc[0]
    bounds = tuple(float(value) for value in aoi_wgs84.bounds)
    projected = aoi.to_crs("EPSG:32647")
    poly = projected.geometry.union_all()
    minx, miny, maxx, maxy = poly.bounds

    target = ensure_dir(out_dir or CURATED_DIR / "city")
    destination = target / "observed_water_cells.parquet"

    records: list[dict] = []
    per_year: dict[int, dict] = {}

    for year in YEARS:
        name = gsw.tile_name_for(year, bounds)
        path = Path("data/staged/gsw") / name
        if not path.is_file():
            per_year[year] = {"status": "tile_not_staged"}
            continue
        with rasterio.open(path) as dataset:
            data, transform = rio_mask(
                dataset, [aoi_wgs84], crop=True, filled=True, nodata=gsw.CODE_NO_OBSERVATIONS
            )
        array = data[0]
        rows, cols = array.shape
        # Cell-centre coordinates in the raster CRS, then a projected grid.
        col_index = np.arange(cols)
        row_index = np.arange(rows)
        xs = transform.c + transform.a * (col_index + 0.5)
        ys = transform.f + transform.e * (row_index + 0.5)
        lons, lats = np.meshgrid(xs, ys)

        from pyproj import Transformer

        to_analysis = Transformer.from_crs(dataset.crs, "EPSG:32647", always_xy=True)
        px, py = to_analysis.transform(lons.ravel(), lats.ravel())

        gx = (np.floor(px / GRID_M) * GRID_M).astype("int64")
        gy = (np.floor(py / GRID_M) * GRID_M).astype("int64")

        water = gsw.is_water(array).ravel()
        land = (~np.isin(array.ravel(), gsw.CODE_NODATA)).ravel()

        paired = pd.DataFrame({"gx": gx, "gy": gy, "w": water.astype("int64"), "c": land.astype("int64")})
        grouped = paired.groupby(["gx", "gy"])[["w", "c"]].sum()
        grouped = grouped[(grouped["c"] > 0) & (grouped["w"] > 0)]
        grouped = grouped.reset_index()

        # Pixel footprint in km^2 at this latitude band: 0.00025 deg of
        # longitude by 0.00025 deg of latitude, converted from square metres.
        pixel_width_m = 0.00025 * 111320.0 * np.cos(np.radians(13.7))
        pixel_height_m = 0.00025 * 110574.0
        area_per_px = float(pixel_width_m * pixel_height_m) / 1e6
        for row in grouped.itertuples():
            records.append(
                {
                    "cell_id": cell_id(row.gx, row.gy),
                    "year": year,
                    "x": row.gx + GRID_M / 2.0,
                    "y": row.gy + GRID_M / 2.0,
                    "water_px": int(row.w),
                    "classified_px": int(row.c),
                    "water_share": float(row.w) / float(row.c) if row.c else 0.0,
                    "water_km2": float(row.w) * area_per_px,
                    "source_role": "observed",
                    "measures": "extent_only",
                }
            )
        per_year[year] = {
            "status": "ok",
            "cells_with_water": int(len(grouped)),
            "water_km2": float(grouped["w"].sum() * area_per_px),
        }
        print(f"  {year}: {len(grouped)} 1 km cells contain observed water")

    columns = ["cell_id", "year", "x", "y", "lon", "lat", "water_px", "classified_px",
               "water_share", "water_km2", "source_role", "measures"]
    frame = pd.DataFrame.from_records(records, columns=columns)
    if not frame.empty:
        frame = gpd.GeoDataFrame(
            frame, geometry=gpd.points_from_xy(frame["x"], frame["y"]), crs="EPSG:32647"
        )
        # GeoJSON is WGS84 by specification (RFC 7946), so publish real
        # longitude and latitude rather than projected metres with misleading
        # column names. The analysis-CRS x/y are kept alongside.
        wgs84 = frame.to_crs("OGC:CRS84")
        frame["lon"] = wgs84.geometry.x
        frame["lat"] = wgs84.geometry.y
        frame = frame[["cell_id", "year", "x", "y", "lon", "lat", "water_px", "classified_px",
                       "water_share", "water_km2", "source_role", "measures"]]
    frame.to_parquet(destination, index=False)

    return {
        "path": str(destination),
        "rows": int(len(frame)),
        "years": sorted(int(year) for year in per_year),
        "per_year": per_year,
        "grid_size_m": GRID_M,
        "sha256": sha256_file(destination) if destination.is_file() else None,
        "written_at": utc_now_iso(),
        "note": (
            "Aggregated to a 1 km projected grid. Extent only: no depth, duration or "
            "direction. Annual classes do not resolve flood-event timing or peak extent; "
            "no observations is not dry land."
        ),
    }


if __name__ == "__main__":
    import json

    result = build()
    target = CURATED_DIR / "city" / "observed_water_cells.provenance.json"
    from bkkflow.util import write_json

    write_json(target, result)
    print(json.dumps(result, indent=2)[:900])
