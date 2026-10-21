"""The 1984-2021 JRC Maximum Water Extent for a run's area (BKK-055c).

No run stores the ever-water area or cells, but a city run records the exact
extent tile it used (``observed_water.json`` -> ``max_extent``). This module
serves the extent only for that tile: the staged bytes must hash to the
recorded SHA-256. A missing, different or unrecorded tile is reported with a
reason, never as zero water. Nothing is written; results are cached by the
tile's identity.

The extent marks everywhere ever detected as water in 1984-2021. It is not one
flood and carries no depth.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from api.models import ApiWarning
from api.runs import RunRef
from api.settings import Settings
from api.tables import artefact_path, feature, make_warning
from pipeline.bkkflow.sources import gsw
from pipeline.bkkflow.util import sha256_file

MEASURES = (
    "everywhere ever detected as water in 1984-2021 (JRC Maximum Water Extent); "
    "not one flood, not depth"
)
#: Names taken from run artefacts must be plain file names, never paths.
SAFE_TILE = re.compile(r"^[A-Za-z0-9._-]+\.tif$")
SAFE_AOI = re.compile(r"^[a-z0-9-]+$")


def build_ever_water(
    run: RunRef, settings: Settings, *, min_share: float, limit: int
) -> dict[str, Any]:
    """The ever-water summary and 1 km cells, or nulls with the reason."""
    warnings: list[ApiWarning] = []
    base: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": [],
        "run_id": run.run_id,
        "available": False,
        "verified": False,
        "is_observation": True,
        "measures": MEASURES,
        "source_id": gsw.EXTENT_SOURCE_ID,
        "tile_name": None,
        "content_sha256": None,
        "aoi_id": None,
        "aoi_km2": None,
        "ever_water_km2": None,
        "no_data_km2": None,
        "ever_water_share_of_observed": None,
        "min_share": min_share,
        "matched_cells": 0,
        "returned": 0,
        "truncated": False,
        "reason": None,
        "warnings": warnings,
    }

    record, reason = _recorded_extent(run)
    if record is None:
        return _unavailable(base, reason, "max_extent_unavailable")
    tile_name, sha, aoi_id = record
    base.update(tile_name=tile_name, content_sha256=sha, aoi_id=aoi_id)

    tile = settings.data_dir / "staged" / "gsw" / tile_name
    aoi_path = settings.data_dir / "curated" / "aoi" / f"{aoi_id}.geojson"
    if not tile.is_file():
        return _unavailable(base, f"the recorded extent tile {tile_name} is not staged", "source_not_staged")
    if not aoi_path.is_file():
        return _unavailable(base, f"the run's area {aoi_id} has no boundary file", "aoi_unavailable")
    stat = tile.stat()
    if _sha256(str(tile), stat.st_size, stat.st_mtime_ns) != sha:
        return _unavailable(
            base,
            f"the staged {tile_name} does not match the SHA-256 this run recorded",
            "source_mismatch",
        )
    try:
        summary = _measure(str(tile), sha, str(aoi_path), aoi_path.stat().st_mtime_ns)
    except (OSError, ValueError) as exc:
        return _unavailable(base, f"the extent tile could not be measured: {exc}", "unreadable_artefact")

    cells = [cell for cell in summary["cells"] if cell["water_share"] >= min_share]
    matched = len(cells)
    truncated = matched > limit
    if truncated:
        cells = sorted(cells, key=lambda cell: cell["water_km2"], reverse=True)[:limit]
        warnings.append(make_warning(
            "truncated", f"{matched - limit} cells were dropped by the limit of {limit}, keeping the wettest",
        ))
    base.update(
        available=True,
        verified=True,
        aoi_km2=summary["aoi_km2"],
        ever_water_km2=summary["ever_water_km2"],
        no_data_km2=summary["no_data_km2"],
        ever_water_share_of_observed=summary["ever_water_share_of_observed"],
        matched_cells=matched,
        returned=len(cells),
        truncated=truncated,
        features=[_cell_feature(cell) for cell in cells],
    )
    return base


def _recorded_extent(run: RunRef) -> tuple[tuple[str, str, str] | None, str]:
    """(tile name, SHA-256, AOI id) the run recorded, or None and why."""
    path = artefact_path(run, "observed_water.json")
    if not path.is_file():
        return None, "this run has no observed_water.json, so it records no extent tile"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"observed_water.json could not be read: {exc}"
    extent = payload.get("max_extent") if isinstance(payload, dict) else None
    if not isinstance(extent, dict) or extent.get("status") != "ok":
        return None, "this run records no usable JRC Maximum Water Extent tile"
    tile_name, sha = extent.get("tile_name"), extent.get("content_sha256")
    aoi_id = payload.get("aoi_id") or run.aoi_id
    if not (isinstance(tile_name, str) and SAFE_TILE.match(tile_name)):
        return None, "the recorded extent tile name is not a plain file name"
    if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
        return None, "the recorded extent tile has no SHA-256"
    if not (isinstance(aoi_id, str) and SAFE_AOI.match(aoi_id)):
        return None, "the run's area id is missing or not a plain id"
    return (tile_name, sha, aoi_id), ""


def _unavailable(base: dict[str, Any], reason: str, code: str) -> dict[str, Any]:
    base["reason"] = reason
    base["warnings"].append(make_warning(code, reason, "observed_water.json"))
    return base


@lru_cache(maxsize=8)
def _sha256(path: str, size: int, mtime_ns: int) -> str:
    """Hash once per file version; size and mtime key the cache."""
    return sha256_file(Path(path))


@lru_cache(maxsize=4)
def _measure(tile: str, sha: str, aoi_path: str, aoi_mtime_ns: int) -> dict[str, Any]:
    """Measure once per verified tile and boundary version."""
    import geopandas as gpd

    aoi = gpd.read_file(aoi_path)
    return gsw.measure_extent(Path(tile), aoi.to_crs("EPSG:4326").geometry.union_all())


def _cell_feature(cell: dict[str, Any]) -> dict[str, Any]:
    return feature(
        {"type": "Point", "coordinates": [cell["lon"], cell["lat"]]},
        {
            "cell_id": cell["cell_id"],
            "year": None,
            "water_share": cell["water_share"],
            "water_km2": cell["water_km2"],
            "source_role": "observed",
            "measures": "ever_water_1984_2021",
        },
    )
