#!/usr/bin/env python
"""BKK/FLOW pipeline command line.

    python pipeline/run.py ingest      # fetch and stage licensed sources
    python pipeline/run.py run         # execute one full run
    python pipeline/run.py run --baseline   # dry run for comparison
    python pipeline/run.py run --pilot sai-mai-district
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
from bkkflow.sources.pilot_stage import stage_pilot  # noqa: E402
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
    summary = execute_run(
        flood_enabled=not args.baseline,
        max_agents=args.max_agents,
        pilot_id=args.pilot,
        cohort_from_run=args.cohort_from_run,
    )
    print(json.dumps({key: value for key, value in summary.items() if key != "stats"}, indent=2))
    print(json.dumps(summary["stats"]["population"], indent=2))
    print(json.dumps(summary["stats"]["flood"], indent=2))
    print(json.dumps(summary["stats"]["evacuation"], indent=2)[:1500])
    return 0 if summary["validation_passed"] else 2


def cmd_stage_pilot(args: argparse.Namespace) -> int:
    summary = stage_pilot(args.pilot)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_ingest_city(args: argparse.Namespace) -> int:
    """Stage the whole-city OSM extract and the city population grid."""
    import geopandas as gpd

    from bkkflow import aoi as aoi_module
    from bkkflow import population as population_module
    from bkkflow.sources import city_osm, population_source
    from bkkflow.util import ensure_dir

    record = city_osm.ingest_city()
    print(
        f"[city] {record.road_ways:,} ways, {record.buildings:,} buildings, "
        f"{record.waterway_features:,} water features from {record.byte_count:,} bytes"
    )

    aoi_frame = aoi_module.load_aoi("bangkok-bma")
    clip = Path("data/staged/population/tha_ppp_2020_bangkok.tif")
    if not clip.is_file():
        clip.parent.mkdir(parents=True, exist_ok=True)
        stats = population_source.clip_to_aoi(
            "data/staged/population/tha_ppp_2020.tif", aoi_frame.geometry.iloc[0], clip
        )
        print(f"[city] population clip total {stats['clip_total_population']:,.0f}")
    cells = population_module.build_population_cells(
        clip, aoi_frame, population_version="bkk-city-pop-v0.1-2020", analysis_crs="EPSG:32647"
    )
    out = ensure_dir("data/curated/city/population")
    cells.to_parquet(out / "population_cells.parquet", index=False)
    print(f"[city] {len(cells):,} cells, {cells['pop_count'].sum():,.0f} residents")
    return 0


def cmd_city(args: argparse.Namespace) -> int:
    """Execute the city baseline run."""
    from bkkflow.city_runner import execute_city_run

    summary = execute_city_run()
    print(json.dumps({k: v for k, v in summary.items() if k != "stats"}, indent=2))
    print(json.dumps(summary["stats"]["network"], indent=2))
    print(json.dumps(summary["stats"]["buildings"], indent=2))
    flood = summary["stats"]["flood"]
    print(f"flood depth: {flood.get('depth_status')}")
    observed = flood.get("observed_extent") or {}
    print(f"observed extent: {observed.get('status')} ({len(observed.get('years', []))} years)")
    print(f"drainage index rows: {(summary['stats'].get('drainage') or {}).get('rows')}")
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
    sub.add_parser("ingest-city", help="stage whole-city OSM and population").set_defaults(
        func=cmd_ingest_city
    )
    sub.add_parser("city", help="execute the city baseline run").set_defaults(func=cmd_city)
    sub.add_parser("registry", help="print the source registry").set_defaults(func=cmd_registry)

    stage = sub.add_parser("stage-pilot", help="stage one named pilot from verified regional sources")
    stage.add_argument("--pilot", required=True, help="named AOI configuration")
    stage.set_defaults(func=cmd_stage_pilot)

    run = sub.add_parser("run", help="execute one full run")
    run.add_argument("--baseline", action="store_true", help="disable the flood scenario")
    run.add_argument("--max-agents", type=int, default=None)
    run.add_argument("--cohort-from-run", default=None)
    run.add_argument(
        "--pilot",
        default=None,
        help="named AOI configuration; omit for the legacy Khlong San invocation",
    )
    run.set_defaults(func=cmd_run)

    validate = sub.add_parser("validate", help="re-validate a run")
    validate.add_argument("--run-id", default=None)
    validate.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
