"""Run orchestration.

The runner executes the PFLOW stage sequence, writes one immutable artefact
per stage, records progress, and refuses to publish a run that fails
validation. Every stage is timed and its row count is reported, because the
website's stage rail reads those numbers directly.

The run state machine is:

    draft -> validating_inputs -> population -> activities -> trips ->
    trajectories -> aggregates -> flood -> cohort -> evacuation ->
    validating_outputs -> published | failed
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from . import aoi as aoi_module
from . import buildings as buildings_module
from . import evacuation as evacuation_module
from . import flood as flood_module
from . import manifest as manifest_module
from . import mobility as mobility_module
from . import network as network_module
from . import population as population_module
from . import validate as validate_module
from .code_identity import capture_code_identity, verify_code_identity
from .pilot_config import load_pilot_bundle
from .sources import pilot_stage
from .sources.registry import load_registry
from .util import (
    CURATED_DIR,
    REPO_ROOT,
    RUNS_DIR,
    read_json,
    utc_now_iso,
    write_json,
)

CONFIG_DIR = REPO_ROOT / "config"


def load_config(name: str) -> dict[str, Any]:
    return read_json(CONFIG_DIR / name)


@dataclass
class RunContext:
    run_id: str
    run_dir: Path
    pilot: dict[str, Any]
    population_config: dict[str, Any]
    scenario_config: dict[str, Any]
    input_root: Path
    versions: dict[str, str]
    sources: dict[str, str]
    named_pilot: bool
    active_scenario: dict[str, str]
    stages: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_versions: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = field(default_factory=utc_now_iso)

    def record(self, stage: str, seconds: float, rows: int | None = None, note: str = "") -> None:
        self.stages.append(
            {
                "stage": stage,
                "status": "completed",
                "seconds": round(float(seconds), 3),
                "rows": rows,
                "note": note,
                "completed_at": utc_now_iso(),
            }
        )

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def write_state(self, state: str, *, error: str | None = None) -> None:
        payload = {
            "run_id": self.run_id,
            "state": state,
            "started_at": self.started_at,
            "updated_at": utc_now_iso(),
            "stage_count": len(self.stages),
            "stages": self.stages,
            "warnings": self.warnings,
            "error": error,
            "active_scenario": dict(self.active_scenario),
        }
        write_json(self.run_dir / "run_state.json", payload)


def _write_parquet(context: RunContext, name: str, frame: pd.DataFrame | gpd.GeoDataFrame) -> Path:
    path = context.run_dir / name
    if isinstance(frame, gpd.GeoDataFrame):
        frame.to_parquet(path, index=False)
    else:
        frame.to_parquet(path, index=False)
    return path


def register_output(
    context: RunContext, role: str, path: Path, *, rows: int | None = None, crs: str | None = None
) -> None:
    entry = manifest_module.output_entry(role, path, row_count=rows, crs=crs)
    if any(existing.get("uri") == entry["uri"] for existing in context.outputs):
        raise ValueError(f"Duplicate output URI: {entry['uri']}")
    context.outputs.append(entry)


def _validate_cohort_reference(payload: Any, expected_run_id: str) -> dict[str, Any]:
    """Reject an explicit pair reference unless its canonical identity is complete."""
    if not isinstance(payload, dict):
        raise ValueError("cohort reference metadata must be a JSON object")
    required = {*evacuation_module.COHORT_IDENTITY_FIELDS, "run_id", "reference_run_id"}
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"cohort reference metadata missing fields: {', '.join(missing)}")
    text_fields = ("run_id", "aoi_id", "order_geometry_rule", "presence_rule", "sample_rule")
    if any(not isinstance(payload[key], str) or not payload[key].strip() for key in text_fields):
        raise ValueError("cohort reference metadata has an invalid text identity field")
    if payload["run_id"] != expected_run_id:
        raise ValueError("cohort reference metadata run_id does not match its directory")
    if payload["cohort_rule_version"] != evacuation_module.COHORT_RULE_VERSION:
        raise ValueError("cohort reference metadata has an unsupported rule version")
    if payload["reference_run_id"] is not None and (
        not isinstance(payload["reference_run_id"], str) or not payload["reference_run_id"].strip()
    ):
        raise ValueError("cohort reference metadata has an invalid reference_run_id")
    for key in ("seed", "max_agents", "scenario_time_s"):
        if type(payload[key]) is not int:
            raise ValueError(f"cohort reference metadata has invalid {key}")
    if payload["seed"] < 0 or not 0 < payload["max_agents"] <= evacuation_module.COHORT_CAP:
        raise ValueError("cohort reference metadata has invalid seed or sample cap")
    if payload["scenario_time_s"] < 0:
        raise ValueError("cohort reference metadata has invalid scenario_time_s")
    for key in ("order_radius_m", "sampling_probability"):
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
            raise ValueError(f"cohort reference metadata has invalid {key}")
    if payload["order_radius_m"] <= 0 or not 0 <= payload["sampling_probability"] <= 1:
        raise ValueError("cohort reference metadata has invalid radius or sampling probability")
    centres = (payload["order_centre_lon"], payload["order_centre_lat"])
    if centres != (None, None) and (
        any(isinstance(value, bool) or not isinstance(value, (int, float))
            or not np.isfinite(value) for value in centres)
        or not -180 <= centres[0] <= 180 or not -90 <= centres[1] <= 90
    ):
        raise ValueError("cohort reference metadata has invalid order centre")
    for key in ("sample_digest", "cohort_digest"):
        value = payload[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"cohort reference metadata has invalid {key}")
    return payload


def execute_run(
    *,
    run_id: str | None = None,
    flood_enabled: bool = True,
    max_agents: int | None = None,
    pilot_id: str | None = None,
    cohort_from_run: str | None = None,
) -> dict[str, Any]:
    """Run the full pipeline once and return the published run summary."""
    if type(flood_enabled) is not bool:
        raise ValueError("flood_enabled must explicitly select dry or moderate")
    bundle = load_pilot_bundle(
        pilot_id, config_dir=CONFIG_DIR, curated_dir=CURATED_DIR
    )
    if bundle.named:
        pilot_stage.validate_staged_pilot(
            bundle.input_root, expected_bundle=bundle
        )
    cohort_reference: dict[str, Any] | None = None
    if cohort_from_run is not None:
        if not isinstance(cohort_from_run, str) or not cohort_from_run.strip():
            raise ValueError("cohort reference run ID must be a non-empty string")
        reference_dir = (RUNS_DIR / cohort_from_run).resolve()
        if reference_dir.parent != RUNS_DIR.resolve():
            raise ValueError("cohort reference run must be a direct child of runs/")
        reference_path = reference_dir / "cohort_metadata.json"
        if not reference_path.is_file():
            raise ValueError(f"cohort reference has no cohort_metadata.json: {cohort_from_run}")
        try:
            loaded_reference = read_json(reference_path)
        except (OSError, ValueError) as exc:
            raise ValueError("cohort reference metadata is not valid JSON") from exc
        cohort_reference = _validate_cohort_reference(loaded_reference, cohort_from_run)
    run_id = run_id or str(uuid.uuid4())
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    code_identity = capture_code_identity()

    pilot = bundle.pilot
    population_config = bundle.population
    scenario_config = bundle.scenario
    active_scenario = {
        "state": "moderate" if flood_enabled else "dry",
        "configured_scenario_id": str(scenario_config["flood"]["scenario_id"]),
    }

    context = RunContext(
        run_id=run_id,
        run_dir=run_dir,
        pilot=pilot,
        population_config=population_config,
        scenario_config=scenario_config,
        input_root=bundle.input_root,
        versions=bundle.versions,
        sources=bundle.sources,
        named_pilot=bundle.named,
        active_scenario=active_scenario,
    )
    context.write_state("validating_inputs")

    analysis_crs = pilot["analysis_crs"]
    aoi_id = pilot["aoi"]["aoi_id"]
    registry = load_registry()

    # ---- licence gate ----------------------------------------------------
    required_sources = [bundle.sources["population"], bundle.sources["osm"]]
    registry.require_approved(required_sources)
    stage_start = time.time()
    context.record("sources", time.time() - stage_start, rows=len(registry), note="licence gate passed")

    # ---- AOI -------------------------------------------------------------
    if bundle.named:
        aoi_frame = gpd.read_parquet(bundle.input_root / "aoi.parquet")
        aoi_provenance = read_json(bundle.input_root / "aoi.provenance.json")
    else:
        aoi_frame = aoi_module.load_aoi(aoi_id)
        aoi_provenance = read_json(CURATED_DIR / "aoi" / f"{aoi_id}.provenance.json")
    aoi_path = _write_parquet(context, "aoi.parquet", aoi_frame)
    register_output(
        context, "aoi", aoi_path, rows=len(aoi_frame), crs=aoi_frame.crs.to_string()
    )
    osm_provenance = read_json(bundle.input_root / "osm" / "provenance.json")
    if bundle.named:
        expected = {
            "AOI aoi_id": (aoi_provenance.get("aoi_id"), aoi_id),
            "AOI relation": (
                aoi_provenance.get("osm_id"), pilot["aoi"]["osm_relation_id"]
            ),
            "AOI source": (aoi_provenance.get("source_id"), bundle.sources["osm"]),
            "OSM aoi_id": (osm_provenance.get("aoi_id"), aoi_id),
            "OSM source": (osm_provenance.get("source_id"), bundle.sources["osm"]),
        }
        mismatches = [
            f"{label}: {actual!r} != {wanted!r}"
            for label, (actual, wanted) in expected.items()
            if actual != wanted
        ]
        if mismatches:
            raise ValueError("Named pilot input identity mismatch: " + "; ".join(mismatches))
    context.source_versions.append(
        {
            "source_id": bundle.sources["osm"],
            "retrieved_at": aoi_provenance["retrieved_at"],
            "content_sha256": aoi_provenance["content_sha256"],
            "licence_snapshot": "ODbL 1.0 (c) OpenStreetMap contributors",
            "request_parameters": {"role": "aoi_boundary", "osm": f"R{aoi_provenance['osm_id']}"},
        }
    )

    # ---- P0/P1 population ------------------------------------------------
    stage_start = time.time()
    clip_path = bundle.input_root / "population" / "population_cells.parquet"
    cells = gpd.read_parquet(clip_path)
    if bundle.named:
        cell_versions = {str(value) for value in cells["population_version"].dropna().unique()}
        if cell_versions != {bundle.versions["population"]}:
            raise ValueError(
                "Named pilot population version mismatch: "
                f"{sorted(cell_versions)!r} != {[bundle.versions['population']]!r}"
            )
        population_provenance = read_json(bundle.input_root / "population" / "provenance.json")
        expected_population = {
            "aoi_id": aoi_id,
            "source_id": bundle.sources["population"],
            "population_version": bundle.versions["population"],
        }
        if any(population_provenance.get(key) != value
               for key, value in expected_population.items()):
            raise ValueError("Named pilot population provenance mismatch")
        context.source_versions.append(
            {
                "source_id": bundle.sources["population"],
                "retrieved_at": population_provenance["retrieved_at"],
                "content_sha256": population_provenance["content_sha256"],
                "licence_snapshot": "CC BY 4.0",
                "request_parameters": {
                    "role": "resident_population",
                    "aoi_id": aoi_id,
                    "resource_url": population_provenance["resource_url"],
                },
            }
        )
    total_residents = float(cells["pop_count"].sum())
    context.record("population_cells", time.time() - stage_start, rows=len(cells))

    population_version = population_config["population_version"]
    seed = int(population_config["seed"])

    sex_shares = population_config.get("sex_split")
    # Optional, config-supplied age structure. mode "none" (the default) ingests
    # no marginal, so age_band stays "unknown" for every person. "national"
    # applies one country marginal to every cell. "per_cell" samples the age/sex
    # rasters at each cell centre, which preserves spatial variation but changes
    # the population, so it must be enabled deliberately.
    age_config = population_config.get("age_structure") or {}
    age_mode = age_config.get("mode") or ("national" if age_config.get("bands") else "none")
    age_bands = None
    age_by_cell = None
    if age_mode == "per_cell":
        from bkkflow.sources import population_age

        age_by_cell = population_age.age_weights_by_cell(cells, age_config["raster_dir"])
        if not age_by_cell:
            raise ValueError(
                "per_cell age structure produced no weights; check raster coverage "
                "against this AOI"
            )
    elif age_mode == "national":
        age_bands = age_config.get("bands") or None
    elif age_mode != "none":
        raise ValueError(f"unknown age_structure.mode: {age_mode!r}")

    demographics = population_module.assign_demographics(
        cells.assign(pop_scaled=cells["pop_count"].to_numpy()),
        sex_shares=sex_shares,
        age_bands=age_bands,
        age_bands_by_cell=age_by_cell,
    )
    if "unknown" in set(demographics["age_band"]):
        context.warn(
            "age_band is 'unknown' for every person; this build ingests no "
            "age-structure marginal."
        )

    persons = population_module.make_weighted_persons(
        cells,
        demographics,
        population_version=population_version,
        seed=seed,
        mobility_profiles=tuple(population_config["mobility_profiles"]),
    )
    for warning in population_config.get("warnings", []):
        context.warn(warning)
    persons_path = _write_parquet(context, "persons.parquet", persons)
    register_output(context, "persons", persons_path, rows=len(persons))

    population_qa = population_module.PopulationQA(
        population_version=population_version,
        status="demonstration",
        total_residents=total_residents,
        cell_count=int(len(cells)),
        occupied_cell_count=int((cells["pop_count"] > 0).sum()),
        sparsity=round(float(1.0 - (cells["pop_count"] > 0).sum() / max(len(cells), 1)), 6),
        control_error={
            "status": "unavailable",
            "reason": "no external administrative control total was ingested in this build",
        },
        demographics={
            "age_bands": (
                {label: float(share) for label, share in age_config["bands"].items()}
                if age_mode == "national" and age_config.get("bands")
                else {"unknown": 1.0}
            ),
            "age_structure_mode": age_mode,
            "sex_split": sex_shares or {"male": 0.5, "female": 0.5},
            # Record what actually happened. "not_configured" means this build
            # supplies no age structure; it does NOT mean a licence gate
            # refused one. The registry holds approved age/sex sources that are
            # simply not ingested, and reporting that as a licence failure
            # would state something false in the run record.
            "age_structure_source": (
                age_config.get("source_id", "unknown") if age_mode != "none" else "not_configured"
            ),
            "age_structure_status": age_config.get("status", "unknown"),
            "age_structure_spatial": age_mode == "per_cell",
        },
        building_allocation={
            "status": "none",
            "reason": "OSM building use does not prove residential occupancy; allocation would be an invention",
        },
        warnings=list(context.warnings),
    ).as_dict()
    write_json(run_dir / "population_qa.json", population_qa)
    context.record("persons", time.time() - stage_start, rows=len(persons))

    # ---- network ---------------------------------------------------------
    stage_start = time.time()
    roads = gpd.read_parquet(bundle.input_root / "osm" / "roads.parquet")
    network_version = f"{bundle.versions['network']}-{osm_provenance['fetches'][0]['retrieved_at'][:10]}"
    build = network_module.build_network(
        roads, analysis_crs=analysis_crs, network_version=network_version, aoi_geometry=aoi_frame
    )
    edges = build.edges
    edges_out = edges.copy()
    edges_out["geometry_wkt"] = edges_out.geometry.to_wkt(rounding_precision=-1)
    edges_path = _write_parquet(context, "network_edges.parquet", edges_out.drop(columns="geometry"))
    register_output(context, "network_edges", edges_path, rows=len(edges), crs=analysis_crs)
    for fetch in osm_provenance["fetches"]:
        context.source_versions.append(
            {
                "source_id": bundle.sources["osm"],
                "retrieved_at": fetch["retrieved_at"],
                "content_sha256": fetch["content_sha256"],
                "licence_snapshot": "ODbL 1.0 (c) OpenStreetMap contributors",
                "request_parameters": {"layer": "osm_extract", "query_sha256": fetch["query_sha256"]},
            }
        )
    context.record("network", time.time() - stage_start, rows=len(edges), note=json_note(build.stats))

    # ---- buildings -------------------------------------------------------
    stage_start = time.time()
    raw_buildings = gpd.read_parquet(bundle.input_root / "osm" / "buildings.parquet")
    building_table = buildings_module.build_building_table(
        raw_buildings,
        aoi_frame=aoi_frame,
        analysis_crs=analysis_crs,
        building_version=f"{bundle.versions['buildings']}-{osm_provenance['fetches'][1]['retrieved_at'][:10]}",
    )
    coverage = buildings_module.height_coverage(building_table)
    if coverage.get("coverage_share", 0) < 0.5:
        context.warn(
            f"building height coverage is {coverage.get('coverage_share', 0):.1%}; "
            "most footprints have no height evidence and are marked unknown rather than defaulted."
        )
    candidate_count = int(building_table["osm_shelter_tag"].sum())
    if candidate_count:
        context.warn(
            f"{candidate_count} OSM amenity=shelter tags exist in the AOI. They are unverified "
            "candidates and are never presented as refuges."
        )
    context.record("buildings", time.time() - stage_start, rows=len(building_table), note=json_note(coverage))

    # ---- P2/P3/P4 mobility ---------------------------------------------
    stage_start = time.time()
    limit = max_agents or int(population_config["mobility_sample"]["max_agents"])
    sample = population_module.sample_representative_agents(persons, max_agents=limit, seed=seed)
    cells_projected = cells.to_crs(analysis_crs)
    cell_centroids = cells_projected.geometry.centroid
    homes_xy = {
        cell_id: (float(point.x), float(point.y))
        for cell_id, point in zip(cells_projected["cell_id"], cell_centroids)
    }
    destinations_candidates = building_table[
        building_table["use_class"].astype(str).isin(
            ["commercial", "retail", "office", "school", "university", "hotel", "apartments", "yes", "house"]
        )
    ]

    activities = mobility_module.generate_activities(
        sample,
        candidates=destinations_candidates,
        analysis_crs=analysis_crs,
        homes_xy=homes_xy,
        seed=seed,
    )
    activities_path = _write_parquet(context, "activities.parquet", activities)
    register_output(context, "activities", activities_path, rows=len(activities))
    context.record("activities", time.time() - stage_start, rows=len(activities),
                   note=f"source_status=scenario_prior; {len(sample)} sampled agents")

    stage_start = time.time()
    trips = mobility_module.generate_trips(
        activities,
        seed=seed,
        mobility_profiles=sample.set_index("person_id")["mobility_profile"],
    )
    context.record("trips", time.time() - stage_start, rows=len(trips))

    stage_start = time.time()
    walk_graph = mobility_module.build_routing_graph(edges, mobility_module.MODE_WALK)
    car_graph = mobility_module.build_routing_graph(edges, mobility_module.MODE_CAR)
    indices = {
        mobility_module.MODE_WALK: mobility_module.NetworkIndex(walk_graph, analysis_crs),
        mobility_module.MODE_CAR: mobility_module.NetworkIndex(car_graph, analysis_crs),
    }
    trips, waypoints = mobility_module.route_trips(trips, indices)
    trips_path = _write_parquet(context, "trips.parquet", trips)
    register_output(context, "trips", trips_path, rows=len(trips))
    waypoints_path = _write_parquet(context, "waypoints.parquet", waypoints)
    register_output(context, "waypoints", waypoints_path, rows=len(waypoints))
    routed = int((trips["route_status"] == "routed").sum())
    context.record("trajectories", time.time() - stage_start, rows=len(waypoints),
                   note=f"{routed}/{len(trips)} trips routed; no straight-line fallback")

    # ---- P5 aggregates ---------------------------------------------------
    stage_start = time.time()
    mesh_volume = mobility_module.aggregate_mesh_volume(
        activities, trips, analysis_crs=analysis_crs, mesh_size_m=500, time_step_s=600
    )
    mesh_path = _write_parquet(context, "mesh_volume.parquet", mesh_volume)
    register_output(context, "mesh_volume", mesh_path, rows=len(mesh_volume))
    link_volume = mobility_module.aggregate_link_volume(waypoints)
    link_path = _write_parquet(context, "link_volume.parquet", link_volume)
    register_output(context, "link_volume", link_path, rows=len(link_volume))
    context.record("aggregates", time.time() - stage_start, rows=len(mesh_volume) + len(link_volume))

    return _finish_run(
        context=context,
        code_identity=code_identity,
        aoi_frame=aoi_frame,
        aoi_provenance=aoi_provenance,
        persons=persons,
        sample=sample,
        activities=activities,
        trips=trips,
        waypoints=waypoints,
        mesh_volume=mesh_volume,
        link_volume=link_volume,
        edges=edges,
        building_table=building_table,
        indices=indices,
        flood_enabled=flood_enabled,
        sample_cap=limit,
        total_residents=total_residents,
        routed_trips=routed,
        cohort_reference=cohort_reference,
    )


def json_note(payload: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in list(payload.items())[:4])


def _finish_run(
    *,
    context: RunContext,
    code_identity: dict[str, Any],
    aoi_frame: gpd.GeoDataFrame,
    aoi_provenance: dict[str, Any],
    persons: pd.DataFrame,
    sample: pd.DataFrame,
    activities: pd.DataFrame,
    trips: pd.DataFrame,
    waypoints: pd.DataFrame,
    mesh_volume: pd.DataFrame,
    link_volume: pd.DataFrame,
    edges: gpd.GeoDataFrame,
    building_table: gpd.GeoDataFrame,
    indices: dict[int, mobility_module.NetworkIndex],
    flood_enabled: bool,
    sample_cap: int,
    total_residents: float,
    routed_trips: int,
    cohort_reference: dict[str, Any] | None,
) -> dict[str, Any]:
    """Flood, cohort, evacuation, validation and publication."""
    analysis_crs = context.pilot["analysis_crs"]
    scenario_config = context.scenario_config
    population_config = context.population_config
    seed = int(population_config["seed"])

    # ---- F1/F2 flood -----------------------------------------------------
    stage_start = time.time()
    water = gpd.read_parquet(context.input_root / "osm" / "water.parquet")
    flood_config = scenario_config["flood"]
    scenario = flood_module.FloodScenario(
        scenario_id=flood_config["scenario_id"],
        severity=flood_config["severity"] if flood_enabled else "low",
        start_time_s=flood_config["start_time_s"],
        peak_time_s=flood_config["peak_time_s"],
        end_time_s=flood_config["end_time_s"],
        time_step_s=flood_config["time_step_s"],
        observed_source_available=flood_config["observed_source_available"],
        notes=list(flood_config["notes"]),
    )
    if not flood_enabled:
        scenario.severity = "low"
        scenario.peak_depth_m = 0.0
        context.warn("baseline run: flood disabled, used for dry-versus-flooded comparison")
    else:
        context.warn(
            "No terrain elevation model was ingested, so the depth surface is a "
            "distance-to-water decay only. Flooding is therefore confined to a "
            "corridor along canals and the river; low-lying basins away from water "
            "cannot be represented. This is the plan's drainage-blindness risk and "
            "is the highest-value next data acquisition."
        )

    surface = flood_module.build_depth_surface(
        water,
        scenario=scenario,
        analysis_crs=analysis_crs,
        cell_size_m=flood_config["cell_size_m"],
        aoi_geometry=aoi_frame,
    )
    slices = flood_module.build_flood_slices(surface, scenario=scenario)
    slices_path = _write_parquet(context, "flood_slices.parquet", slices)
    register_output(context, "flood_slices", slices_path, rows=len(slices))

    edge_depths = flood_module.sample_edge_depths(edges, surface)
    edge_states = flood_module.build_edge_states(
        edges,
        edge_depths,
        scenario=scenario,
        threshold_set_version=flood_config["threshold_set_version"],
    )
    edge_states_path = _write_parquet(context, "edge_states.parquet", edge_states)
    register_output(context, "edge_states", edge_states_path, rows=len(edge_states))

    exposure = flood_module.build_building_exposure(building_table, surface)
    building_table = building_table.merge(exposure, on="building_id", how="left")
    building_out = building_table.copy()
    building_out["geometry_wkt"] = building_out.geometry.to_wkt()
    buildings_path = _write_parquet(context, "buildings.parquet", building_out.drop(columns="geometry"))
    register_output(context, "buildings", buildings_path, rows=len(building_table), crs=analysis_crs)
    context.record("flood", time.time() - stage_start, rows=len(slices),
                   note=f"source_role=scenario; {len(surface)} depth cells")

    # ---- E1 cohort -------------------------------------------------------
    stage_start = time.time()
    from pyproj import Transformer

    to_analysis = Transformer.from_crs("OGC:CRS84", analysis_crs, always_xy=True)
    people_present = sample.copy()
    if not activities.empty:
        at_time = scenario.start_time_s
        active = activities[
            (activities["start_time_s"] <= at_time) & (activities["end_time_s"] > at_time)
        ]
        present_ids = set(active["person_id"])
        people_present = sample[sample["person_id"].isin(present_ids)].copy()
    people_present["x"], people_present["y"] = to_analysis.transform(
        people_present["lon"].to_numpy(), people_present["lat"].to_numpy()
    )

    # One KD-tree for the whole cohort rather than one query per person.
    from scipy.spatial import cKDTree

    depth_tree = cKDTree(np.column_stack([surface["x"].to_numpy(), surface["y"].to_numpy()])) if len(surface) else None
    surface_depths = surface["peak_depth_m"].to_numpy() if len(surface) else np.array([0.0])

    def depth_at(lon: float, lat: float) -> float:
        # Persons are stored in WGS84; the surface lives in the analysis CRS.
        if depth_tree is None:
            return 0.0
        px, py = to_analysis.transform(lon, lat)
        _, index = depth_tree.query([px, py])
        return float(surface_depths[int(index)])

    # The dry baseline orders the same population as the flooded run; only the
    # water is removed. Using the flood exposure rule for both would make the
    # comparison meaningless, because the dry run would have no cohort at all.
    exposure_threshold = 0.15 if flood_enabled else 0.0
    cohort, cohort_reconciliation, people_present = evacuation_module.select_cohort(
        people_present,
        surface_depth_at=depth_at,
        scenario_time_s=scenario.start_time_s,
        min_depth_m=exposure_threshold,
        aoi_id=context.pilot["aoi"]["aoi_id"],
        seed=seed,
        max_agents=sample_cap,
        sample_persons=sample,
        sampling_probability=min(1.0, sample_cap / len(persons)) if len(persons) else 0.0,
        expected_metadata=cohort_reference,
        return_present=True,
    )
    cohort_reconciliation["run_id"] = context.run_id
    cohort_reconciliation["reference_run_id"] = (
        cohort_reference.get("run_id") if cohort_reference else None
    )
    cohort_path = _write_parquet(context, "cohort.parquet", cohort)
    register_output(context, "cohort", cohort_path, rows=len(cohort))
    cohort_metadata_path = context.run_dir / "cohort_metadata.json"
    write_json(cohort_metadata_path, cohort_reconciliation)
    register_output(context, "cohort_metadata", cohort_metadata_path)
    context.record("cohort", time.time() - stage_start, rows=len(cohort),
                   note=json_note(cohort_reconciliation))

    # ---- E2 evacuation ---------------------------------------------------
    stage_start = time.time()
    evac_config = scenario_config["evacuation"]
    destinations = evacuation_module.build_hypothetical_destinations(
        building_table[building_table["footprint_m2"] > 0],
        analysis_crs=analysis_crs,
        count=evac_config["destination_count"],
        capacity=evac_config["refuge_capacity"],
    )
    refuges_out = destinations.copy()
    refuges_out["geometry_wkt"] = refuges_out.geometry.to_wkt()
    refuges_path = _write_parquet(
        context, "refuges.parquet", refuges_out.drop(columns="geometry")
    )
    register_output(context, "refuges", refuges_path, rows=len(destinations))

    # Build the peak-time walk graph once. Zero multipliers remove closed ways;
    # every open way uses its depth-adjusted speed in the routing cost.
    peak_walk = edge_states[
        (edge_states["time_s"] == scenario.peak_time_s)
        & (edge_states["mode"] == mobility_module.MODE_WALK)
    ]
    if peak_walk["edge_id"].duplicated().any():
        raise ValueError("duplicate peak walking edge state")
    peak_speed_multipliers = dict(
        zip(peak_walk["edge_id"], peak_walk["speed_multiplier"])
    )
    evacuation_index = mobility_module.NetworkIndex(
        mobility_module.build_routing_graph(
            edges,
            mobility_module.MODE_WALK,
            speed_multipliers=peak_speed_multipliers,
        ),
        analysis_crs,
    )

    def route_lookup(lon: float, lat: float, dest_x: float, dest_y: float):
        """Route one person to one destination.

        The person is held in WGS84 (as stored on ``persons``); the destination
        comes from the building table and is already in the analysis CRS. Only
        the person needs transforming.
        """
        px, py = to_analysis.transform(lon, lat)
        origin = evacuation_index.snap(px, py)
        destination = evacuation_index.snap(dest_x, dest_y)
        if origin is None or destination is None:
            return None
        result = evacuation_index.route(origin, destination)
        if result is None:
            return None
        path, cost = result
        used = [
            evacuation_index.graph[path[i]][path[i + 1]]["edge_id"]
            for i in range(len(path) - 1)
        ]
        distance = sum(
            evacuation_index.graph[path[i]][path[i + 1]]["length_m"]
            for i in range(len(path) - 1)
        )
        return float(cost), float(distance), used

    evacuation_scenario = evacuation_module.EvacuationScenario(
        scenario_id=evac_config["scenario_id"],
        warning_time_s=evac_config["warning_time_s"],
        warning_reach=evac_config["warning_reach"],
        compliance=evac_config["compliance"],
        preparation_delay_mean_s=evac_config["preparation_delay_mean_s"],
        preparation_delay_sd_s=evac_config["preparation_delay_sd_s"],
        walk_speed_multiplier=evac_config["walk_speed_multiplier"],
        reduced_mobility_share=evac_config["reduced_mobility_share"],
        refuge_capacity=evac_config["refuge_capacity"],
        destinations=destinations.drop(columns="geometry").to_dict("records"),
        notes=list(evac_config["notes"]),
    )
    states, outcomes = evacuation_module.simulate_evacuation(
        cohort, destinations=destinations, route_lookup=route_lookup,
        scenario=evacuation_scenario, seed=seed,
    )
    denominators = evacuation_module.validate_denominator_contract(
        evacuation_module.build_denominator_contract(
            persons, sample, people_present, cohort, states,
            cohort_identity=cohort_reconciliation,
        )
    )
    denominators_path = context.run_dir / "denominators.json"
    write_json(denominators_path, denominators)
    register_output(context, "denominators", denominators_path)
    states_path = _write_parquet(context, "evacuation_states.parquet", states)
    register_output(context, "evacuation_states", states_path, rows=len(states))
    conservation = denominators["conservation"]
    context.record("evacuation", time.time() - stage_start, rows=len(states),
                   note=json_note(outcomes.get("clearance_time_minutes", {})))

    # ---- V1 validation ---------------------------------------------------
    stage_start = time.time()
    report = validate_module.run_all_checks(
        persons=persons,
        sample=sample,
        activities=activities,
        trips=trips,
        waypoints=waypoints,
        edge_states=edge_states,
        buildings=building_table,
        total_residents=total_residents,
        public_min_cell_m=int(population_config["privacy"]["public_min_cell_metres"]),
        extra={
            "evacuation.conservation": validate_module.Check(
                "evacuation.conservation",
                "every cohort member lands in exactly one terminal state",
                conservation["passed"],
                conservation["absolute_tolerance"],
                conservation["residual_abs"],
            )
        },
    )
    write_json(context.run_dir / "validation.json", report.as_dict())
    context.record("validate", time.time() - stage_start, rows=report.as_dict()["checks_total"],
                   note=f"{report.as_dict()['checks_failed']} failed checks")

    # ---- U1 publish ------------------------------------------------------
    stage_start = time.time()
    if context.named_pilot:
        pilot_stage.validate_staged_pilot(
            context.input_root,
            expected_bundle=load_pilot_bundle(
                context.pilot["aoi"]["aoi_id"],
                config_dir=CONFIG_DIR,
                curated_dir=CURATED_DIR,
            ),
        )
    manifest = manifest_module.build_manifest(
        code_identity=verify_code_identity(code_identity, context.run_dir),
        active_scenario=context.active_scenario,
        run_id=context.run_id,
        geography={
            "country": "Thailand",
            "aoi_id": aoi_provenance["aoi_id"],
            "aoi_version": f"osm-R{aoi_provenance['osm_id']}-{aoi_provenance['retrieved_at'][:10]}",
            "storage_crs": "OGC:CRS84",
            "analysis_crs": analysis_crs,
            "aggregation_geography": "projected_square_grid_100m_internal_1000m_public",
        },
        source_versions=_dedupe_sources(context.source_versions),
        population_model={
            "population_version": population_config["population_version"],
            "method": "weighted-persons",
            "agent_representation": {
                "weight_field": "weight",
                "home_spatial_unit": "100m_grid",
                "households_supported": False,
                "building_assignment": "none",
            },
            "seed": seed,
            "control_source_ids": [
                context.sources["population"],
                context.sources["osm"],
            ],
            "time_profile": {
                "status": "illustrative",
                "activity_model_version": "pflow-bkk-activity-scenario-v0.1",
                "external_trip_policy": "boundary_flows_not_modelled",
            },
            "privacy": {
                "public_min_cell_metres": int(population_config["privacy"]["public_min_cell_metres"]),
                "minimum_reported_count": int(population_config["privacy"]["minimum_reported_count"]),
                "real_trajectories_present": False,
            },
        },
        pflow_components={
            "person_generator": manifest_module.component(
                "bkk-weighted-persons", "0.1.0",
                {
                    "population_version": population_config["population_version"],
                    "seed": seed,
                    "weighted_person_records": int(len(persons)),
                },
            ),
            "activity_generator": manifest_module.component(
                "bkk-scenario-activity-chain", "0.1.0",
                {
                    "status": "scenario_prior_uncalibrated",
                    "sample_cap": int(sample_cap),
                    "sampled_agents": int(len(sample)),
                },
            ),
            "trip_generator": manifest_module.component(
                "bkk-adjacent-activity-trips", "0.1.0",
                {"routed": int(routed_trips), "total": int(len(trips))},
            ),
            "trajectory_generator": manifest_module.component(
                "bkk-astar-osm-graph", "0.1.0",
                {"algorithm": "astar", "network_version": build_stats_network_version(edges)},
            ),
            "aggregation": manifest_module.component(
                "bkk-mesh-link-aggregate", "0.1.0",
                {"mesh_size_m": 500, "time_step_s": 600},
            ),
        },
        flood_scenario_entry=scenario.as_manifest_entry("0.1.0"),
        evacuation_scenario_entry=evacuation_scenario.as_manifest_entry(seed),
        outputs=context.outputs,
        warnings=context.warnings,
        validation_status="demonstration",
    )
    schema_problems = manifest_module.validate_manifest(manifest)
    if schema_problems:
        raise ValueError(
            "Manifest schema validation failed: " + "; ".join(schema_problems)
        )
    manifest_module.verify_output_integrity(context.run_dir, manifest["outputs"])
    write_json(context.run_dir / "manifest.json", manifest)

    stats = _build_stats(
        context=context,
        manifest=manifest,
        outcomes=outcomes,
        denominators=denominators,
        edge_states=edge_states,
        scenario=scenario,
        surface=surface,
        building_table=building_table,
        report=report,
    )
    write_json(context.run_dir / "stats.json", stats)
    context.record("publish", time.time() - stage_start, rows=len(context.outputs))

    verify_code_identity(code_identity, context.run_dir)
    context.write_state("published" if report.passed else "failed_validation")
    return {
        "run_id": context.run_id,
        "run_dir": str(context.run_dir),
        "validation_status": "demonstration",
        "validation_passed": report.passed,
        "checks": report.as_dict()["checks_total"],
        "checks_failed": report.as_dict()["checks_failed"],
        "warnings": len(context.warnings),
        "stats": stats,
    }


def build_stats_network_version(edges: gpd.GeoDataFrame) -> str:
    if "network_version" in edges.columns and len(edges):
        return str(edges["network_version"].iloc[0])
    return "unknown"


def _dedupe_sources(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = f"{entry['source_id']}:{entry['content_sha256']}"
        seen.setdefault(key, entry)
    return list(seen.values())


def _build_stats(
    *,
    context: RunContext,
    manifest: dict[str, Any],
    outcomes: dict[str, Any],
    denominators: dict[str, Any],
    edge_states: pd.DataFrame,
    scenario: flood_module.FloodScenario,
    surface: gpd.GeoDataFrame,
    building_table: gpd.GeoDataFrame,
    report: validate_module.ValidationReport,
) -> dict[str, Any]:
    """Assemble the API-facing statistics payload from the contract."""
    peak_states = edge_states[
        (edge_states["time_s"] == scenario.peak_time_s) & (edge_states["mode"] == mobility_module.MODE_WALK)
    ]
    total_edges = int(edge_states["edge_id"].nunique())
    closed_edges = int(peak_states[peak_states["closed"]]["edge_id"].nunique())
    average_factor = float(peak_states["speed_multiplier"].mean()) if not peak_states.empty else 1.0
    flooded_buildings = int(building_table["flooded"].sum()) if "flooded" in building_table else 0

    flooded_cells = surface[surface["peak_depth_m"] >= 0.15] if len(surface) else surface
    cell_area = float(context.scenario_config["flood"]["cell_size_m"]) ** 2
    return {
        "run_id": context.run_id,
        "validation_status": manifest["validation_status"],
        "created_at": manifest["created_at"],
        "geography": {
            "aoi_id": manifest["geography"]["aoi_id"],
            "name": context.pilot["aoi"]["name_en"],
            "area_km2": context.pilot["aoi"]["area_km2"],
            "analysis_crs": manifest["geography"]["analysis_crs"],
        },
        "population": {
            "residents_weighted": denominators["quantities"]["full_population"]["weight"],
            "people_present": denominators["quantities"]["present"]["weight"],
            "people_exposed": denominators["quantities"]["exposed_present"]["weight"],
            "exposed_share_of_present": denominators["shares"]["exposed_of_present"],
            "population_version": manifest["population_model"]["population_version"],
            "time_profile": context.scenario_config.get("analysis_time_of_day", "evening"),
        },
        "flood": {
            "max_depth_m": round(float(surface["peak_depth_m"].max()) if len(surface) else 0.0, 4),
            "flooded_area_km2": round(
                float(len(flooded_cells) * cell_area / 1e6), 4
            ),
            "flooded_area_basis": "50 m scenario cells at or above 0.15 m peak depth",
            "edges_closed": closed_edges,
            "edges_total": total_edges,
            "road_capacity_loss_share": round(1.0 - average_factor, 6),
            "flooded_buildings": flooded_buildings,
            "source_role": "scenario",
            "model": {
                "name": manifest["flood_scenario"]["model_name"],
                "version": manifest["flood_scenario"]["model_version"],
            },
        },
        "evacuation": {
            "cohort_weighted": denominators["quantities"]["cohort"]["weight"],
            "arrived_weighted": denominators["quantities"]["terminal_states"]["arrived"]["weight"],
            "unserved_weighted": denominators["unserved_derived"]["weight"],
            "clearance_time_minutes": outcomes["clearance_time_minutes"],
            "state_distribution": {
                state: values["weight"]
                for state, values in denominators["quantities"]["terminal_states"].items()
            },
            "top_bottleneck_edges": outcomes["top_bottleneck_edges"],
            "destinations": outcomes["destinations"],
        },
        "denominators": denominators,
        "stages": context.stages,
        "validation": {
            "passed": report.passed,
            "checks_total": report.as_dict()["checks_total"],
            "checks_failed": report.as_dict()["checks_failed"],
        },
        "warnings": context.warnings,
        "sources": [
            {
                "source_id": entry["source_id"],
                "licence": entry["licence_snapshot"].split(" (c)", 1)[0],
                "status": "approved",
            }
            for entry in manifest["source_versions"]
        ],
    }
