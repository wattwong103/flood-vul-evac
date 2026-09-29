# PFLOW → Bangkok flood evacuation integration

## Decision

Use a **hybrid PFLOW adapter**.

- Preserve PFLOW's canonical research contract: synthetic people → activities → trips → trajectories → mesh/link aggregates.
- Replace Japan-specific source data, spatial indexing, behavioural parameters and routing services with Bangkok-native, openly licensed inputs and explicitly calibrated models.
- Add flood state, building exposure, refuge eligibility, time-varying edge impedance and evacuation outcomes as versioned extensions.
- Keep the existing Java PFLOW workspace unchanged until a bounded implementation task and comparison plan are approved.

This decision is grounded in the local PFLOW vault and project state, especially `pflow-overview`, `pflow-pipeline`, `people-flow-webapi-pipeline`, `people-flow-reality-gap-analysis`, and `PFLOW/STATE.md`, reviewed 2026-09-29.

## Why this is not a straight Bangkok port

The current people-flow pipeline is coupled to Japanese population inputs, Japanese mesh conventions, historical activity-transition and mode-choice parameters, and a Japan-oriented Web API route generator. The project record also says the people-flow side lacks an archived ground-truth validation suite comparable to the truck and taxi modules.

Copying that implementation and changing the map would create false comparability. Bangkok needs a new calibration and validation contract even when the file schemas and stage boundaries remain compatible.

## Canonical PFLOW contract to retain

| PFLOW stage | Bangkok adapter | Required evidence |
|---|---|---|
| `PersonGenerator` | Generate weighted synthetic people from open gridded population plus approved demographic marginals | Population totals, age/sex/household constraints, synthesis error |
| `ActivityGenerator` | Generate daily activity chains with Bangkok-calibrated transition and duration models | Household travel survey or another openly reusable behavioural source |
| `TripGenerator` | Convert activities to trips and select a mode | Bangkok mode-choice evidence and scenario assumptions |
| `TrajectoryGenerator` / Web API route | Route trips on a dated OSM graph | Network QA, mode permissions, route plausibility |
| `MeshVolumeCalculator` | Aggregate time-varying population to an explicit Bangkok analysis grid | Selected analysis CRS/grid and aggregation tests |
| `LinkVolumeCalculator` | Aggregate traversals, density and capacity use by link/time | Link mapping, time-window and direction rules |

The compatibility target is semantic and schema-level. It does not require reusing Japan-specific coefficients.

## Bangkok extensions

### 1. Flood-state service

For every model time step, publish flood `extent`, `depth_m`, optional `velocity_mps`, observation/model timestamps, uncertainty and run identifier. GISTDA and Sentinel-1 are observation inputs; they do not by themselves provide a citywide depth field.

### 2. Dynamic network intervention

Join flood state to each network edge in a justified projected CRS. Compute mode-specific speed and capacity multipliers and an explicit closure state. Persist the original dry edge, sampled hazard, threshold source and final impedance so every route decision can be audited.

### 3. Building exposure and vertical refuge

Attach footprint, estimated height, flood depth, entrance connectivity and provenance to each building. Building height is an exposure variable. A building becomes a destination only through a separate verified-refuge record containing operator, opening conditions, accessible entrance, usable floor, capacity and review status.

### 4. Evacuation decision layer

Add warning receipt, departure delay, household grouping, assistance need, destination choice, route replanning and non-compliance as explicit scenario parameters. Keep stochastic seeds in the run manifest. Do not infer these parameters from Japan-side PFLOW defaults.

### 5. Extended outputs

Alongside PFLOW-compatible activity, trip, trajectory, mesh-volume and link-volume outputs, produce:

- person-level exposure time by depth band, released only under privacy-safe aggregation;
- edge closure, capacity loss and bottleneck duration by time step;
- building exposure and verified-refuge occupancy;
- arrival, unserved, trapped and rerouted counts;
- clearance-time distributions across repeated runs;
- source, model and parameter provenance plus validation warnings.

## Spatial decisions that remain open

Country is fixed as **Thailand**. Storage should use `OGC:CRS84` for interoperable longitude/latitude exchange. No measurement CRS or aggregation grid has been silently selected.

Recommended candidate:

- analysis CRS: WGS 84 / UTM zone 47N (`EPSG:32647`) for the Bangkok pilot;
- analytical grid: metric square cells for PFLOW-style population/volume comparison, with BMA district summaries as a reporting layer.

Strongest counterargument: official Bangkok layers may use a different datum or local coordinate reference system, and UTM-zone transformations can hide datum or accuracy problems. The first staged layer must therefore be inventoried before this candidate is approved.

Alternative aggregation choices:

1. H3 for portable multiscale web aggregation; cell area/shape and transport-analysis interpretation are less intuitive.
2. A projected square grid for reproducible metric distance and area; it requires an approved analysis CRS and origin.
3. BMA districts for policy communication; they are too coarse and heterogeneous for network and evacuation calibration.

## Minimum schemas

### Activity record

`person_id, age_band, sex, labour_status, start_time, duration, purpose_id, lon, lat, zone_id, weight`

### Trip record

`person_id, trip_id, origin_activity_id, destination_activity_id, departure_time, arrival_time, mode, purpose, distance_m, route_status`

### Trajectory waypoint

`person_id, trip_id, sequence, timestamp, lon, lat, link_id, mode, flood_depth_m, speed_mps`

Exact coordinates and individual trajectories are sensitive. Public outputs must use coarse aggregates, minimum-count suppression and redacted identifiers.

## Validation gates

1. **Synthetic population:** fit to all target marginals; report absolute and relative errors by geography.
2. **Activities and trips:** compare trip rate, purpose, duration, departure time, distance and mode shares with held-out Bangkok evidence.
3. **Network:** audit disconnected population, forbidden modes, topology defects and route plausibility.
4. **Flood:** validate extent against held-out observations and depth where local measurements are licensed and available.
5. **Building height:** compare Open Buildings 2.5D with a representative local sample; do not transfer the published non-Thailand error as Bangkok accuracy.
6. **Evacuation:** test mass balance, destination capacity, deterministic replay, sensitivity and uncertainty before any behavioural-validity claim.

## First implementation slice

1. Freeze a pilot AOI and analysis CRS through an explicit decision record.
2. Stage the licensed BMA flood-risk CSV and a dated OSM extract; record hashes and metadata.
3. Build dry walking/vehicle graphs and publish a topology audit.
4. Stage WorldPop and Open Buildings 2.5D for the AOI.
5. Create PFLOW-compatible synthetic-person, trip and trajectory fixtures.
6. Intersect one historical flood observation with roads and buildings.
7. Replay a walking-only evacuation with hypothetical destinations labelled as such.
8. Export the run manifest defined by `schemas/pflow-bkk-run.schema.json`.
