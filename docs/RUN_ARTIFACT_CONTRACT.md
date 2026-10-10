# BKK/FLOW run artefact and API contract

**Contract version:** `bkkflow-run-v0.1`
**Status:** frozen for the pilot prototype
**Applies to:** every run directory and every API response

This document is the agreement between the Python pipeline, the FastAPI service
and the website. It exists so those three can be built against one specification
instead of against each other.

## 1. Run directory layout

```text
runs/<run_id>/
  manifest.json          # conforms to schemas/pflow-bkk-run.schema.json
  run_state.json         # stage, progress, warnings, timings
  validation.json        # every check with its threshold and result
  stats.json             # API-friendly aggregate metrics
  population_qa.json     # population diagnostics
  persons.parquet
  activities.parquet
  trips.parquet
  waypoints.parquet
  mesh_volume.parquet
  link_volume.parquet
  network_edges.parquet
  flood_slices.parquet
  edge_states.parquet
  buildings.parquet
  refuges.parquet
  evacuation_states.parquet
  scenarios/baseline/    # dry comparison run
  report/                # generated figures and markdown summary
```

`run_id` is a UUID4 string. Every artefact is immutable once written; a changed
input produces a new `run_id`, never an edited file.

New pilot and city manifests include `code_identity`: Git commit/tree, scoped
working-tree status, a SHA-256 over source paths and bytes, file count and
verification status. Legacy manifests without this field remain readable and
must not be retrospectively described as source-pinned. Without Git, commit and
tree are null and status is `unavailable`; a dirty checkout is explicit.

Source/configuration bytes are checked before execution and again before
publication. Detected drift writes `failed_source_changed` and refuses publication.
This is not process isolation: a transient edit restored between checks is not
detected, and installed dependencies are not frozen by the digest. Release runs
must use a quiescent checkout and record their environment separately.

New manifests also record `population_model.age_structure.coverage`: occupied
cell counts, population weights and covered/unknown shares. The block is
optional so manifests created before the coverage extension remain readable.
For per-cell inputs, `band_shares` uses the
`population_weighted_over_covered_cells` basis and is conditional on that
reported coverage.

## 2. Validation status vocabulary

`demonstration | research | reviewed | operational`

A run starts and, in the pilot, stays at `demonstration`. The API must expose
this value verbatim and the site must display it. It is never inferred from
polish, latency or how good the numbers look.

## 3. Table contracts

### persons.parquet
| column | type | notes |
|---|---|---|
| `person_id` | string | run-scoped synthetic id, never a source key |
| `population_version` | string | immutable synthesis version |
| `weight` | float | people represented by this record |
| `age_band` | string | `unknown` when age structure is absent or the admitted source has no valid value at the home cell |
| `sex_code` | string | `M` / `F` / `unknown` |
| `home_cell_id` | string | 100 m base cell |
| `home_building_id` | string \| null | null when evidence is insufficient |
| `mobility_profile` | string | scenario class with provenance |
| `lon`, `lat` | float | WGS84 |
| `sampled` | bool | true when the row is a mobility sample |

### activities.parquet
`person_id, sequence, purpose, start_time_s, duration_s, lon, lat, gcode, source_status`

`purpose` ∈ `home, work, education, shopping_services, health_care,
social_recreation, transfer, evacuation, unknown`.
`source_status` is `scenario_prior` unless a licensable diary was used.

### trips.parquet
`trip_id, person_id, seq, origin_activity, dest_activity, mode, depart_time_s,
arrive_time_s, duration_s, distance_m, route_status, failure_reason`
`mode` uses PFLOW-compatible codes: `0 walk, 1 bicycle, 2 bus, 3 car, 4 train`.
`route_status` ∈ `routed, unroutable, straight_line_fallback`.

### waypoints.parquet
`trip_id, seq, lon, lat, edge_id, cumulative_time_s`

### mesh_volume.parquet
`run_id, gcode, mesh_size_m, time_s, stationary_pop, travelling_pop, total_pop`

### link_volume.parquet
`run_id, edge_id, hour, volume, mode, distance_m`

### network_edges.parquet
`edge_id, u, v, length_m, highway, walk_allowed, vehicle_allowed,
speed_walk_mps, speed_vehicle_mps, geometry_wkt`

### flood_slices.parquet
`time_s, cell_id, depth_m, source_role, confidence`
`source_role` ∈ `observed, modelled, scenario`.

### edge_states.parquet
`edge_id, time_s, mode, depth_m, speed_multiplier, capacity_multiplier,
closed, threshold_set_version, reason_code`

### evacuation_states.parquet
`person_id, state, reason, event_time_s, weight, dest_id`
`state` follows the plan's machine:
`not_eligible, exposed, warned, deciding, departed, en_route, arrived,
stranded, shelter_full, route_failed, did_not_depart`.

## 4. Statistics payload (`stats.json` and `GET /v1/runs/{id}/stats`)

```json
{
  "run_id": "uuid",
  "validation_status": "demonstration",
  "created_at": "ISO-8601",
  "geography": { "aoi_id": "", "name": "", "area_km2": 0.0, "analysis_crs": "EPSG:32647" },
  "population": {
    "residents_weighted": 0.0,
    "people_present": 0.0,
    "people_exposed": 0.0,
    "exposed_share_of_present": 0.0,
    "population_version": "",
    "time_profile": "day|evening|night"
  },
  "flood": {
    "max_depth_m": 0.0,
    "flooded_area_km2": 0.0,
    "edges_closed": 0,
    "edges_total": 0,
    "road_capacity_loss_share": 0.0,
    "source_role": "scenario",
    "model": { "name": "", "version": "" }
  },
  "evacuation": {
    "cohort_weighted": 0.0,
    "arrived_weighted": 0.0,
    "unserved_weighted": 0.0,
    "clearance_time_minutes": { "p5": 0.0, "median": 0.0, "p95": 0.0 },
    "top_bottleneck_edges": []
  },
  "stages": [ { "stage": "population", "status": "completed", "seconds": 0.0, "rows": 0 } ],
  "warnings": [],
  "sources": [ { "source_id": "", "licence": "", "status": "" } ]
}
```

Rules the API must not break:

- `people_present` and `people_exposed` are different quantities and are never
  summed into a single "affected people" number.
- `validation_status` is copied from the manifest, never recomputed.
- An empty or missing run returns HTTP 404 with a JSON error body, never an
  empty object that looks like a result of zero.

## 5. Minimum API surface

| Method and path | Purpose |
|---|---|
| `GET /v1/health` | liveness and version |
| `GET /v1/sources` | registry with licence status |
| `GET /v1/runs` | list runs, newest first |
| `GET /v1/runs/{id}` | stage, progress, warnings, manifest |
| `GET /v1/runs/{id}/stats` | the `stats.json` payload above |
| `GET /v1/runs/{id}/mesh?time=` | mesh time slice |
| `GET /v1/runs/{id}/flood?time=&limit=` | positive-depth flood cells for one model time, with source role and coverage-sampling metadata |
| `GET /v1/runs/{id}/links?time=&mode=` | edge states and volume |
| `GET /v1/runs/{id}/buildings` | aggregated exposure |
| `GET /v1/runs/{id}/evacuation` | clearance distribution and states |
| `GET /v1/runs/{id}/routes` | aggregate top evacuation bottleneck edges; never person trajectories |
| `GET /v1/runs/{id}/validation` | checks, thresholds, results |
| `GET /v1/runs/{id}/export` | manifest and artefact bundle |
| `GET /v1/config` | pilot area, CRS, and declared scenario status |
| `GET /v1/areas/bangkok` | full BMA administrative boundary used as the map frame, independent of run scope |

CORS must allow the Vite dev origin. No endpoint may return a full person-level
trajectory set; a single trip lookup is the finest granularity allowed.

## 6. Website contract

The site reads only from this API. It must:

1. label every numeric result with `validation_status` and the model time;
2. keep observed, modelled and scenario flood visually distinct;
3. name which population quantity each map layer represents;
4. frame maps with the full Bangkok boundary while clearly stating when a selected run covers only a pilot area;
5. show the PFLOW stage rail with per-stage row counts;
6. offer a non-map table view for every map result;
7. never describe the product as a warning or routing service.

## 7. City-run additions

City runs publish layers a pilot run does not have. Each is optional: a client
must render a clean empty state, never a fabricated zero.

- **population_grid_1km.parquet** - the resident baseline on the fixed 1 km
  public grid. Aggregated by summing, so the total is preserved exactly. The
  population field is `pop`, not `total_pop`.
- **observed_water.json** and **observed_water_cells.parquet** - the only
  observational hazard layer in the project. **Extent, never depth.** A yearly
  Landsat composite cannot resolve within-year timing and under-detects
  short-lived flooding, so every year is a lower bound. The 2011 Bangkok flood
  is absent from the record; that absence is the product behaving as documented.
- **destinations.parquet** - destination candidates recovered from OSM tags.
  Every record is `verified=false` with no operator, capacity or inspection
  date. `verified_count` is reported at payload level so a client cannot
  present a shelter tag as a refuge by omission.

For city runs stats.flood splits into depth_status / depth_reason (with
max_depth_m and edges_closed **null**) and observed_extent. Pilot runs
still carry the earlier flat shape, so clients must read both.
