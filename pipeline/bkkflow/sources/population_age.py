"""Per-cell age-band weights from the WorldPop age/sex rasters.

The rasters are 100 m EPSG:4326 constrained estimates in which each file holds
one age band for both sexes (``tha_t_<band>_...tif``). Summing the files gives a
NATIONAL marginal, which is the wrong geography for a small urban district:
across the four pilot AOIs the 65+ share runs from 9.5% to 19.3%.

Sampling at each population cell's centre instead recovers that variation. The
population raster and the age/sex rasters share CRS and resolution but differ by
one column and eight rows, so this nearest-neighbour lookup IS the declared
reprojection onto the population grid -- it is explicit and recorded, not an
implicit assumption that the grids coincide.

Licence: WorldPop, CC BY 4.0. DOI 10.5258/SOTON/WP00841.
Modelled aggregate estimates in age bands; these are NOT individual records and
NOT household composition.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

#: WorldPop band code -> the label used in ``age_band``. Band 00 is 0-12 months
#: and 01 is 1-4 years; the rest are five-year bands up to 90+.
BAND_CODES = ("00", "01", "05", "10", "15", "20", "25", "30", "35", "40",
              "45", "50", "55", "60", "65", "70", "75", "80", "85", "90")

BAND_LABELS = {
    "00": "0_12m", "01": "1_4", "05": "5_9", "10": "10_14", "15": "15_19",
    "20": "20_24", "25": "25_29", "30": "30_34", "35": "35_39", "40": "40_44",
    "45": "45_49", "50": "50_54", "55": "55_59", "60": "60_64", "65": "65_69",
    "70": "70_74", "75": "75_79", "80": "80_84", "85": "85_89", "90": "90_plus",
}

SOURCE_ID = "worldpop-tha-age-sex-2026-r2025a"
DOI = "10.5258/SOTON/WP00841"
LICENCE = "CC BY 4.0"


def band_paths(raster_dir: Path | str, year: int = 2026, release: str = "R2025A") -> dict[str, Path]:
    """Expected raster path per band code, for verification before reading."""
    root = Path(raster_dir)
    return {
        code: root / f"tha_t_{code}_{year}_CN_100m_{release}_v1.tif"
        for code in BAND_CODES
    }


def missing_bands(raster_dir: Path | str) -> list[str]:
    """Band codes whose raster is absent. Reported rather than silently skipped."""
    return [code for code, path in band_paths(raster_dir).items() if not path.is_file()]


def _read_band(path: Path, coordinates: list[tuple[float, float]]) -> np.ndarray:
    import rasterio

    with rasterio.open(path) as src:
        nodata = src.nodata if src.nodata is not None else -99999.0
        values = np.array([sample[0] for sample in src.sample(coordinates)], dtype="float64")
    return np.where(np.isfinite(values) & (values != nodata), values, 0.0)


def age_weights_by_cell(
    cells: pd.DataFrame,
    raster_dir: Path | str,
) -> dict[str, dict[str, float]]:
    """Per-``cell_id`` age-band shares, sampled from the age/sex rasters.

    ``cells`` must carry ``cell_id``, ``lon`` and ``lat``. Each cell's band
    weights are normalised across bands; a cell with no population in any band
    is omitted so the caller can fall back rather than record an invented zero.
    """
    missing = missing_bands(raster_dir)
    if missing:
        raise FileNotFoundError(
            f"{SOURCE_ID}: {len(missing)} band rasters are absent from {raster_dir}: "
            f"{', '.join(missing)}"
        )

    coordinates = list(zip(cells["lon"].to_numpy(), cells["lat"].to_numpy()))
    per_band = {
        code: _read_band(path, coordinates)
        for code, path in band_paths(raster_dir).items()
    }

    result: dict[str, dict[str, float]] = {}
    for position, cell_id in enumerate(cells["cell_id"]):
        weights = {BAND_LABELS[code]: float(values[position]) for code, values in per_band.items()}
        total = sum(weights.values())
        if total > 0:
            result[str(cell_id)] = {label: weight / total for label, weight in weights.items()}
    return result


def summarise_by_area(
    weights_by_cell: dict[str, dict[str, float]],
) -> dict[str, float]:
    """Aggregate per-cell shares into one marginal, for an AOI-level summary."""
    if not weights_by_cell:
        return {}
    labels = list(next(iter(weights_by_cell.values())))
    return {label: sum(m.get(label, 0.0) for m in weights_by_cell.values()) for label in labels}


def provenance(raster_dir: Path | str, year: int = 2026) -> dict[str, Any]:
    """Minimal record for the run manifest."""
    return {
        "source_id": SOURCE_ID,
        "doi": DOI,
        "licence": LICENCE,
        "year": year,
        "resolution": "100m (3 arc), EPSG:4326",
        "raster_dir": str(raster_dir),
        "bands": len(BAND_CODES),
        "method": "nearest-neighbour sampling at population cell centres",
        "reprojection": "explicit: population and age/sex grids differ by 1 column and 8 rows",
        "meaning": "modelled aggregate age structure; not individual records, not household composition",
        "temporal_note": "age/sex year differs from the population baseline year",
    }