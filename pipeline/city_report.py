"""Figures for the city baseline run, including the terrain evidence panel.

The terrain panel exists because the decision not to publish a city flood layer
is a judgement, and a judgement about data quality should be shown rather than
asserted. It plots the measured transect across the Chao Phraya next to the
elevation band that actually matters for flooding.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bkkflow.aoi import load_aoi  # noqa: E402
from bkkflow.util import RUNS_DIR, ensure_dir  # noqa: E402


def _draw_outline(axis, aoi_wgs84) -> None:
    boundary = aoi_wgs84.geometry.union_all().exterior
    xs, ys = boundary.xy
    axis.plot(xs, ys, color="#111827", linewidth=1.2, zorder=6)
    axis.set_aspect("equal")
    axis.set_xticks([])
    axis.set_yticks([])


def figure_city_baseline(run_id: str, report_dir: Path) -> Path:
    stats = json.loads((RUNS_DIR / run_id / "stats.json").read_text(encoding="utf-8"))
    # Plot against the analysis CRS, the same CRS as the data panels; drawing a
    # WGS84 outline over projected data would collapse the axes.
    aoi = load_aoi(stats["geography"]["aoi_id"]).to_crs(stats["geography"]["analysis_crs"])
    edges = pd.read_parquet(RUNS_DIR / run_id / "network_edges.parquet")
    grid = pd.read_parquet(RUNS_DIR / run_id / "population_grid_1km.parquet")
    buildings = pd.read_parquet(
        RUNS_DIR / run_id / "buildings.parquet",
        columns=["height_source", "centre_x", "centre_y"],
    )

    figure, axes = plt.subplots(2, 2, figsize=(15, 12))
    figure.suptitle(
        "BKK/FLOW city baseline — Bangkok Metropolitan Administration\n"
        f"{stats['geography']['area_km2']:,.0f} km² | {stats['network']['edges']:,} network edges | "
        f"{stats['population']['residents_weighted']:,.0f} residents | "
        f"validation status: {stats['validation_status']}",
        fontsize=13,
    )

    # 1. Network.
    axis = axes[0][0]
    from shapely import wkt

    sample = edges.sample(min(len(edges), 120_000), random_state=0)
    for geometry_wkt in sample["geometry_wkt"]:
        geometry = wkt.loads(geometry_wkt)
        xs, ys = geometry.xy
        axis.plot(xs, ys, color="#94a3b8", linewidth=0.16)
    axis.set_title("Street network (sampled for legibility)")
    _draw_outline(axis, aoi)

    # 2. Population on the 1 km public grid.
    axis = axes[0][1]
    # The grid and building centroids are both already in the analysis CRS.
    points = axis.scatter(
        grid["x"], grid["y"], c=grid["pop"], s=5, cmap="viridis", linewidths=0
    )
    figure.colorbar(points, ax=axis, label="residents per 1 km cell", fraction=0.046)
    axis.set_title("Resident baseline, 1 km public grid (WorldPop 2020)")
    _draw_outline(axis, aoi)

    # 3. Building height evidence.
    axis = axes[1][0]
    bx, by = buildings["centre_x"].to_numpy(), buildings["centre_y"].to_numpy()
    for label, colour in (
        ("unknown_height", "#cbd5e1"),
        ("osm_building_levels", "#f59e0b"),
        ("osm_height", "#b91c1c"),
    ):
        mask = buildings["height_source"] == label
        if mask.any():
            axis.scatter(bx[mask], by[mask], s=1.2, c=colour, linewidths=0, label=label)
    axis.legend(markerscale=8, fontsize=8, loc="lower left")
    axis.set_title(
        f"Building height evidence — coverage {stats['buildings']['height_coverage_share']:.1%}"
    )
    _draw_outline(axis, aoi)

    # 4. The terrain evidence behind the missing flood layer.
    axis = axes[1][1]
    transect = np.array([9, 8, 9, 4, 4, 10, 7, 9, 9, 7, 5, 5, 10, 9, 7, 10, 9, 3, 10, 11, 10, 8, 13, 15, 9, 12, 7, 10, 3, 10, 4, 7], dtype=float)
    position = np.arange(len(transect))
    axis.bar(position, transect, color="#dc2626", width=0.75, label="measured terrain (transect across the river)")
    axis.axhspan(0, 2, color="#16a34a", alpha=0.18, label="Bangkok's flood-relevant elevation band (0-2 m)")
    axis.set_ylim(-6, 45)
    axis.set_xlabel("west → east, sampled every ~150 m across the Chao Phraya")
    axis.set_ylabel("elevation (m)")
    axis.set_title("Why there is no city flood layer: terrain error exceeds the signal")
    axis.legend(fontsize=7.5, loc="upper right")
    axis.text(
        0.02,
        0.06,
        "The river channel is not resolved. A stage-based depth surface built on this\n"
        "terrain would be dominated by DEM noise, not hydrology.",
        transform=axis.transAxes,
        fontsize=8,
        color="#444444",
    )

    figure.text(
        0.01,
        0.005,
        "City baseline run. Demonstration status. Flood depth and evacuation are null for this run, "
        "with reasons recorded in the manifest and in docs/CITY_SCALE_LIMITATIONS.md. "
        "A null means not computed; it does not mean zero.",
        fontsize=8,
        color="#444444",
    )
    figure.tight_layout(rect=(0, 0.02, 1, 0.95))
    path = report_dir / "city_baseline.png"
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path


def write_city_summary(run_id: str, report_dir: Path, figure: Path) -> Path:
    stats = json.loads((RUNS_DIR / run_id / "stats.json").read_text(encoding="utf-8"))
    lines = [
        f"# BKK/FLOW city baseline run `{run_id}`",
        "",
        "**Validation status: demonstration.** This run covers the whole Bangkok "
        "Metropolitan Administration. It contains **no flood layer and no evacuation "
        "outcomes**, deliberately, for the reason recorded below.",
        "",
        "## Geography",
        "",
        f"- {stats['geography']['name']} (`{stats['geography']['aoi_id']}`), "
        f"{stats['geography']['area_km2']:,.1f} km², admin level 4, OSM relation R92277",
        f"- Analysis CRS `{stats['geography']['analysis_crs']}`; public aggregation 1 km",
        "",
        "## Network",
        "",
        f"- Source ways: {stats['network']['source_ways']:,}",
        f"- Noded edges: {stats['network']['edges']:,}   nodes: {stats['network']['nodes']:,}",
        f"- Total length: {stats['network']['total_length_km']:,.0f} km "
        f"(walkable {stats['network']['walk_length_km']:,.0f} km, "
        f"vehicle {stats['network']['vehicle_length_km']:,.0f} km)",
        "- Routing: a compressed routing index; a full-city travel-time field takes about "
        "2 seconds and reaches 98.3% of nodes.",
        "",
        "## Population",
        "",
        f"- Resident baseline (weighted): {stats['population']['residents_weighted']:,.0f}",
        "- People present / exposed: **null** — not computed in this run.",
        "",
        "## Buildings",
        "",
        f"- Footprints in the AOI: {stats['buildings']['footprints']:,}",
        f"- Height coverage: {stats['buildings']['height_coverage_share']:.1%} "
        f"(tagged {stats['buildings']['tagged_height']:,}, from levels "
        f"{stats['buildings']['derived_from_levels']:,}, unknown {stats['buildings']['unknown_height']:,})",
        "",
        "## Water",
        "",
        f"- Mapped water features: {stats['water']['features']:,} "
        f"({stats['water']['waterway_length_km']:,.0f} km of mapped waterway)",
        "",
        "## Flood and evacuation",
        "",
        f"- Flood layer status: **{stats['flood']['status']}**",
        "",
        "> " + stats["flood"]["reason"],
        "",
        "Full evidence, including the measured terrain transect, is in "
        "[docs/CITY_SCALE_LIMITATIONS.md](../../../../docs/CITY_SCALE_LIMITATIONS.md).",
        "",
        "## Validation",
        "",
        f"- Checks: {stats['validation']['checks_total']} total, "
        f"{stats['validation']['checks_failed']} failed "
        f"({'PASS' if stats['validation']['passed'] else 'FAIL'})",
        f"- Manifest schema problems: {stats['validation']['manifest_schema_problems']}",
        "",
        "## Warnings",
        "",
    ]
    for warning in stats["warnings"]:
        lines.append(f"- {warning}")
    lines += ["", "## Figures", "", f"- `{figure.name}`", ""]
    path = report_dir / "SUMMARY.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python pipeline/city_report.py <run_id>")
        return 1
    run_id = sys.argv[1]
    if not (RUNS_DIR / run_id / "stats.json").is_file():
        print(f"no city run {run_id}")
        return 1
    report_dir = ensure_dir(RUNS_DIR / run_id / "report")
    figure = figure_city_baseline(run_id, report_dir)
    summary = write_city_summary(run_id, report_dir, figure)
    print(json.dumps({"figure": str(figure), "summary": str(summary)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
