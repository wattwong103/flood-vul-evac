"""Building height, exposure and the refuge distinction.

The plan is explicit on the failure mode this module exists to prevent:

    "Never silently convert building height into 'safe shelter'."

So height and refuge eligibility are separate fields, separate layers, and
separate confidences. A tall building is an exposure and capacity *input*; a
refuge is a reviewed record with an operator, hours and verified capacity.

Height provenance is ranked: measured/tagged OSM height first, then
``building:levels`` converted at a stated metres-per-level assumption, then
nothing. Where no source exists the height is null and the record is marked
``unknown`` rather than filled with a default.
"""

from __future__ import annotations

import re
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

METRES_PER_LEVEL = 3.0
METRES_PER_LEVEL_SOURCE = (
    "Scenario assumption: 3.0 m per storey. Not a Bangkok building-code survey. "
    "Sensitivity to 2.8-3.5 m should be reported before any capacity claim."
)

HEIGHT_SOURCE_RANK = {
    "osm_height": 1,
    "osm_building_levels": 2,
    "unknown": 3,
}

# Residential-capable tags, used for dasymetric allocation only.
RESIDENTIAL_TAGS = {
    "house",
    "residential",
    "apartments",
    "dormitory",
    "detached",
    "semidetached_house",
    "terrace",
    "bungalow",
    "hut",
    "cabin",
    "farm",
}

DESTINATION_TAGS = {
    "work": {"office", "industrial", "retail", "commercial", "warehouse"},
    "education": {"school", "university", "college", "kindergarten"},
    "health_care": {"hospital", "clinic", "healthcare"},
}


def _parse_height(value: Any) -> float | None:
    """Parse an OSM height value into metres.

    Handles the forms that actually appear in the extract: bare numbers, metric
    suffixes with or without a decimal point, and feet/foot marks.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"no", "none"}:
        return None
    feet = bool(re.match(r"^\d+(\.\d+)?\s*('|ft|feet|foot)$", text))
    number = re.match(r"^(\d+(?:\.\d+)?)", text)
    if not number:
        return None
    metres = float(number.group(1))
    if feet:
        return round(metres * 0.3048, 2)
    return round(metres, 2)


def _parse_levels(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"no", "none"}:
        return None
    number = re.match(r"^(\d+(?:\.\d+)?)", text)
    if not number:
        return None
    return float(number.group(1))


def build_building_table(
    buildings: gpd.GeoDataFrame,
    *,
    aoi_frame: gpd.GeoDataFrame,
    analysis_crs: str,
    building_version: str,
) -> gpd.GeoDataFrame:
    """Normalise footprints into the building table with ranked height evidence."""
    frame = buildings.copy()
    if frame.empty:
        return frame
    if "building" not in frame.columns:
        frame["building"] = "yes"

    aoi_projected = aoi_frame.to_crs(analysis_crs)
    clip = aoi_projected.geometry.union_all()
    frame = frame.to_crs(analysis_crs)
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty]
    frame = frame[frame.geometry.intersects(clip)].copy()
    frame["geometry"] = frame.geometry.intersection(clip)
    frame = frame[~frame.geometry.is_empty].copy()
    frame = frame[frame.geom_type.isin(["Polygon", "MultiPolygon"])]
    frame = frame.reset_index(drop=True)

    frame["building_id"] = [
        f"b_{int(osm_id)}_{osm_type}" for osm_id, osm_type in zip(frame["osm_id"], frame["osm_type"])
    ]
    frame["footprint_m2"] = frame.geometry.area
    frame["footprint_source"] = "openstreetmap"

    tagged_height = frame.get("height", pd.Series([None] * len(frame))).apply(_parse_height)
    levels = frame.get("building:levels", pd.Series([None] * len(frame))).apply(_parse_levels)

    frame["height_m"] = tagged_height
    frame["height_source"] = np.where(tagged_height.notna(), "osm_height", "unknown")
    fill = levels.notna() & tagged_height.isna()
    frame.loc[fill, "height_m"] = (levels[fill] * METRES_PER_LEVEL).round(2)
    frame.loc[fill, "height_source"] = "osm_building_levels"

    frame["height_levels"] = levels
    frame["height_confidence"] = np.where(
        frame["height_source"] == "osm_height",
        "tagged",
        np.where(frame["height_source"] == "osm_building_levels", "derived_from_levels", "unknown"),
    )
    frame["height_metres_per_level"] = np.where(
        frame["height_source"] == "osm_building_levels", METRES_PER_LEVEL, np.nan
    )

    frame["building_version"] = building_version
    frame["is_residential_candidate"] = frame["building"].astype(str).isin(RESIDENTIAL_TAGS)
    frame["use_class"] = frame["building"].astype(str)
    frame["centre_x"] = frame.geometry.centroid.x
    frame["centre_y"] = frame.geometry.centroid.y

    # A refuge claim is a separate, explicitly unverified layer.
    frame["osm_shelter_tag"] = frame.get("amenity", pd.Series([None] * len(frame))).astype(str).eq(
        "shelter"
    )
    frame["refuge_status"] = np.where(
        frame["osm_shelter_tag"], "osm_tagged_candidate_unverified", "not_a_refuge"
    )
    frame["refuge_verified"] = False
    frame["refuge_capacity"] = np.nan
    frame["refuge_operator"] = None
    frame["refuge_accessible"] = False
    frame["refuge_reviewed_at"] = None

    keep = [
        "building_id",
        "osm_id",
        "osm_type",
        "footprint_m2",
        "footprint_source",
        "use_class",
        "is_residential_candidate",
        "height_m",
        "height_levels",
        "height_source",
        "height_confidence",
        "height_metres_per_level",
        "centre_x",
        "centre_y",
        "osm_shelter_tag",
        "refuge_status",
        "refuge_verified",
        "refuge_capacity",
        "refuge_operator",
        "refuge_accessible",
        "refuge_reviewed_at",
        "building_version",
        "geometry",
    ]
    for column in ("name", "amenity", "office", "shop", "building"):
        if column in buildings.columns:
            keep.append(column)
    return frame[[column for column in dict.fromkeys(keep) if column in frame.columns]]


def height_coverage(buildings: gpd.GeoDataFrame) -> dict[str, Any]:
    """Report how much of the AOI has any height evidence at all."""
    total = len(buildings)
    if total == 0:
        return {"buildings": 0}
    tagged = int((buildings["height_source"] == "osm_height").sum())
    from_levels = int((buildings["height_source"] == "osm_building_levels").sum())
    unknown = total - tagged - from_levels
    return {
        "buildings": total,
        "tagged_height": tagged,
        "derived_from_levels": from_levels,
        "unknown_height": unknown,
        "coverage_share": round((tagged + from_levels) / total, 4),
        "metres_per_level": METRES_PER_LEVEL,
        "metres_per_level_source": METRES_PER_LEVEL_SOURCE,
    }


def candidate_destinations(buildings: gpd.GeoDataFrame) -> pd.DataFrame:
    """Aggregate building tags into destination attractor classes.

    These are *scenario* attractors derived from OSM tags. A building tagged
    ``office=yes`` is evidence of a possible workplace, not a verified
    destination, and the class carries that status.
    """
    records: list[dict[str, Any]] = []
    for purpose, tags in DESTINATION_TAGS.items():
        mask = buildings["use_class"].astype(str).isin(tags)
        selected = buildings[mask]
        if selected.empty:
            records.append(
                {
                    "purpose": purpose,
                    "candidate_count": 0,
                    "status": "no_tagged_candidates",
                    "footprint_m2": 0.0,
                }
            )
            continue
        records.append(
            {
                "purpose": purpose,
                "candidate_count": int(len(selected)),
                "status": "scenario_from_osm_tags",
                "footprint_m2": round(float(selected["footprint_m2"].sum()), 2),
            }
        )
    return pd.DataFrame(records)
