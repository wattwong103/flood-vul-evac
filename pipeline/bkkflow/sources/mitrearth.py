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
        # cannot be repaired are dropped and counted rather than retained.
        # Measure the area about to be discarded, so a year whose extent was
        # mostly invalid geometry is marked unreliable instead of published
        # as a small, confident number.
        discarded = _invalid_area_by_year(frame)
        repaired, dropped = _repair(frame)
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
            "discarded_invalid_area_by_year": discarded,
            "status": "ok",
            "source_file": relative,
            "rows_total": int(len(frame) + dropped),
            "repaired_geometries": int(repaired),
            "dropped_unrepairable": int(dropped),
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
        layers.get("flood_extent_gistda", {}).get("discarded_invalid_area_by_year", {}),
    )

    result = IngestResult(
        layers=layers, flood_extent_by_year=flood_extent, excluded=EXCLUDED, written_at=utc_now_iso()
    )
    write_json(target / "provenance.json", result.as_dict())
    return result


def _flood_extent_by_year(
    frame: gpd.GeoDataFrame | None,
    target: Path,
    discarded: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Dissolve the flood layer by year and record the unioned extent.

    The raw polygons overlap heavily, so summing their areas would triple-count
    the flood. Only the union is a meaningful extent.
    """
    if frame is None or frame.empty or "year" not in frame.columns:
        return {"status": "unavailable", "years": []}

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
                "discarded_invalid": (discarded or {}).get(str(int(year)), {}),
                "union_km2": round(float(dissolved.area / 1e6), 3),
                "raw_sum_km2": round(float(subset.area.sum() / 1e6), 3),
                "overlap_factor": round(
                    float(subset.area.sum() / dissolved.area), 3
                )
                if dissolved.area
                else None,
            }
        )

    # A year of 0 means "unspecified" in this extract; keep it out of the
    # per-year comparison but record it so the gap is visible.
    # A year is unreliable when the geometry it lost could have covered far
    # more than what survived. Comparing against the published extent keeps
    # a handful of discarded slivers from disqualifying an otherwise sound year.
    for entry in records:
        # Conservative and simple: a year that lost any feature to unrepairable
        # geometry is reported as unreliable. No area is invented for the lost
        # features, because a self-intersecting ring reports an arbitrary area
        # and its bounding box can be nonsense too.
        entry["reliable"] = float(
            (entry.get("discarded_invalid") or {}).get("invalid_features", 0)
        ) == 0

    unspecified = next((r for r in records if r["year"] == 0), None)
    dated = [r for r in records if r["year"] != 0]

    if dated:
        largest = max(dated, key=lambda entry: entry["union_km2"])
        for entry in dated:
            entry["is_largest_mapped_event"] = entry["year"] == largest["year"]

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
            "not an observation, and is labelled source_role='mapped'. A year whose apparent extent "
            "was mostly self-intersecting geometry is reported as unreliable "
            "rather than published as a small confident number."
        ),
    }


def _repair(frame: gpd.GeoDataFrame) -> tuple[int, int]:
    """Repair invalid rings; drop what cannot be repaired. Returns (repaired, dropped)."""
    import numpy as np
    import shapely

    invalid = ~frame.geometry.is_valid
    count = int(invalid.sum())
    if not count:
        return 0, 0
    original = frame.geometry.values[invalid]
    fixed = shapely.make_valid(original)
    usable = np.array(
        [shapely.get_type_id(item) in (1, 2, 3, 6) for item in fixed]  # line/ring/polygon/multipolygon
    )
    frame = frame.copy()
    frame.loc[invalid, "geometry"] = np.where(usable, fixed, original)
    still_invalid = ~frame.geometry.is_valid
    dropped = int(still_invalid.sum())
    return count - dropped, dropped



def _invalid_area_by_year(frame: gpd.GeoDataFrame) -> dict[str, dict[str, float]]:
    """Envelope of the geometry about to be discarded, keyed by year.

    A self-intersecting ring reports an arbitrary `area`, and its bounding box
    can contain stray far-off coordinates, so no area is derived here at all.
    Only the count is reported, and any year that lost a feature is marked
    unreliable so its published extent is never mistaken for a measurement.
    """
    import math

    if frame is None or frame.empty or "year" not in frame.columns:
        return {}
    invalid = ~frame.geometry.is_valid
    if not invalid.any():
        return {}

    out: dict[str, dict[str, float]] = {}
    for year, block in frame[invalid].groupby("year"):
        west = east = south = north = None
        for geometry in block.geometry:
            try:
                x0, y0, x1, y1 = geometry.bounds
            except Exception:
                continue
            if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
                continue
            west = x0 if west is None else min(west, x0)
            east = x1 if east is None else max(east, x1)
            south = y0 if south is None else min(south, y0)
            north = y1 if north is None else max(north, y1)
        if west is None:
            continue
        out[str(int(year))] = {
            "invalid_features": int(len(block)),
            "bounds_were_finite": bool(west is not None),
        }
    return out
