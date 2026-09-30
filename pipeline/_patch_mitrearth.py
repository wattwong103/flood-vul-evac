"""Insert reliability detection into the mitrearth ingest (line-based)."""

from pathlib import Path

P = Path("pipeline/bkkflow/sources/mitrearth.py")
lines = P.read_text(encoding="utf-8").split("\n")


def find(needle: str, start: int = 0) -> int:
    for index in range(start, len(lines)):
        if needle in lines[index]:
            return index
    raise SystemExit(f"not found: {needle}")


# 1. measure the area we are about to discard, before repair
i = find("repaired, dropped = _repair(frame)")
lines[i:i] = [
    "        # Measure the area about to be discarded, so a year whose extent was",
    "        # mostly invalid geometry is marked unreliable instead of published",
    "        # as a small, confident number.",
    '        discarded = _invalid_area_by_year(frame)',
]

# 2. record it on the layer
i = find('layers[name] = {', find("clipped = clipped.reset_index"))
lines[i + 1:i + 1] = ['            "discarded_invalid_area_by_year": discarded,']

# 3. pass it into the per-year summary
i = find("_flood_extent_by_year(frames.get")
lines[i : i + 1] = [
    '    flood_extent = _flood_extent_by_year(',
    '        frames.get("flood_extent_gistda"),',
    "        target,",
    '        layers.get("flood_extent_gistda", {}).get("discarded_invalid_area_by_year", {}),',
    "    )",
]

# 4. widen the signature
i = find("def _flood_extent_by_year(")
lines[i + 1 : i + 1] = ["    frame: gpd.GeoDataFrame | None,", "    target: Path,", "    discarded: dict[str, float] | None = None,"]
# remove the now-duplicated old first parameter line
if lines[i + 4].strip().startswith("frame: gpd.GeoDataFrame"):
    del lines[i + 4]

# 5. per-year reliability
i = find('"polygons": int(len(subset)),')
lines[i + 1 : i + 1] = [
    '                "discarded_invalid_km2": round(float((discarded or {}).get(str(int(year)), 0.0)), 3),',
    '                "reliable": float((discarded or {}).get(str(int(year)), 0.0)) < 1.0,',
]

# 6. list unreliable years in the summary
i = find('"unspecified_year": unspecified,')
lines[i + 1 : i + 1] = ['        "unreliable_years": [r["year"] for r in dated if not r["reliable"]],']
i = find('"not an observation, and is labelled source_role=')
lines[i] = (
    '            "not an observation, and is labelled source_role=\'mapped\'. A year whose '
    'apparent extent "\n            "was mostly self-intersecting geometry is reported as unreliable "\n'
    '            "rather than published as a small confident number."'
)

# 7. the helper
lines += [
    "",
    "",
    "def _invalid_area_by_year(frame: gpd.GeoDataFrame) -> dict[str, float]:",
    '    """Area of geometry about to be discarded as unrepairable, keyed by year.',
    "",
    "    A self-intersecting ring can report an arbitrary area. If a year loses a",
    "    large share of its apparent extent here, its published extent would be a",
    "    truncated artifact rather than a measurement.",
    '    """',
    '    if frame is None or frame.empty or "year" not in frame.columns:',
    "        return {}",
    "    invalid = ~frame.geometry.is_valid",
    "    if not invalid.any():",
    "        return {}",
    "    discarded: dict[str, float] = {}",
    '    for year, block in frame[invalid].groupby("year"):',
    "        import math",
    "",
    "        area = 0.0",
    "        for geometry in block.geometry:",
    "            centre = geometry.centroid",
    "            area += (",
    "                geometry.area",
    "                * 111_320.0",
    "                * 110_574.0",
    "                * abs(math.cos(math.radians(centre.y)))",
    "            )",
    '        discarded[str(int(year))] = round(area / 1e6, 3)',
    "    return discarded",
    "",
]

P.write_text("\n".join(lines), encoding="utf-8")
print("edits applied")
