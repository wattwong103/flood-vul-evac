# BKK/FLOW — product and implementation plan

> The expanded population, PFLOW, architecture, API, validation, privacy, scale and delivery specification is in [`docs/FULL_IMPLEMENTATION_PLAN.md`](docs/FULL_IMPLEMENTATION_PLAN.md).

## 1. Product thesis

BKK/FLOW should answer one practical question:

> Under a defined flood scenario, where can people still move, which buildings and roads are exposed, and how long could evacuation take?

The product combines four things that are usually shown separately:

1. observed or modelled flood extent and depth;
2. a routable Bangkok street and pedestrian network;
3. building presence and height;
4. agent-based evacuation and congestion.

The first audience is researchers, urban planners, civil-society groups, and local agencies doing scenario analysis. It must not present itself as a public warning service until the model, data latency, operating procedures, and institutional ownership have been validated.

### Confirmed PFLOW reference

The local Obsidian vault and `H:\Dropbox\PFLOW` workspace establish that PFLOW is a synthetic transport/activity model, not a generic pedestrian crowd engine. Its reusable contract is:

`PersonGenerator → ActivityGenerator → TripGenerator → TrajectoryGenerator → MeshVolumeCalculator → LinkVolumeCalculator`.

BKK/FLOW will preserve those stage boundaries and compatible activity/trip/trajectory outputs. It will replace Japan-specific census, mesh, behavioural and routing assumptions with Bangkok-native open inputs and a new validation contract, then add flood state, building exposure, refuge eligibility and evacuation response. See `docs/PFLOW_BANGKOK_INTEGRATION.md`.

## 2. The first useful release

### Core user journey

1. Choose a historical event or compose a scenario from rainfall, river stage, tide, and evacuation start time.
2. Inspect observed flood extent and predicted depth separately.
3. Turn building height, population, road closure, and route layers on or off.
4. Select an origin area and one or more **verified** safe destinations.
5. Run an evacuation simulation.
6. Compare clearance time, exposed population, road-capacity loss, inaccessible destinations, and bottleneck locations.
7. Export the scenario manifest and results with full data provenance.

### MVP screens

- **Scenario Lab** — inputs, map, simulation clock, route animation, and outcome metrics.
- **Data Registry** — source, agency, endpoint, format, resolution, access, licence, attribution, and approval state.
- **Method** — plain-language pipeline, assumptions, uncertainty, and validation status.
- **Scenario Compare** — side-by-side baseline versus intervention; add after the single-scenario pipeline is real.
- **Run Detail** — immutable input versions, parameters, logs, outputs, and downloadable files; add with the backend.

The current prototype implements the first three screens with illustrative values.

## 3. Data policy

A source passes only when it is:

- accessible to anyone, with public registration allowed; and
- accompanied by explicit reuse permission.

Registry states:

- **Approved** — accessible and explicitly reusable.
- **Verify** — public, but licence or access terms are not sufficiently clear.
- **Rejected** — proprietary, scraped, partner-only, or otherwise restricted.

Licence approval is per dataset/resource, not per agency or domain. A licensed GISTDA resource does not automatically approve every GISTDA service.

### Initial registry

| Model role | Preferred source | Licence state | MVP use |
|---|---|---:|---|
| Observed flood extent | GISTDA 1-day flood extent JSON API | Approved: Open Data Common | Event footprint and calibration |
| Independent water observation | Copernicus Sentinel-1 via CDSE STAC | Approved: free, full, open | SAR water classification |
| Rainfall forcing | Thai Meteorological Department or another open provider | Verify per resource: current general TMD terms restrict reuse | Excluded until a resource passes the open-data gate |
| Roads and paths | OpenStreetMap regional extract | Approved: ODbL 1.0 | PostGIS/pgRouting network |
| Buildings and tagged levels | OpenStreetMap | Approved: ODbL 1.0 | Footprints and direct height tags |
| Building presence and height | Google Open Buildings 2.5D | Approved: CC BY 4.0 or ODbL 1.0 | 4 m raster height estimate; locally validate |
| Population | WorldPop | Approved: CC BY 4.0 | Population-at-risk and agent seeding |
| Known flood-risk/watch locations | BMA open-data CSV | Approved: CC Attribution | Qualitative hotspot checks; not precise points unless coordinates validate |
| Five-minute water levels | BMA data API | Verify: licence unspecified | Do not ingest until resolved |

### Required registry fields

`source_id`, `agency`, `dataset`, `resource_url`, `format`, `spatial_resolution`, `temporal_resolution`, `live_or_historical`, `authentication`, `licence`, `licence_url`, `attribution`, `rate_limit`, `archive_available`, `status`, `reviewed_at`, `reviewer`, `notes`.

For every ingestion, save the source checksum, retrieval timestamp, request parameters, source metadata, and a licence snapshot or licence version.

## 4. Scientific and technical pipeline

```text
Open source registry
        ↓
Versioned ingestion → raw object store / STAC catalogue
        ↓
Geospatial normalization → PostGIS + Cloud-Optimized GeoTIFFs
        ↓
Flood observation + depth model
        ↓
Depth-by-road + depth-by-building exposure
        ↓
Dynamic multimodal graph
        ↓
Evacuation engine
        ↓
Scenario API + vector/raster tiles + reproducible run manifest
        ↓
BKK/FLOW web application
```

### 4.1 Flood observation

Use GISTDA flood extent as a direct observation layer when the explicitly licensed endpoint covers the event. Independently process Sentinel-1 SAR to create a reproducible water mask:

1. query Bangkok scenes from the Copernicus STAC catalogue;
2. orbit correction/calibration and terrain correction;
3. speckle-aware preprocessing;
4. permanent-water and layover/shadow masking;
5. threshold or supervised water classification;
6. connected-component cleanup;
7. publish mask, acquisition time, confidence, and algorithm version.

Observed extent is not depth.

### 4.2 Flood depth

Implement in two tracks:

- **Research benchmark:** an open 2D shallow-water or rapid-inundation solver, selected only after a licence and Bangkok-input audit.
- **Interactive surrogate:** a fast model calibrated to benchmark runs so the web interface can respond in seconds.

Minimum boundary conditions are rainfall hyetograph, river/tide level, terrain, roughness, and an explicit representation of drainage capacity. Bangkok’s canals, pumps, gates, and drainage network are major determinants; if open and licensed operational data are not available, treat them as scenario assumptions and show the limitation.

For each pixel or mesh cell, publish `depth_m(x,t)`, `velocity_mps(x,t)`, `confidence`, and `model_run_id`.

### 4.3 Building height and exposure

Create a building table with:

- footprint geometry;
- observed OSM `height` or `building:levels` when present;
- Open Buildings 2.5D raster summary (median, p90, valid-pixel share);
- estimated height source and confidence;
- maximum modelled flood depth at the footprint;
- road and entrance connectivity;
- verified-refuge status, capacity, accessibility, and operator.

Precedence should be measured/open authoritative height, then explicit OSM height, then locally calibrated remote-sensing estimate. Never silently convert building height into “safe shelter.” Vertical evacuation requires a separately verified destination record.

### 4.4 Road disruption

For each network edge and time step, sample flood depth and velocity. Apply a transparent mode-specific impedance curve:

```text
effective_speed(edge, mode, t)
  = dry_speed(edge, mode)
  × depth_factor(depth, mode)
  × congestion_factor(flow / capacity)
```

An edge closes when depth, velocity, bridge status, or access rules exceed the selected mode’s threshold. Keep walking, wheelchair, motorcycle, car, bus, and emergency-vehicle thresholds separate. Thresholds must be cited and configurable.

### 4.5 Evacuation engine

Use two levels of model fidelity:

- **City scale:** network-based agents on a dynamic graph; route replanning, departure delay, household grouping, mobility classes, and destination capacity.
- **Bottleneck scale:** a pedestrian engine such as JuPedSim for selected terminals, bridges, stations, corridors, or refuge-building approaches.

Do not run a microscopic pedestrian solver across all Bangkok. Use it where density interactions matter, and use graph agents elsewhere.

### 4.6 PFLOW compatibility layer

The Bangkok implementation must keep PFLOW's semantic sequence—people, activities, trips, trajectories, mesh volumes and link volumes—while treating Japan-specific parameters as non-transferable. A compatibility adapter will map Bangkok-native tables into PFLOW-shaped records and add versioned flood/exposure fields. Each run records component versions, seeds, source hashes and warnings through `schemas/pflow-bkk-run.schema.json`.

The existing PFLOW people model has no archived ground-truth validation suite in the current project record. Therefore “PFLOW-compatible” means contract compatibility, not inherited behavioural validity.

Important inputs:

- population distribution by time of day;
- origin zones and departure-time distribution;
- walking/driving speed distribution;
- reduced-mobility share and assistance requirements;
- route knowledge and compliance;
- vehicle availability and occupancy;
- destination opening time, verified capacity, and accessibility;
- road and transit closures over time.

Important outputs:

- clearance-time distribution, not only an average;
- unserved or trapped population;
- arrivals by destination and capacity overflow;
- edge density/flow and bottleneck duration;
- exposure time by flood-depth band;
- route stability when assumptions change;
- uncertainty intervals across repeated stochastic runs.

## 5. Software architecture

### Web application

- React + TypeScript.
- MapLibre GL for the production map, using self-hosted/openly licensed tiles.
- deck.gl or custom WebGL layers for large agent traces and building extrusion.
- Scenario state encoded in a shareable manifest, not only browser state.
- Accessibility: keyboard controls, non-colour map encodings, reduced-motion mode, and table equivalents for map results.

### Services

- Python/FastAPI scenario and catalogue API.
- PostgreSQL/PostGIS for spatial entities and metadata.
- pgRouting or a versioned graph service for network analysis.
- Object storage for COGs, GeoParquet, run manifests, and result archives.
- Background workers for ingestion, satellite processing, flood runs, and evacuation ensembles.
- PMTiles/MVT for vector delivery; COG/TiTiler-style raster access for flood results.

### Reproducible run contract

Every run should produce:

```json
{
  "run_id": "uuid",
  "created_at": "ISO-8601",
  "area_of_interest": "geometry/version",
  "source_versions": [],
  "licence_registry_version": "git sha",
  "flood_model": { "name": "", "version": "", "parameters": {} },
  "network_version": "",
  "evacuation_model": { "name": "", "version": "", "seed": 0, "parameters": {} },
  "outputs": [],
  "warnings": [],
  "validation_status": "demonstration|research|reviewed|operational"
}
```

## 6. Delivery roadmap

### Phase 0 — truth, scope, and governance (2 weeks)

- confirm one Bangkok pilot area and two historical events;
- decide the intended user and decision, not just the visualization;
- complete the data-source registry and attribution rules;
- define observed, predicted, and scenario visual language;
- agree “not for emergency use” wording and escalation ownership;
- identify local validation partners.

**Exit:** approved source registry, pilot boundary, event list, and signed model-purpose statement.

### Phase 1 — open-data city baseline (3–4 weeks)

- import a dated OSM extract into PostGIS;
- build walking and vehicle graphs with QA reports;
- ingest Open Buildings 2.5D and WorldPop for the pilot area;
- calculate building-height coverage and uncertainty;
- add BMA risk/watch points and versioned source metadata;
- replace the prototype SVG with MapLibre and real pilot geometries.

**Exit:** reproducible city baseline, map tiles, source attribution, and coverage dashboard.

### Phase 2 — observed flood and depth benchmark (5–7 weeks)

- connect the explicitly licensed GISTDA endpoint;
- build Sentinel-1 flood-mask processing;
- select and configure the open flood solver;
- build two historical-event benchmarks;
- quantify extent and depth error;
- expose flood result tiles with uncertainty and acquisition time.

**Exit:** historical flood runs reproduce known extents within agreed metrics; no “live” label.

### Phase 3 — dynamic routing and evacuation (5–7 weeks)

- define mode-specific flood impedance and closure curves;
- implement time-varying graph routing;
- seed agents from population/origin zones;
- add destination capacity and verified-refuge records;
- run ensembles with fixed random seeds and export manifests;
- use JuPedSim for one selected bottleneck if needed.

**Exit:** repeatable scenario results, sensitivity report, and traceable clearance-time distributions.

### Phase 4 — pilot validation and hardening (4–6 weeks)

- local review of building height, routes, closures, and destinations;
- compare simulated movement with drills, surveys, or historical traces that pass the data policy;
- usability and accessibility testing in English and Thai;
- performance, security, backup, and observability work;
- operational-readiness decision with explicit go/no-go criteria.

**Exit:** reviewed research pilot. Operational deployment is a separate approval.

## 7. MVP acceptance criteria

The first data-backed pilot is complete when:

- every visible data layer resolves to an approved registry entry and attribution;
- the map distinguishes observation time, model time, and scenario time;
- changing rainfall/river/tide produces a new immutable run, not cosmetic UI changes;
- roads close or slow according to published, mode-specific curves;
- destinations are verified records with capacities or clearly marked hypothetical;
- the same manifest and random seed reproduce the same outputs;
- result downloads include source/model versions and warnings;
- the interface works on desktop and mobile and provides non-map result access;
- at least two historical Bangkok events have documented validation scores;
- no operational or public-safety claim appears without the corresponding review state.

## 8. Validation metrics

### Flood

- intersection-over-union, precision, and recall for extent;
- depth MAE/RMSE and bias where observations exist;
- critical success index by district;
- latency from acquisition to published observation.

### Network

- topology errors and disconnected population share;
- route plausibility from local expert review;
- closure sensitivity by depth threshold;
- runtime at city and pilot-area scales.

### Evacuation

- clearance time median and 5th/95th percentiles;
- trapped/unserved population;
- destination overflow;
- maximum and sustained bottleneck density;
- sensitivity to departure delay, compliance, mobility, capacity, and flood uncertainty.

## 9. Risks to manage early

1. **Drainage blindness:** surface rainfall and river stage alone may misrepresent Bangkok flooding.
2. **Height false precision:** remote-sensing height is an estimate, not a surveyed building model.
3. **Shelter inference:** a tall building may be inaccessible, structurally unsuitable, closed, or full.
4. **Population timing:** residential population is not daytime population.
5. **Behavioural certainty:** evacuation decisions are social and institutional, not only shortest-path choices.
6. **Licence drift:** dataset pages and terms change; snapshot and re-review them.
7. **Latency:** satellite observations arrive after acquisition and processing; show timestamps prominently.
8. **Misuse:** users may treat a polished research map as authoritative. Persistent labels and downloadable caveats are required.

## 10. Immediate next build slice

The next engineering milestone should be a single real pilot corridor, not all Bangkok:

1. choose a 5–10 km² area with known flood risk and useful building-height variation;
2. import real OSM roads/buildings and Open Buildings height tiles;
3. replay one documented flood event from GISTDA/Sentinel-1;
4. define 2–3 hypothetical destinations, visibly labelled as such;
5. run one walking-only dynamic graph simulation;
6. compare dry versus flooded clearance time;
7. publish the full source and run manifest in the UI.

That slice tests the scientific and product spine before scaling data volume, modes, or geography.
