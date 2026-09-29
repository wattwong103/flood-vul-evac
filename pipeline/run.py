#!/usr/bin/env python
"""BKK/FLOW pipeline command line.

    python pipeline/run.py ingest      # fetch and stage licensed sources
    python pipeline/run.py run         # execute one full run
    python pipeline/run.py run --baseline   # dry run for comparison
    python pipeline/run.py validate    # re-validate the newest run

Everything downloaded or derived is written under data/ and runs/, both of
which are git-ignored. Nothing in this tool is an emergency service.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bkkflow import aoi as aoi_module  # noqa: E402
from bkkflow import population as population_module  # noqa: E402
from bkkflow.http import HttpClient  # noqa: E402
from bkkflow.runner import execute_run  # noqa: E402
from bkkflow.sources import osm  # noqa: E402
from bkkflow.sources import population_source  # noqa: E402
from bkkflow.sources.registry import load_registry  # noqa: E402
from bkkflow.util import CURATED_DIR, RUNS_DIR, ensure_dir, read_json, write_json  # noqa: E402

PILOT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "pilot.json"


def cmd_ingest(args: argparse.Namespace) -> int:
    """Stage the AOI, OSM extract and population raster for the pilot."""
    pilot = read_json(PILOT_CONFIG)
    aoi_id = pilot["aoi"]["aoi_id"]
    client = HttpClient()

    print(f"[aoi] resolving {aoi_id}")
    aoi_path = CURATED_DIR / "aoi" / f"{aoi_id}.parquet"
    if not aoi_path.is_file():
        frame, record = aoi_module.fetch_boundary(
            client,
            osm_type="relation",
            osm_id=3147280,
            aoi_id=aoi_id,
            analysis_crs=pilot["analysis_crs"],
            name=pilot["aoi"]["name"],
            name_en=pilot["aoi"]["name_en"],
            admin_level=pilot["aoi"]["admin_level"],
        )
        saved = aoi_module.save_aoi(frame, record)
        print(f"[aoi] {saved['area_km2']} km2, saved to {saved['parquet']}")
    else:
        print(f"[aoi] already staged at {aoi_path}")

    bbox = aoi_module.bbox(aoi_id)
    print(f"[osm] fetching extract for bbox {[round(v, 5) for v in bbox]}")
    roads, roads_record = osm.fetch_roads(client, bbox)
    buildings, buildings_record = osm.fetch_buildings(client, bbox)
    water, water_record = osm.fetch_water(client, bbox)
    out = ensure_dir(CURATED_DIR / "osm")
    layers = [
        osm.save_layer(roads, "roads", out),
        osm.save_layer(buildings, "buildings", out),
        osm.save_layer(water, "water", out),
    ]
    write_json(
        out / "provenance.json",
        {
            "aoi_id": aoi_id,
            "bbox_wgs84": list(bbox),
            "layers": layers,
            "fetches": [roads_record.as_dict(), buildings_record.as_dict(), water_record.as_dict()],
        },
    )
    print(f"[osm] {len(roads)} ways, {len(buildings)} buildings, {len(water)} water features")

    print("[population] resolving WorldPop count raster")
    dataset = population_source.select_dataset(population_source.list_datasets(client))
    raster_path, meta = population_source.download_count_raster(client, dataset)
    print(f"[population] {raster_path.name} ({meta['byte_count']:,} bytes)")

    import geopandas as gpd

    aoi_frame = aoi_module.load_aoi(aoi_id)
    clip_path = CURATED_DIR / "population" / f"{raster_path.stem}_aoi.tif"
    stats = population_source.clip_to_aoi(raster_path, aoi_frame.geometry.iloc[0], clip_path)
    print(
        f"[population] clip total {stats['clip_total_population']:,.0f} "
        f"across {stats['clip_nonzero_cells']:,} cells"
    )

    cells = population_module.build_population_cells(
        clip_path,
        aoi_frame,
        population_version=read_json(PILOT_CONFIG.parent / "population.json")["population_version"],
        analysis_crs=pilot["analysis_crs"],
    )
    out_dir = ensure_dir(CURATED_DIR / "population")
    cells.to_parquet(out_dir / "population_cells.parquet", index=False)
    print(f"[population] {len(cells):,} cells, {cells['pop_count'].sum():,.0f} residents")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    summary = execute_run(flood_enabled=not args.baseline, max_agents=args.max_agents)
    print(json.dumps({key: value for key, value in summary.items() if key != "stats"}, indent=2))
    print(json.dumps(summary["stats"]["population"], indent=2))
    print(json.dumps(summary["stats"]["flood"], indent=2))
    print(json.dumps(summary["stats"]["evacuation"], indent=2)[:1500])
    return 0 if summary["validation_passed"] else 2


def cmd_validate(args: argparse.Namespace) -> int:
    run_id = args.run_id
    if not run_id:
        runs = sorted(RUNS_DIR.glob("*/validation.json"), key=lambda p: p.stat().st_mtime)
        if not runs:
            print("no runs found", file=sys.stderr)
            return 1
        run_id = runs[-1].parent.name
    payload = read_json(RUNS_DIR / run_id / "validation.json")
    print(json.dumps(payload, indent=2)[:4000])
    return 0 if payload["passed"] else 2


def cmd_registry(args: argparse.Namespace) -> int:
    print(json.dumps(load_registry().summary(), indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest", help="stage licensed sources").set_defaults(func=cmd_ingest)
    sub.add_parser("registry", help="print the source registry").set_defaults(func=cmd_registry)

    run = sub.add_parser("run", help="execute one full run")
    run.add_argument("--baseline", action="store_true", help="disable the flood scenario")
    run.add_argument("--max-agents", type=int, default=None)
    run.set_defaults(func=cmd_run)

    validate = sub.add_parser("validate", help="re-validate a run")
    validate.add_argument("--run-id", default=None)
    validate.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
