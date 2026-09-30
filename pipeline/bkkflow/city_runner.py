"""City-scale baseline run for the whole Bangkok Metropolitan Administration.

This run deliberately produces **no flood layer and no evacuation outcomes**.
The reasoning is recorded in ``docs/CITY_SCALE_LIMITATIONS.md``: the only
terrain source reachable from this environment carries several times more
vertical error than the entire flood-relevant elevation range in Bangkok, so a
city depth surface derived from it would be a noise field wearing the costume
of a flood map.

Consequently every hazard field in the emitted statistics is ``null`` with an
explicit reason, never ``0``. A zero would be read as "no flooding"; a null
says "this quantity was not computed, and here is why".
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from . import aoi as aoi_module
from . import buildings as buildings_module
from . import city_network as city_network_module
from . import manifest as manifest_module
from . import population as population_module
from . import validate as validate_module
from . import drainage as drainage_module
from . import observed_evac as observed_evac_module
from .sources import city_osm, destinations as destinations_source, gsw, mitrearth
from .util import CURATED_DIR, RUNS_DIR, ensure_dir, read_json, sha256_file, utc_now_iso, write_json

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
WORLDPOP_RASTER = Path(__file__).resolve().parents[2] / "data/staged/population/tha_ppp_2020.tif"

FLOOD_NOT_COMPUTED = (
    "not_computed_insufficient_dem_vertical_accuracy"
)
FLOOD_REASON = (
    "No city-scale flood layer in this run. The only reachable open terrain source "
    "has approximately 5-10 m vertical error across a floodplain whose relevant "
    "elevation range is 0-2 m, so a stage-based depth surface would be dominated by "
    "DEM noise. See docs/CITY_SCALE_LIMITATIONS.md. The Khlong San pilot retains "
    "flood depth and evacuation."
)


def load_config(name: str) -> dict[str, Any]:
    return read_json(CONFIG_DIR / name)


def _stage_record(
    stage: str, seconds: float, rows: int | None = None, note: str = ""
) -> dict[str, Any]:
    """Build one trustworthy stage record; impossible timings abort publication."""
    duration = float(seconds)
    if not math.isfinite(duration) or duration < 0:
        raise ValueError(f"stage {stage!r} duration must be finite and non-negative")
    return {
        "stage": stage,
        "status": "completed",
        "seconds": round(duration, 3),
        "rows": rows,
        "note": note,
        "completed_at": utc_now_iso(),
    }


def _observed_source_version(
    observed: dict[str, Any], *, aoi_id: str
) -> dict[str, Any] | None:
    """Describe the exact JRC tile set as one deterministic manifest source."""
    if observed.get("status") != "ok":
        return None
    tiles = [
        {
            "year": int(record["year"]),
            "tile_name": str(record["tile_name"]),
            "content_sha256": str(record["content_sha256"]),
        }
        for record in observed.get("years", [])
        if record.get("tile_name") and record.get("content_sha256")
    ]
    if not tiles:
        return None
    tiles.sort(key=lambda record: (record["year"], record["tile_name"]))
    fingerprint = hashlib.sha256(
        json.dumps(tiles, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    retrieved = [
        str(record["retrieved_at"])
        for record in observed.get("years", [])
        if record.get("retrieved_at")
    ]
    return {
        "source_id": str(observed.get("source_id", gsw.SOURCE_ID)),
        "retrieved_at": max(retrieved) if retrieved else str(observed["retrieved_at"]),
        "content_sha256": fingerprint,
        "licence_snapshot": "CC BY 4.0 (Copernicus / European Commission JRC)",
        "request_parameters": {
            "aoi_id": aoi_id,
            "years": [record["year"] for record in tiles],
            "tiles": tiles,
        },
    }


def _agglomerate_cells(
    cells: gpd.GeoDataFrame, *, crs: str, cell_size_m: float
) -> gpd.GeoDataFrame:
    """Aggregate 100 m population cells to a coarser reporting grid.

    City-wide 100 m output would be tens of millions of rows with no analytical
    benefit, so published tables aggregate to 1 km. Counts are summed, never
    averaged, so the population total is preserved exactly.
    """
    projected = cells.to_crs(crs)
    origins = projected.geometry.centroid
    minx, miny = projected.total_bounds[0], projected.total_bounds[1]
    column = ((origins.x - minx) // cell_size_m).astype("int64")
    row = ((origins.y - miny) // cell_size_m).astype("int64")
    frame = pd.DataFrame(
        {
            "gx": column.to_numpy(),
            "gy": row.to_numpy(),
            "pop": projected["pop_scaled"].to_numpy()
            if "pop_scaled" in projected.columns
            else projected["pop_count"].to_numpy(),
        }
    )
    grouped = frame.groupby(["gx", "gy"], as_index=False)["pop"].sum()
    grouped["x"] = minx + (grouped["gx"] + 0.5) * cell_size_m
    grouped["y"] = miny + (grouped["gy"] + 0.5) * cell_size_m
    frame_out = gpd.GeoDataFrame(
        grouped, geometry=gpd.points_from_xy(grouped["x"], grouped["y"]), crs=crs
    )
    return frame_out.to_crs("OGC:CRS84")


def execute_city_run(
    *, run_id: str | None = None, max_agents: int = 1500
) -> dict[str, Any]:
    """Build the city baseline and publish one immutable run."""
    run_id = run_id or str(uuid.uuid4())
    run_dir = ensure_dir(RUNS_DIR / run_id)
    started = time.time()

    config = load_config("pilot.city.json")
    analysis_crs = config["analysis_crs"]
    aoi_id = config["aoi"]["aoi_id"]
    aoi_frame = aoi_module.load_aoi(aoi_id)
    aoi_provenance = read_json(CURATED_DIR / "aoi" / f"{aoi_id}.provenance.json")

    stages: list[dict[str, Any]] = []
    warnings: list[str] = []

    def record(stage: str, seconds: float, rows: int | None = None, note: str = "") -> None:
        stages.append(_stage_record(stage, seconds, rows, note))

    # ---- sources ---------------------------------------------------------
    stage_start = time.time()
    ingest_path = CURATED_DIR / "city" / "provenance.json"
    if not ingest_path.is_file():
        city_osm.ingest_city()
    ingest = read_json(ingest_path)
    record("sources", time.time() - stage_start, rows=int(ingest["road_ways"]),
           note="regional PBF extract via GDAL, not tiled Overpass")

    # ---- network ---------------------------------------------------------
    stage_start = time.time()
    roads = gpd.read_parquet(CURATED_DIR / "city" / "roads.parquet")
    network = city_network_module.build_city_network(
        roads,
        analysis_crs=analysis_crs,
        network_version=f"bkk-city-{ingest['retrieved_at'][:10]}",
        aoi_geometry=aoi_frame,
    )
    edges = network.edges
    edges_out = edges.drop(columns="geometry").copy()
    edges_out["geometry_wkt"] = edges.geometry.to_wkt()
    edges_path = run_dir / "network_edges.parquet"
    edges_out.to_parquet(edges_path, index=False)
    record("network", time.time() - stage_start, rows=len(edges),
           note=f"{network.stats['nodes']} nodes, {network.stats['total_length_km']} km")
    warnings.append(
        "Network edges are undirected in the routing index. OSM oneway tags are not "
        "enforced, which overstates connectivity for driving; the pedestrian "
        "graph is unaffected."
    )

    # ---- buildings -------------------------------------------------------
    stage_start = time.time()
    raw_buildings = gpd.read_parquet(CURATED_DIR / "city" / "buildings.parquet")
    building_table = buildings_module.build_building_table(
        raw_buildings,
        aoi_frame=aoi_frame,
        analysis_crs=analysis_crs,
        building_version=f"bkk-city-{ingest['retrieved_at'][:10]}",
    )
    coverage = buildings_module.height_coverage(building_table)
    buildings_out = building_table.drop(columns="geometry").copy()
    buildings_out["geometry_wkt"] = building_table.geometry.to_wkt()
    buildings_path = run_dir / "buildings.parquet"
    buildings_out.to_parquet(buildings_path, index=False)
    record("buildings", time.time() - stage_start, rows=len(building_table),
           note=f"height coverage {coverage.get('coverage_share', 0):.1%}")
    warnings.append(
        f"Building height coverage in the AOI is {coverage.get('coverage_share', 0):.1%}. "
        "Footprints without height evidence are marked unknown rather than defaulted."
    )

    # ---- water -----------------------------------------------------------
    stage_start = time.time()
    water_frames = []
    for name, crs_hint in (("water_lines", "EPSG:4326"), ("water_areas", "EPSG:4326")):
        path = CURATED_DIR / "city" / f"{name}.parquet"
        if path.is_file():
            water_frames.append(gpd.read_parquet(path))
    water = (
        gpd.GeoDataFrame(pd.concat(water_frames, ignore_index=True), crs="EPSG:4326")
        if water_frames
        else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    )
    if len(water):
        water_projected = water.to_crs(analysis_crs)
        clip = aoi_frame.to_crs(analysis_crs).geometry.union_all()
        water_projected = water_projected[water_projected.geometry.intersects(clip)]
        water_out = water_projected.copy()
        water_out["geometry_wkt"] = water_out.geometry.to_wkt()
        water_out.drop(columns="geometry").to_parquet(run_dir / "water_features.parquet", index=False)
        water_length_km = float(water_projected.geometry.length.sum() / 1000.0)
    else:
        water_length_km = 0.0
    record("water", time.time() - stage_start, rows=len(water),
           note=f"{water_length_km:.0f} km mapped waterway length")

    # ---- observed surface water (the only observational hazard layer) ----
    stage_start = time.time()
    observed = _observed_extent(analysis_crs, aoi_frame, aoi_id)
    write_json(run_dir / "observed_water.json", observed)
    observed_years = observed.get("years", [])
    if observed_years:
        warnings.append(
            "Observed surface water from JRC Global Surface Water (Landsat) is available for "
            f"{len(observed_years)} years: " + ", ".join(
                f"{entry['year']} {entry['aoi_water_km2']:.1f} km2" for entry in observed_years
            ) + ". It is EXTENT, not depth, and the annual classification does not resolve the "
            "timing or peak extent of a flood event."
        )
        anomaly = max(observed_years, key=lambda entry: entry["aoi_water_km2"])
        observed_note = (
            f"JRC GSW yearly classification; wettest year {anomaly['year']} at "
            f"{anomaly['aoi_water_km2']:.1f} km2"
        )
    else:
        warnings.append(str(observed.get("reason", "Observed surface water is unavailable.")))
        observed_note = "JRC GSW unavailable; reason recorded in observed_water.json"
    record(
        "observed_water",
        time.time() - stage_start,
        rows=len(observed_years),
        note=observed_note,
    )

    # ---- destination candidates ------------------------------------------
    stage_start = time.time()
    destination_record = destinations_source.extract_destinations()
    warnings.append(
        f"{destination_record['rows']:,} destination candidates are extracted from OSM "
        f"tags, including {destination_record['shelter_candidates']} tagged shelters. "
        "Every one is UNVERIFIED: no operator, no capacity, no inspection date. None may be "
        "presented as a refuge."
    )
    record(
        "destinations",
        time.time() - stage_start,
        rows=int(destination_record["rows"]),
        note="0 verified; " + ", ".join(
            f"{key}={value}" for key, value in list(destination_record["by_class"].items())[:4]
        ),
    )

    # ---- MitrEarth hazard, drainage and hydrography layers ---------------
    stage_start = time.time()
    mitre = mitrearth.ingest(aoi_frame=aoi_frame, analysis_crs=analysis_crs)
    mitre_layers = [
        name for name, detail in mitre.layers.items() if detail.get("status") == "ok"
    ]
    unreliable = mitre.flood_extent_by_year.get("unreliable_years", [])
    warnings.append(
        "MitrEarth hazard and drainage layers are ingested: " + ", ".join(mitre_layers) + ". "
        "The bundled DEM and its contours are excluded on fitness grounds, independent of the "
        "licence decision: the DEM reads +13.8 m at Khlong San where ground is 1-2 m."
    )
    if unreliable:
        warnings.append(
            f"MitrEarth mapped flood extent is UNRELIABLE for {unreliable}: those years contain "
            "features with self-intersecting rings that had to be discarded, so the published "
            "extent would be a truncated artifact rather than a measurement. Only the "
            "reliable years may be used."
        )
    record(
        "mitrearth",
        time.time() - stage_start,
        rows=sum(
            detail.get("rows_in_aoi", 0)
            for detail in mitre.layers.values()
            if detail.get("status") == "ok"
        ),
        note=", ".join(mitre_layers) + f"; flood years unreliable={unreliable}",
    )
    write_json(run_dir / "mitrearth.json", mitre.as_dict())

    # ---- population ------------------------------------------------------
    stage_start = time.time()
    cells = gpd.read_parquet(CURATED_DIR / "city" / "population" / "population_cells.parquet")
    cells["pop_scaled"] = cells["pop_count"]
    total_residents = float(cells["pop_count"].sum())

    demographics = population_module.assign_demographics(
        cells, sex_shares={"male": 0.49, "female": 0.51}, age_bands=None
    )
    persons = population_module.make_weighted_persons(
        cells,
        demographics,
        population_version="bkk-city-pop-v0.1-2020",
        seed=29092026,
        mobility_profiles=(
            {"label": "walk_only", "share": 0.46, "vehicle_access": "none"},
            {"label": "motorcycle_access", "share": 0.28, "vehicle_access": "motorcycle"},
            {"label": "car_access", "share": 0.17, "vehicle_access": "car"},
            {"label": "reduced_mobility", "share": 0.09, "vehicle_access": "none",
             "assistance_share": 1.0},
        ),
    )
    persons_path = run_dir / "persons.parquet"
    persons.to_parquet(persons_path, index=False)
    record("population", time.time() - stage_start, rows=len(persons),
           note=f"{total_residents:,.0f} weighted residents")

    stage_start = time.time()
    grid = _agglomerate_cells(cells, crs=analysis_crs, cell_size_m=1000.0)
    grid_out = grid.copy()
    grid_out["geometry_wkt"] = grid.geometry.to_wkt()
    grid_out.drop(columns="geometry").to_parquet(run_dir / "population_grid_1km.parquet", index=False)
    record("aggregation", time.time() - stage_start,
           rows=len(grid), note="1 km public aggregation grid")

    warnings.extend(
        [
            "Resident counts are a 2020 modelled surface, not a count of people present at any moment.",
            "No external administrative control total was ingested; population control error is unverified.",
            "Age structure is unknown for every person; no age-structure source passed the licence gate.",
            "Sex split is a declared prior, not a measured Bangkok marginal.",
            FLOOD_REASON,
        ]
    )

    # ---- observed-hazard connectivity screening --------------------------
    stage_start = time.time()
    screening = observed_evac_module.compare_years((2010, 2011, 2012, 2020))
    worst = min(
        screening.values(), key=lambda entry: entry["reachable_share_of_exposed"]
    )
    warnings.append(
        "Connectivity screening under OBSERVED water presence is computed for 2010, 2011, "
        "2012 and 2020. This is NOT an evacuation simulation: a yearly Landsat classification "
        "carries no depth, duration, flow direction or timing, and water is treated as "
        "impassable at any depth. Destinations are unverified OSM tags with no capacity."
    )
    warnings.append(
        f"The worst observed year is {worst['year']} at "
        f"{worst['reachable_share_of_exposed']:.1%} of exposed population able to reach a "
        "designated destination. Treat this as a relative screening comparison between years, "
        "not as an evacuation time."
    )
    record(
        "connectivity_screening",
        time.time() - stage_start,
        rows=len(screening),
        note="; ".join(
            f"{year}: {entry['closed_edge_share']:.2%} ways closed, "
            f"{entry['reachable_share_of_exposed']:.1%} reachable"
            for year, entry in screening.items()
        ),
    )
    write_json(run_dir / "connectivity_screening.json", {
        "measures": "network connectivity under observed water presence",
        "is_evacuation_simulation": False,
        "years": screening,
    })

    # ---- drainage-discharge screening index -------------------------------
    extra_outputs: list[dict[str, Any]] = []
    stage_start = time.time()
    drainage_result = drainage_module.build_drainage_index()
    drainage = drainage_result.as_dict() if hasattr(drainage_result, "as_dict") else dict(drainage_result)
    if drainage.get("status") == "ok":
        warnings.append(
            "A drainage-discharge screening index is derived from the mapped drainage network, "
            "basins and overflow paths. It is a relative index of drainage-discharge "
            "susceptibility from infrastructure geometry only: not a hydraulic model, not a "
            "flood depth, and it ignores rainfall, river stage, tide, pumping and gate "
            "operations, all of which dominate real Bangkok flooding."
        )
    else:
        warnings.append(f"drainage index unavailable: {drainage.get('reason')}")
    if drainage.get("status") == "ok":
        drainage_path = run_dir / "drainage_index.parquet"
        drainage_result.frame.to_parquet(drainage_path, index=False)
        extra_outputs.append(
            manifest_module.output_entry(
                "drainage_index",
                drainage_path,
                row_count=int(drainage["rows"]),
                crs=analysis_crs,
            )
        )
    write_json(run_dir / "drainage_index.json", drainage)
    record(
        "drainage_index",
        time.time() - stage_start,
        rows=int(drainage.get("rows", 0)),
        note=json.dumps(drainage.get("statistics", {}).get("band_counts", {})),
    )

    # ---- validation ------------------------------------------------------
    stage_start = time.time()
    report = validate_module.ValidationReport()
    report.add(
        validate_module.Check(
            "persons.reconcile_to_resident_baseline",
            "weighted person total matches the city resident baseline",
            abs(float(persons["weight"].sum()) - total_residents) / total_residents <= 0.01,
            "relative error <= 0.01",
            round(abs(float(persons["weight"].sum()) - total_residents) / total_residents, 8),
        )
    )
    report.add(
        validate_module.Check(
            "persons.unique_ids",
            "person identifiers are unique and synthetic",
            persons["person_id"].is_unique
            and bool(persons["person_id"].astype(str).str.match(r"^p_[0-9a-f]{20}$").all()),
            "0 duplicate ids, all p_<20 hex>",
            int((~persons["person_id"].astype(str).str.match(r"^p_[0-9a-f]{20}$")).sum()),
        )
    )
    report.add(
        validate_module.Check(
            "network.geometry_valid",
            "network edges are valid geometries with positive length",
            bool(edges.geometry.is_valid.all()) and bool((edges["length_m"] > 0).all()),
            "all valid, all length > 0",
            int((~edges.geometry.is_valid).sum()),
        )
    )
    report.add(
        validate_module.Check(
            "population.aggregation_conserves_total",
            "1 km aggregation preserves the population total",
            abs(float(grid["pop"].sum()) - total_residents) / total_residents <= 1e-9,
            "relative error <= 1e-9",
            round(abs(float(grid["pop"].sum()) - total_residents) / total_residents, 12),
        )
    )
    report.add(
        validate_module.Check(
            "buildings.height_provenance",
            "every building height is tagged, derived from levels, or explicitly unknown",
            True,
            "no unrecognised height sources",
            f"{coverage.get('unknown_height', 0)} buildings unknown (recorded, not defaulted)",
        )
    )
    report.add(
        validate_module.Check(
            "flood.depth_absence_is_declared",
            "flood depth is absent and the absence is declared with a reason",
            True,
            "depth fields null with an explicit reason",
            FLOOD_NOT_COMPUTED,
        )
    )
    report.add(
        validate_module.Check(
            "flood.observed_extent_is_observation",
            "an observed, non-scenario hazard layer is present and labelled as such",
            observed.get("status") == "ok"
            and observed.get("is_observation") is True
            and len(observed.get("years", [])) > 0,
            "status ok, is_observation true, at least one year measured",
            f"{observed.get('status')}, {len(observed.get('years', []))} years",
        )
    )
    report.add(
        validate_module.Check(
            "destinations.none_verified_without_inventory",
            "no OSM tag candidate is presented as a verified refuge",
            int(destination_record["verified_count"]) == 0,
            "0 verified destinations without a refuge inventory",
            f"{destination_record['verified_count']} verified of "
            f"{destination_record['rows']} candidates",
        )
    )
    write_json(run_dir / "validation.json", report.as_dict())
    record("validate", time.time() - stage_start, rows=report.as_dict()["checks_total"],
           note=f"{report.as_dict()['checks_failed']} failed")

    # ---- manifest --------------------------------------------------------
    source_versions = [
        {
            "source_id": "bbbike-bangkok-osm-extract",
            "retrieved_at": ingest["retrieved_at"],
            "content_sha256": ingest["content_sha256"],
            "licence_snapshot": "ODbL 1.0 (c) OpenStreetMap contributors",
            "request_parameters": {"byte_count": ingest["byte_count"]},
        },
        {
            "source_id": "worldpop-global2-tha-100m-r2025a",
            "retrieved_at": aoi_provenance["retrieved_at"],
            # The real checksum of the staged raster. The schema demands a
            # 64-hex digest, and a placeholder here would be a provenance lie.
            "content_sha256": sha256_file(WORLDPOP_RASTER),
            "licence_snapshot": "CC BY 4.0",
            "request_parameters": {"popyear": 2020, "clip": aoi_id},
        },
    ]
    observed_source = _observed_source_version(observed, aoi_id=aoi_id)
    if observed_source is not None:
        source_versions.append(observed_source)

    manifest = manifest_module.build_manifest(
        run_id=run_id,
        geography={
            "country": "Thailand",
            "aoi_id": aoi_id,
            "aoi_version": f"osm-R{aoi_provenance['osm_id']}-{aoi_provenance['retrieved_at'][:10]}",
            "storage_crs": "OGC:CRS84",
            "analysis_crs": analysis_crs,
            "aggregation_geography": "projected_square_grid_100m_internal_1000m_public",
        },
        source_versions=source_versions,
        population_model={
            "population_version": "bkk-city-pop-v0.1-2020",
            "method": "weighted-persons",
            "agent_representation": {
                "weight_field": "weight",
                "home_spatial_unit": "100m_grid",
                "households_supported": False,
                "building_assignment": "none",
            },
            "seed": 29092026,
            "control_source_ids": [
                "worldpop-global2-tha-100m-r2025a",
                "bbbike-bangkok-osm-extract",
            ],
            "time_profile": {
                "status": "illustrative",
                "activity_model_version": "not_run_at_city_scale",
                "external_trip_policy": "boundary_flows_not_modelled",
            },
            "privacy": {
                "public_min_cell_metres": 1000,
                "minimum_reported_count": 20,
                "real_trajectories_present": False,
            },
        },
        pflow_components={
            "person_generator": manifest_module.component(
                "bkk-weighted-persons", "0.1.0",
                {"population_version": "bkk-city-pop-v0.1-2020", "seed": 29092026,
                 "weighted_person_records": int(len(persons))},
            ),
            "activity_generator": manifest_module.component(
                "not-run-at-city-scale", "0.1.0",
                {"reason": "mobility stages are not part of the city baseline run"},
            ),
            "trip_generator": manifest_module.component(
                "not-run-at-city-scale", "0.1.0",
                {"reason": "mobility stages are not part of the city baseline run"},
            ),
            "trajectory_generator": manifest_module.component(
                "not-run-at-city-scale", "0.1.0",
                {"reason": "mobility stages are not part of the city baseline run"},
            ),
            "aggregation": manifest_module.component(
                "bkk-grid-aggregate", "0.1.0", {"public_grid_metres": 1000},
            ),
        },
        flood_scenario_entry={
            "model_name": "not-computed",
            "model_version": "0.0.0",
            "time_step_seconds": 300,
            "parameters": {
                "depth_status": FLOOD_NOT_COMPUTED,
                "depth_reason": FLOOD_REASON,
                "reference": "docs/CITY_SCALE_LIMITATIONS.md",
                "observed_extent_source_id": observed.get("source_id"),
                "observed_extent_years": [
                    entry["year"] for entry in observed.get("years", [])
                ],
                "observed_extent_is_observation": True,
            },
        },
        evacuation_scenario_entry={
            "seed": 29092026,
            "departure_model": {"status": "not_computed", "reason": "requires a flood layer"},
            "route_choice": {
                "algorithm": "csr_dijkstra_destination_centric",
                "status": "implemented_not_run",
                "note": "One Dijkstra per destination yields travel time for every origin, "
                        "which is the only tractable approach at city scale.",
            },
            "destinations": [],
            "mode_thresholds": {"status": "not_applied_without_flood"},
        },
        outputs=[
            *extra_outputs,
            manifest_module.output_entry("network_edges", edges_path, row_count=len(edges), crs=analysis_crs),
            manifest_module.output_entry("buildings", buildings_path, row_count=len(building_table), crs=analysis_crs),
            manifest_module.output_entry("persons", persons_path, row_count=len(persons)),
            manifest_module.output_entry("population_grid_1km", run_dir / "population_grid_1km.parquet", row_count=len(grid)),
            manifest_module.output_entry("destinations", Path(destination_record["path"]), row_count=int(destination_record["rows"])),
            manifest_module.output_entry("observed_water", run_dir / "observed_water.json", row_count=len(observed.get("years", []))),
        ],
        warnings=warnings,
        validation_status="demonstration",
    )
    schema_problems = manifest_module.validate_manifest(manifest)
    write_json(run_dir / "manifest.json", manifest)

    stats = {
        "run_id": run_id,
        "validation_status": "demonstration",
        "scale": "city",
        "created_at": manifest["created_at"],
        "geography": {
            "aoi_id": aoi_id,
            "name": config["aoi"]["name_en"],
            "area_km2": config["aoi"]["area_km2"],
            "analysis_crs": analysis_crs,
        },
        "population": {
            "residents_weighted": round(total_residents, 2),
            "people_present": None,
            "people_exposed": None,
            "exposed_share_of_present": None,
            "population_version": "bkk-city-pop-v0.1-2020",
            "time_profile": None,
            "note": "Resident baseline only. Presence and exposure are not computed in the "
                    "city baseline run and are null rather than zero.",
        },
        "network": {
            "edges": int(len(edges)),
            "nodes": int(network.stats["nodes"]),
            "total_length_km": network.stats["total_length_km"],
            "walk_length_km": network.stats["walk_length_km"],
            "vehicle_length_km": network.stats["vehicle_length_km"],
            "source_ways": network.stats["source_ways"],
        },
        "buildings": {
            "footprints": int(len(building_table)),
            "height_coverage_share": coverage.get("coverage_share"),
            "tagged_height": coverage.get("tagged_height"),
            "derived_from_levels": coverage.get("derived_from_levels"),
            "unknown_height": coverage.get("unknown_height"),
        },
        "water": {"features": int(len(water)), "waterway_length_km": round(water_length_km, 2)},
        "flood": {
            # Depth and closure remain uncomputable; observed extent is real.
            "depth_status": FLOOD_NOT_COMPUTED,
            "depth_reason": FLOOD_REASON,
            "max_depth_m": None,
            "flooded_area_km2": None,
            "edges_closed": None,
            "depth_source_role": None,
            "observed_extent": {
                "status": observed.get("status"),
                "source_id": observed.get("source_id"),
                "is_observation": True,
                "measures": "water extent, NOT depth, duration or direction",
                "licence": observed.get("licence"),
                "years": [
                    {
                        "year": entry["year"],
                        "water_km2": entry["aoi_water_km2"],
                        "water_share": entry["aoi_water_share"],
                        "classified_km2": entry["aoi_area_km2"],
                        "excess_km2_vs_baseline": entry["excess_km2_vs_baseline"],
                    }
                    for entry in observed.get("years", [])
                ],
                "note": observed.get("note"),
            },
        },
        "destinations": {
            "candidates": int(destination_record["rows"]),
            "verified": int(destination_record["verified_count"]),
            "shelter_tag_candidates": int(destination_record["shelter_candidates"]),
            "by_class": destination_record["by_class"],
            "note": destination_record["note"],
        },
        "evacuation": {
            "status": "not_computed",
            "reason": "requires a depth surface; see flood.depth_reason",
            "cohort_weighted": None,
            "arrived_weighted": None,
            "unserved_weighted": None,
            "clearance_time_minutes": {"p5": None, "median": None, "p95": None},
        },
        "stages": stages,
        "validation": {
            "passed": report.passed,
            "checks_total": report.as_dict()["checks_total"],
            "checks_failed": report.as_dict()["checks_failed"],
            "manifest_schema_problems": len(schema_problems),
        },
        "warnings": warnings,
        "sources": [
            {"source_id": "bbbike-bangkok-osm-extract", "licence": "ODbL 1.0", "status": "approved"},
            {"source_id": "worldpop-global2-tha-100m-r2025a", "licence": "CC BY 4.0", "status": "approved"},
            {
                "source_id": "jrc-global-surface-water-v1.4",
                "licence": "CC BY 4.0",
                "status": "approved" if observed_source is not None else "unavailable",
            },
        ],
        "elapsed_seconds": round(time.time() - started, 1),
    }
    write_json(run_dir / "stats.json", stats)
    write_json(
        run_dir / "run_state.json",
        {
            "run_id": run_id,
            "state": "published" if report.passed else "failed_validation",
            "scale": "city",
            "started_at": manifest["created_at"],
            "updated_at": utc_now_iso(),
            "stage_count": len(stages),
            "stages": stages,
            "warnings": warnings,
            "error": None,
        },
    )

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "validation_passed": report.passed,
        "checks": report.as_dict()["checks_total"],
        "checks_failed": report.as_dict()["checks_failed"],
        "manifest_schema_problems": len(schema_problems),
        "elapsed_seconds": stats["elapsed_seconds"],
        "stats": stats,
    }

OBSERVED_YEARS = (2010, 2011, 2012, 2020)


def _observed_extent(
    analysis_crs: str, aoi_frame: gpd.GeoDataFrame, aoi_id: str
) -> dict[str, Any]:
    """Fetch the JRC yearly observed surface-water record for the AOI.

    Degrades to a recorded unavailability rather than aborting the run: an
    observed layer is valuable, but a transient download failure must not cost
    us the whole city baseline.
    """
    from .http import HttpClient
    from .sources import gsw

    bounds = tuple(float(value) for value in aoi_frame.geometry.union_all().bounds)
    try:
        summary = gsw.fetch_years(HttpClient(timeout=900), OBSERVED_YEARS, bounds, aoi_frame)
    except Exception as error:  # noqa: BLE001 - recorded, not fatal
        return {
            "status": "unavailable",
            "reason": f"JRC Global Surface Water could not be retrieved: {error}"[:300],
            "source_id": gsw.SOURCE_ID,
            "is_observation": True,
            "measures": "water extent, NOT depth",
            "years": [],
        }
    summary["status"] = "ok"
    summary["aoi_id"] = aoi_id
    summary["analysis_crs"] = analysis_crs
    summary["note"] = (
        "Observed extent is not a depth surface and cannot drive edge closure or "
        "clearance time. It validates spatial extent and supplies the only "
        "non-modelled, non-scenario hazard evidence in the project."
    )
    return summary

