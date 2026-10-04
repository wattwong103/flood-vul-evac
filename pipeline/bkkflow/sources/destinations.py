"""Destination candidates extracted from OSM point features.

The city run had no destinations at all, which meant the evacuation product
had nothing to aim at. OSM carries them, so this module recovers them from the
points layer of the same regional extract already staged for the network and
buildings.

The distinction this module is built to protect is the one the plan keeps
insisting on: **a mapped amenity is a lead, not a refuge.** Every record is
written with ``verified=False`` and ``status='osm_tagged_candidate_unverified'``,
and carries no capacity, no operator and no inspection date, because none of
those can be read from a tag. A reader who sees a school on the map must be
able to see, without ambiguity, that nobody has confirmed it can be used as a
destination in an emergency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..util import CURATED_DIR, ensure_dir, sha256_file, utc_now_iso
from .city_osm import DEFAULT_PBF, parse_other_tags

# Tag -> destination class. Grouping is by what the model would use the place
# for, not by the raw tag, so the class vocabulary stays small and stable.
DESTINATION_AMENITIES = {
    "shelter": "shelter_candidate",
    "hospital": "health_care",
    "clinic": "health_care",
    "doctors": "health_care",
    "school": "education",
    "college": "education",
    "university": "education",
    "kindergarten": "education",
    "fire_station": "emergency_service",
    "police": "emergency_service",
    "community_centre": "community_facility",
    "sports_centre": "community_facility",
    "place_of_worship": "community_facility",
    "marketplace": "commerce",
}

# Places that must never be treated as a refuge even if capacity is invented.
NEVER_REFUGE_CLASSES = {"shelter_candidate"}


def extract_destinations(
    *,
    pbf_path: str | Path = DEFAULT_PBF,
    out_dir: str | Path | None = None,
    aoi_frame=None,
) -> dict[str, Any]:
    """Extract destination candidates from the OSM points layer.

    GDAL does not expose ``amenity`` as a column on the points layer, so it is
    recovered from the ``other_tags`` fragment.
    """
    import pyogrio
    from ..aoi import load_aoi

    aoi = (load_aoi("bangkok-bma") if aoi_frame is None else aoi_frame).to_crs("EPSG:4326")
    source = Path(pbf_path)
    points = pyogrio.read_dataframe(
        source,
        layer="points",
        use_arrow=True,
        columns=["osm_id", "name", "other_tags"],
        bbox=tuple(aoi.total_bounds),
    )
    tags = points["other_tags"].map(parse_other_tags)
    amenity = tags.map(lambda item: item.get("amenity"))
    keep = amenity.isin(DESTINATION_AMENITIES)
    selected = points[keep].copy()

    selected["amenity"] = amenity[keep]
    selected["destination_class"] = selected["amenity"].map(DESTINATION_AMENITIES)
    selected = selected.to_crs(aoi.crs)
    selected = selected[selected.geometry.intersects(aoi.geometry.union_all())].copy()
    selected["verified"] = False
    selected["status"] = "osm_tagged_candidate_unverified"
    selected["operator"] = None
    selected["capacity"] = None
    selected["accessible"] = False
    selected["reviewed_at"] = None
    selected["destination_id"] = [
        f"d_{int(osm_id)}" for osm_id in selected["osm_id"].fillna(0).to_numpy()
    ]
    selected = selected.to_crs("OGC:CRS84")

    target = ensure_dir(Path(out_dir or CURATED_DIR / "city"))
    path = target / "destinations.parquet"
    out = selected.copy()
    out["lon"] = out.geometry.x
    out["lat"] = out.geometry.y
    out.drop(columns="geometry").to_parquet(path, index=False)

    counts = {
        str(key): int(value)
        for key, value in selected["destination_class"].value_counts().items()
    }
    return {
        "layer": "destinations",
        "path": str(path),
        "rows": int(len(selected)),
        "sha256": sha256_file(path),
        "by_class": counts,
        "verified_count": 0,
        "shelter_candidates": counts.get("shelter_candidate", 0),
        "extracted_at": utc_now_iso(),
        "note": (
            "All records are unverified OSM tag candidates. None is a refuge and none "
            "carries a capacity, an operator or an inspection date. A shelter tag is "
            "someone's mapping decision, not an operational guarantee."
        ),
    }
