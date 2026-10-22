"""The 1984-2021 JRC Maximum Water Extent for a run's area (BKK-055c).

No run stores the ever-water area or cells, but a city run records the exact
extent tile it used (``observed_water.json`` -> ``max_extent``) and its own
AOI pixel count for every year. This module serves the extent only when:

- the staged tile's bytes hash to the recorded SHA-256 (the bytes hashed are
  the bytes measured, read once per request);
- the area id agrees with the run's manifest; and
- the boundary yields the same AOI pixel count the run recorded.

Anything else is reported with a reason, never as zero water and never as a
500. Reasons are fixed text; exception details go to the log, not the client.
Nothing is written. The extent marks everywhere ever detected as water in
1984-2021: not one flood, and no depth.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from typing import Any

from api.models import ApiWarning
from api.runs import RunRef
from api.settings import Settings
from api.tables import artefact_path, feature, make_warning
from pipeline.bkkflow.sources import gsw

LOGGER = logging.getLogger("bkkflow.api.ever_water")

MEASURES = (
    "everywhere ever detected as water in 1984-2021 (JRC Maximum Water Extent); "
    "not one flood, not depth"
)
#: Names taken from run artefacts must be plain file names, never paths.
SAFE_TILE = re.compile(r"[A-Za-z0-9._-]+\.tif")
SAFE_AOI = re.compile(r"[a-z0-9-]+")

#: Measurements by (tile SHA-256, boundary SHA-256). One lock serialises cold
#: measurements, so concurrent first requests compute once.
_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_SIZE = 4


def build_ever_water(
    run: RunRef, settings: Settings, *, min_share: float, limit: int
) -> dict[str, Any]:
    """The ever-water summary and 1 km cells, or nulls with the reason."""
    base = _empty_response(run, min_share)
    record, reason = _recorded_extent(run)
    if record is None:
        return _unavailable(base, reason, "max_extent_unavailable")
    tile_name, sha, aoi_id, recorded_pixels = record
    base.update(tile_name=tile_name, content_sha256=sha, aoi_id=aoi_id)

    tile = settings.data_dir / "staged" / "gsw" / tile_name
    aoi_path = settings.data_dir / "curated" / "aoi" / f"{aoi_id}.geojson"
    if not tile.is_file():
        return _unavailable(base, f"the recorded extent tile {tile_name} is not staged", "source_not_staged")
    if not aoi_path.is_file():
        return _unavailable(base, f"the run's area {aoi_id} has no boundary file", "aoi_unavailable")
    try:
        tile_bytes, aoi_bytes = tile.read_bytes(), aoi_path.read_bytes()
    except OSError:
        LOGGER.warning("ever-water: could not read inputs for run %s", run.run_id, exc_info=True)
        return _unavailable(base, "the extent tile or the area boundary could not be read", "unreadable_artefact")
    if hashlib.sha256(tile_bytes).hexdigest() != sha:
        return _unavailable(
            base, f"the staged {tile_name} does not match the SHA-256 this run recorded", "source_mismatch"
        )
    try:
        summary = _measure(sha, tile_bytes, aoi_bytes)
    except Exception:  # noqa: BLE001 - any reader or geometry error is reported, never a 500
        LOGGER.warning("ever-water: measurement failed for run %s", run.run_id, exc_info=True)
        return _unavailable(
            base, "the extent tile or the area boundary could not be measured", "unreadable_artefact"
        )
    if summary["aoi_pixels"] not in recorded_pixels:
        return _unavailable(
            base,
            f"the {aoi_id} boundary covers {summary['aoi_pixels']} pixels, not the "
            f"{sorted(recorded_pixels)} this run recorded",
            "aoi_mismatch",
        )
    return _available(base, summary, min_share=min_share, limit=limit)


def _empty_response(run: RunRef, min_share: float) -> dict[str, Any]:
    return {
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
        "warnings": [],
    }


def _available(
    base: dict[str, Any], summary: dict[str, Any], *, min_share: float, limit: int
) -> dict[str, Any]:
    warnings: list[ApiWarning] = base["warnings"]
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


def _recorded_extent(
    run: RunRef,
) -> tuple[tuple[str, str, str, frozenset[int]] | None, str]:
    """(tile name, SHA-256, area id, recorded AOI pixel counts), or None and why."""
    path = artefact_path(run, "observed_water.json")
    if not path.is_file():
        return None, "this run has no observed_water.json, so it records no extent tile"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "observed_water.json could not be read"
    if not isinstance(payload, dict):
        return None, "observed_water.json is not a record"
    extent = payload.get("max_extent")
    if not isinstance(extent, dict) or extent.get("status") != "ok":
        return None, "this run records no usable JRC Maximum Water Extent tile"
    tile_name, sha = extent.get("tile_name"), extent.get("content_sha256")
    if not (isinstance(tile_name, str) and SAFE_TILE.fullmatch(tile_name)):
        return None, "the recorded extent tile name is not a plain file name"
    if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
        return None, "the recorded extent tile has no SHA-256"
    aoi_id = run.aoi_id
    if not (isinstance(aoi_id, str) and SAFE_AOI.fullmatch(aoi_id)):
        return None, "the run's manifest has no plain area id"
    recorded_area = payload.get("aoi_id")
    if recorded_area is not None and recorded_area != aoi_id:
        return None, "the observed-water record's area disagrees with the run's manifest"
    years = payload.get("years") if isinstance(payload.get("years"), list) else []
    pixels = frozenset(
        entry["aoi_pixels"] for entry in years
        if isinstance(entry, dict) and isinstance(entry.get("aoi_pixels"), int)
    )
    if not pixels:
        return None, "the run records no AOI pixel count, so the boundary cannot be checked"
    return (tile_name, sha, aoi_id, pixels), ""


def _unavailable(base: dict[str, Any], reason: str, code: str) -> dict[str, Any]:
    base["reason"] = reason
    base["warnings"].append(make_warning(code, reason, "observed_water.json"))
    return base


def _measure(sha: str, tile_bytes: bytes, aoi_bytes: bytes) -> dict[str, Any]:
    """Measure once per (tile, boundary) content; the bytes are the ones hashed."""
    key = (sha, hashlib.sha256(aoi_bytes).hexdigest())
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        summary = _measure_bytes(tile_bytes, aoi_bytes)
        if len(_CACHE) >= _CACHE_SIZE:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = summary
        return summary


def _measure_bytes(tile_bytes: bytes, aoi_bytes: bytes) -> dict[str, Any]:
    from rasterio.io import MemoryFile

    geometry = _boundary(aoi_bytes)
    with MemoryFile(tile_bytes) as memory, memory.open(driver="GTiff") as dataset:
        return gsw.measure_extent_dataset(dataset, geometry)


def _boundary(aoi_bytes: bytes) -> Any:
    """The boundary as one geometry, parsed as plain GeoJSON (CRS84) without OGR."""
    from shapely.geometry import shape
    from shapely.ops import unary_union

    payload = json.loads(aoi_bytes.decode("utf-8"))
    if payload.get("type") == "FeatureCollection":
        geometries = [item.get("geometry") for item in payload.get("features", [])]
    elif payload.get("type") == "Feature":
        geometries = [payload.get("geometry")]
    else:
        geometries = [payload]
    shapes = [shape(geometry) for geometry in geometries if geometry]
    if not shapes:
        raise ValueError("the boundary has no geometry")
    return unary_union(shapes)


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
