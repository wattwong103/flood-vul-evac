"""MitrEarth provincial geohazard layers for Bangkok.

Licence status: approved by project decision on 2026-09-30. Chulalongkorn
describes these maps as free for teaching **and disaster response**; this is
non-commercial flood-exposure research, which is the named use. The full terms
stay recorded in the registry so the decision remains auditable.

What is ingested, and what is not:

* **Ingested** - the mapped flood extent by year, the drainage network and
  basins, the overflow paths, flood-susceptible villages, and the
  hydrography. The drainage network matters because the plan identifies
  drainage as a first-order determinant of Bangkok flooding and the OSM
  canal network alone does not describe the engineered system.
* **Excluded** - the bundled DEM and every contour set derived from it. That is
  a fitness decision, not a licence one: the DEM reads +13.8 m at Khlong San
  where ground is 1-2 m. Importing it would put a wrong elevation surface into
  a disaster-response tool, which is worse than having none.

One caution worth carrying forward: the flood layer's per-feature ``year``
attribute is the year of the mapped event, and its ``LAYER`` field is
``Unknown Area Type`` for every feature in this extract, so the layer supports
"extent in year X" but not "which hazard type".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from ..util import CURATED_DIR, ensure_dir, sha256_file, utc_now_iso, write_json

SOURCE_ID = "mitrearth-provincial-geohazard-bangkok"
RAW_ROOT = Path("data/raw")

#: filename -> logical layer name. Only approved, non-DEM layers appear here.
LAYER_FILES: dict[str, str] = {
    "flood_extent_gistda": "7 Geological Hazard/2 Flood GISTDA 0519 BANGKOK.shp",
    "flood_susceptible_village": "6 Valley Ridge and Basin/2_Flood_Susceptible_Village_BANGKOK_-_mitrearth.shp",
    "drainage_basin": "6 Valley Ridge and Basin/2 Drainage Basin.shp",
    "drainage_system": "6 Valley Ridge and Basin/2 Drainage System BANGKOK - mitrearth.shp",
    "overflow_flood": "6 Valley Ridge and Basin/2_Overflow_Flood_BANGKOK_-_mitrearth.shp",
    "major_river": "5 Surface and Ground Water/2 Major River.shp",
    "minor_stream": "5 Surface and Ground Water/2 minor stream.shp",
    "water_body": "5 Surface and Ground Water/2 water body.shp",
}

#: Layers that are excluded, with the reason recorded alongside the exclusion.
EXCLUDED = {
    "dem": "Reads +13.8 m at Khlong San where ground is 1-2 m; unusable for depth.",
    "contours": "Derived from the same rejected DEM, so they encode its noise.",
    "transportation": "OSM from the regional extract is more detailed and better attributed.",
}

#: A repaired polygon is trusted only if ``make_valid`` kept its area within
#: this fraction of the raw ring area. The self-intersections in this extract
#: are rings that pinch or touch themselves, and their repair keeps the area to
#: within 0.03%. A bow-tie whose lobes cancel in the raw area does not, so a
#: larger change means the repair altered the mapped extent.
REPAIR_AREA_TOLERANCE = 0.01


@dataclass
class IngestResult:
    layers: dict[str, Any]
    flood_extent_by_year: dict[str, Any]
    excluded: dict[str, str]
    written_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": SOURCE_ID,
            "layers": self.layers,
            "flood_extent_by_year": self.flood_extent_by_year,
            "excluded": self.excluded,
            "written_at": self.written_at,
        }


def _read(path: Path) -> gpd.GeoDataFrame:
    frame = gpd.read_file(path)
    if frame.crs is None:
        # These extracts ship without a declared CRS in some shapefiles. The
        # coordinates are unmistakably WGS84 degrees, but assigning rather than
        # guessing is deliberate: it makes the assumption explicit in the code.
        frame = frame.set_crs("EPSG:4326", allow_override=True)
    return frame


def ingest(
    *,
    aoi_frame: gpd.GeoDataFrame,
    analysis_crs: str,
    raw_root: str | Path = RAW_ROOT,
    out_dir: str | Path | None = None,
) -> IngestResult:
    """Ingest the approved MitrEarth layers, clipped to the AOI."""
    raw_root = Path(raw_root)
    target = ensure_dir(Path(out_dir or CURATED_DIR / "city" / "mitrearth"))
    clip = aoi_frame.to_crs(analysis_crs).geometry.union_all()

    layers: dict[str, Any] = {}
    frames: dict[str, gpd.GeoDataFrame] = {}

    for name, relative in LAYER_FILES.items():
        path = raw_root / relative
        if not path.is_file():
            layers[name] = {"status": "missing", "source_file": relative}
            continue
        frame = _read(path).to_crs(analysis_crs)

        # These shapefiles contain invalid rings. One invalid polygon aborts the
        # whole spatial test, so they are repaired before clipping and any that
        # cannot be repaired are dropped and counted rather than retained. The
        # outcome is kept per year, so a year that lost a feature, or whose
        # repair changed a feature's area, is marked unreliable.
        rows_total = len(frame)
        frame, outcome = _repair(frame)
        invalid_geometry = _invalid_geometry_by_year(frame, outcome)
        frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty & frame.geometry.is_valid].copy()

        inside = frame.intersects(clip)
        clipped = frame[inside].copy()
        clipped = clipped[~clipped.geometry.is_empty]
        if not clipped.empty and clipped.geom_type.isin(["Polygon", "MultiPolygon"]).any():
            polygonal = clipped.geom_type.isin(["Polygon", "MultiPolygon"])
            clipped.loc[polygonal, "geometry"] = clipped.loc[polygonal].geometry.intersection(clip)
            clipped = clipped[~clipped.geometry.is_empty]
        clipped = clipped.reset_index(drop=True)

        out = clipped.copy()
        out["geometry_wkt"] = out.geometry.to_wkt()
        out["mitrearth_layer"] = name
        out["source_id"] = SOURCE_ID
        columns = [c for c in out.columns if c not in ("geometry", "other_tags")]
        out[columns].to_parquet(target / f"{name}.parquet", index=False)
        frames[name] = clipped

        layers[name] = {
            "invalid_geometry_by_year": invalid_geometry,
            "status": "ok",
            "source_file": relative,
            "rows_total": int(rows_total),
            "repaired_geometries": int((outcome != "dropped").sum()),
            "repaired_area_changed": int((outcome == "repaired_area_changed").sum()),
            "dropped_unrepairable": int((outcome == "dropped").sum()),
            "rows_in_aoi": int(len(clipped)),
            "area_km2": round(float(clipped.area.sum() / 1e6), 3)
            if not clipped.empty and clipped.geom_type.isin(["Polygon", "MultiPolygon"]).any()
            else None,
            "length_km": round(float(clipped.length.sum() / 1000.0), 3)
            if not clipped.empty and clipped.geom_type.isin(["LineString", "MultiLineString"]).any()
            else None,
            "sha256": sha256_file(target / f"{name}.parquet"),
        }

    flood_extent = _flood_extent_by_year(
        frames.get("flood_extent_gistda"),
        target,
        layers.get("flood_extent_gistda", {}).get("invalid_geometry_by_year", {}),
    )

    result = IngestResult(
        layers=layers, flood_extent_by_year=flood_extent, excluded=EXCLUDED, written_at=utc_now_iso()
    )
    write_json(target / "provenance.json", result.as_dict())
    return result


def _flood_extent_by_year(
    frame: gpd.GeoDataFrame | None,
    target: Path,
    invalid_geometry: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Dissolve the flood layer by year and record the unioned extent.

    The raw polygons overlap heavily, so summing their areas would triple-count
    the flood. Only the union is a meaningful extent.
    """
    if frame is None or "year" not in frame.columns:
        return {"status": "unavailable", "years": []}
    invalid_geometry = invalid_geometry or {}

    records: list[dict[str, Any]] = []
    for year in sorted(frame["year"].dropna().unique()):
        subset = frame[frame["year"] == year]
        if subset.empty:
            continue
        dissolved = unary_union(subset.geometry.values)
        records.append(
            {
                "year": int(year),
                "polygons": int(len(subset)),
                "invalid_geometry": invalid_geometry.get(str(int(year)), {}),
                "union_km2": round(float(dissolved.area / 1e6), 3),
                "raw_sum_km2": round(float(subset.area.sum() / 1e6), 3),
                "overlap_factor": round(
                    float(subset.area.sum() / dissolved.area), 3
                )
                if dissolved.area
                else None,
            }
        )

    # A year whose every feature was dropped has no rows left to dissolve, but
    # it still lost its extent. Record it, with the extent unknown rather than
    # zero, so it is reported as unreliable instead of missing from the summary.
    present = {entry["year"] for entry in records}
    for key, invalid in invalid_geometry.items():
        if int(key) not in present and invalid.get("dropped", 0):
            records.append(
                {
                    "year": int(key),
                    "polygons": 0,
                    "invalid_geometry": invalid,
                    "union_km2": None,
                    "raw_sum_km2": None,
                    "overlap_factor": None,
                }
            )
    if not records:
        return {"status": "unavailable", "years": []}
    records.sort(key=lambda entry: entry["year"])

    # A year is unreliable if it lost a feature to unrepairable geometry, or if
    # a repair changed a feature's area beyond REPAIR_AREA_TOLERANCE. No area is
    # invented for lost features. A repair that keeps the area only fixed how
    # the ring was drawn, so it leaves the year reliable.
    for entry in records:
        invalid = entry["invalid_geometry"]
        entry["reliable"] = (
            invalid.get("dropped", 0) == 0 and invalid.get("repaired_area_changed", 0) == 0
        )

    # A year of 0 means "unspecified" in this extract; keep it out of the
    # per-year comparison but record it so the gap is visible.
    unspecified = next((r for r in records if r["year"] == 0), None)
    dated = [r for r in records if r["year"] != 0]

    measured = [r for r in dated if r["union_km2"] is not None]
    largest = max(measured, key=lambda entry: entry["union_km2"]) if measured else None
    for entry in dated:
        entry["is_largest_mapped_event"] = largest is not None and entry["year"] == largest["year"]

    return {
        "status": "ok",
        "measures": "mapped flood extent, a mapped hazard layer rather than a satellite observation",
        "years": dated,
        "unspecified_year": unspecified,
        "unreliable_years": [r["year"] for r in dated if not r["reliable"]],
        "note": (
            "Polygons overlap heavily, so only the dissolved union is an extent. "
            "The LAYER field is 'Unknown Area Type' for every feature in this "
            "extract, so hazard type is not recoverable. This layer is a mapping, "
            "not an observation, and is labelled source_role='mapped'. Self-intersecting "
            "rings are repaired with make_valid. A year that lost a feature to "
            "unrepairable geometry, or whose repair changed a feature's area by more "
            f"than {REPAIR_AREA_TOLERANCE:.0%}, is reported as unreliable."
        ),
    }


def _repair(frame: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, pd.Series]:
    """Repair invalid rings in a copy of ``frame``.

    Returns the repaired frame and, for each feature that was invalid, its
    outcome: ``repaired``, ``repaired_area_changed`` or ``dropped``. Geometry
    that cannot be repaired into a line or polygon is left invalid in the
    returned frame, so the caller's validity filter drops exactly those.
    """
    import numpy as np
    import shapely

    invalid = ~frame.geometry.is_valid
    if not invalid.any():
        return frame, pd.Series([], dtype=object)
    original = np.asarray(frame.geometry.values[invalid])
    fixed = shapely.make_valid(original)
    usable = np.isin(shapely.get_type_id(fixed), (1, 2, 3, 6))  # line/ring/polygon/multipolygon
    repaired_frame = frame.copy()
    repaired_frame.loc[invalid, "geometry"] = np.where(usable, fixed, original)

    # Lines have no area to keep, so only polygons are checked.
    polygonal = np.isin(shapely.get_type_id(original), (3, 6))
    raw_area = shapely.area(original)
    area_kept = (raw_area > 0) & (
        np.abs(shapely.area(fixed) - raw_area) <= REPAIR_AREA_TOLERANCE * raw_area
    )
    still_invalid = ~repaired_frame.geometry.is_valid[invalid].to_numpy()
    outcome = np.where(
        still_invalid,
        "dropped",
        np.where(~polygonal | area_kept, "repaired", "repaired_area_changed"),
    )
    return repaired_frame, pd.Series(outcome, index=frame.index[invalid], dtype=object)


def _invalid_geometry_by_year(
    frame: gpd.GeoDataFrame, outcome: pd.Series
) -> dict[str, dict[str, int]]:
    """Count the features that were invalid, by year and repair outcome.

    No area is derived for a dropped feature: a ring that cannot be repaired
    reports an arbitrary area, and its bounding box can be nonsense too.
    """
    if outcome.empty or "year" not in frame.columns:
        return {}
    out: dict[str, dict[str, int]] = {}
    for year, block in outcome.groupby(frame.loc[outcome.index, "year"]):
        counts = block.value_counts()
        out[str(int(year))] = {
            "invalid_features": int(len(block)),
            "repaired": int(counts.get("repaired", 0)),
            "repaired_area_changed": int(counts.get("repaired_area_changed", 0)),
            "dropped": int(counts.get("dropped", 0)),
        }
    return out
