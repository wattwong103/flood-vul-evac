# BKK/FLOW — full population, PFLOW and flood-evacuation implementation plan

**Plan version:** 0.2  
**Planning date:** 29 September 2026  
**Product status:** research prototype  
**Geographic scope:** one Bangkok pilot area first, then the Bangkok Metropolitan Administration area  
**Data rule:** every core input must be publicly accessible and carry explicit permission for reuse

## 1. Executive decision

BKK/FLOW should be built as a reproducible research platform with three connected models, not as a single opaque simulator:

1. **Bangkok population model** — estimates residents, demographic groups, synthetic people and time-of-day presence.
2. **PFLOW-compatible mobility model** — creates activities, trips, trajectories, 10-minute mesh volumes and hourly link volumes.
3. **Flood-evacuation model** — overlays time-varying flood constraints, building exposure and verified refuge options on the mobility network.

The first release should be a **weighted-person model**, not a synthetic-household model. It can represent age, sex, home location, activity state and mobility mode from open aggregate data without inventing household relationships that cannot yet be supported. Household membership, vehicle ownership, disability and evacuation assistance should remain explicit scenario variables until a reusable Bangkok source or approved microdata agreement exists.

The website is the review surface for this system. It must always distinguish:

- observed data from modelled data;
- resident population from people present at a particular time;
- exposed people from people instructed or able to evacuate;
- PFLOW file compatibility from Bangkok behavioural validity;
- a tall building from a verified refuge.

This makes the prototype useful for urban-research questions now, while preventing it from presenting demonstration assumptions as an emergency warning service.

## 2. Outcomes and non-goals

### 2.1 Outcomes

The platform should let an analyst:

- select a Bangkok pilot area and time of day;
- select or construct a rainfall, river and tide scenario;
- inspect source versions and licences before a run;
- generate or load a reproducible synthetic population;
- run the PFLOW-compatible people → activities → trips → trajectories pipeline;
- apply flood depth and closure rules to roads, paths and buildings;
- choose warning, departure, mobility and refuge assumptions;
- compare dry, flooded and evacuation outcomes;
- inspect population present, population exposed, unserved agents, clearance time, route failure and building exposure;
- export a run manifest, aggregate tables, maps and uncertainty report.

### 2.2 Explicit non-goals for the first release

- It is not a live emergency alert or public routing service.
- It will not publish real individual traces or infer identities.
- It will not label a building as a shelter based on height alone.
- It will not claim real-time population without a separately licensed and validated feed.
- It will not transfer Japanese PFLOW behaviour parameters to Bangkok without calibration.
- It will not claim street-level accuracy where flood depth, road access or population evidence is unresolved.

## 3. Product requirements

### 3.1 Functional requirements

| ID | Requirement | Acceptance signal |
|---|---|---|
| F-01 | Maintain a licence-aware source registry | Every run uses approved source IDs only; verify/rejected sources fail validation |
| F-02 | Create resident and demographic population surfaces | Totals reconcile to approved control geographies within a documented tolerance |
| F-03 | Generate reproducible weighted synthetic people | Same data, parameters and seed create identical agents and QA totals |
| F-04 | Produce PFLOW-compatible activity, trip and trajectory records | Schema, referential integrity, time order and mode-code checks pass |
| F-05 | Create time-of-day population estimates | Mesh counts reconcile to active agents at every published time step |
| F-06 | Apply flood conditions to the transport graph | Every closure or speed penalty cites depth, threshold and effective time |
| F-07 | Simulate evacuation | Agents have eligibility, warning receipt, departure, route and outcome states |
| F-08 | Evaluate buildings and refuges separately | Height/exposure and refuge verification are different fields and layers |
| F-09 | Compare scenarios | Runs with different flood, behaviour or refuge assumptions can be compared |
| F-10 | Publish provenance and uncertainty | Every chart/map exposes validation status, scenario status and run manifest |

### 3.2 Non-functional requirements

- **Reproducibility:** immutable input snapshots, checksums, code version, seed and parameters.
- **Privacy:** public products are aggregated; synthetic IDs cannot be linked to people.
- **Auditability:** no output without its source, transformation and validation status.
- **Accessibility:** keyboard navigation, semantic controls, contrast and non-colour status cues.
- **Performance:** interactive aggregate views should respond in under one second for a pilot run; a single trajectory should load in under 500 ms; the map should render no more than 500 detailed trajectories at once.
- **Resilience:** ingestion and simulation stages are idempotent and resumable.
- **Portability:** open formats and a documented PFLOW adapter avoid dependence on one web or compute vendor.
- **Honesty:** the UI must display “demonstration”, “research”, “reviewed” or “operational” status at run and layer level.

## 4. Population is five different quantities

The model must never use “population” as an unqualified field.

| Quantity | Meaning | Primary use | Must not be interpreted as |
|---|---|---|---|
| **Resident baseline** | Estimated usual residents by 100 m cell and reporting area | Exposure denominator and home allocation | People present at noon or during an event |
| **Demographic controls** | Age/sex totals and approved subdistrict/district totals | Constrain synthetic weights | Individual records or households |
| **Synthetic people** | Reproducible, non-real agents with weights and assigned home cells/buildings | Mobility and evacuation model | A reconstruction of named residents |
| **Dynamic PFLOW population** | Agents present in each mesh or facility at a time step | Day/night exposure and congestion | Live device-derived occupancy |
| **Evacuation cohort** | Eligible, exposed, warned or ordered agents selected by a scenario | Evacuation outcomes | All residents or all exposed people |

Each metric shown on the website must name one of these quantities, its timestamp, geography and model status.

## 5. Open population data strategy

### 5.1 Approved baseline sources

1. **WorldPop Global2 R2025A population counts** — 100 m-class resident surface under CC BY 4.0. Use for spatial distribution, not time-of-day presence.
2. **WorldPop Thailand age and sex structures, R2025A** — 100 m age/sex estimates under CC BY 4.0. Use as demographic marginals with uncertainty, not as microdata.
3. **Department of Provincial Administration / National Housing Authority, population and houses by subdistrict (2025/2568)** — approved aggregate control totals under the Thai Open Data Common licence.
4. **National Statistical Office / Department of Provincial Administration, registered population by district, sex and year (2021–2025)** — approved trend and external-check totals under Creative Commons Attribution.

OpenStreetMap building footprints and Google Open Buildings 2.5D may guide dasymetric allocation, but neither source proves residential use. Building height may inform capacity priors only after local validation and may never determine refuge suitability on its own.

### 5.2 Population synthesis for the MVP

The recommended sequence is:

1. Harmonise all approved population controls to a dated reporting geography.
2. Store rasters in their source CRS and record it; store interchange vectors in `OGC:CRS84`.
3. Select and document a projected analysis CRS before any area, distance, routing or buffering operation. `EPSG:32647` is a candidate for Bangkok, not an automatic choice.
4. Clip WorldPop to the pilot area without resampling counts unnecessarily.
5. Reconcile WorldPop cell totals to approved subdistrict control totals using constrained scaling.
6. Reconcile age/sex cells to district/subdistrict marginals with iterative proportional fitting or another documented raking procedure.
7. Allocate residents to residential-capable buildings where evidence supports it; keep a residual grid allocation for cells whose building use is unknown.
8. Integerise only when an individual-agent run requires it. Preserve fractional weights for aggregate reporting.
9. Generate stable synthetic IDs from the population version and random seed, never from source row identifiers.
10. Publish reconciliation, sparsity, geometry and uncertainty diagnostics.

Minimum person fields:

| Field | Description |
|---|---|
| `person_id` | Run-scoped synthetic identifier |
| `population_version` | Immutable synthesis version |
| `weight` | People represented by the record; 1 for integerised agents |
| `age_band` | Approved aggregate band, not an invented exact age |
| `sex_code` | Source-compatible aggregate code plus unknown option |
| `home_cell_id` | 100 m or chosen base cell |
| `home_building_id` | Optional; null when evidence is insufficient |
| `home_admin_id` | Versioned reporting geography |
| `mobility_profile` | Scenario/calibrated class with provenance |
| `assistance_need` | Scenario field until an approved source exists |
| `vehicle_access` | Scenario field until an approved source exists |

### 5.3 Why weighted persons first

Weighted people are the strongest open-data-pure starting point because approved public sources support demographic totals but not realistic Bangkok household relationships. A household synthesiser would add useful within-household departure and vehicle-sharing behaviour, but it could also manufacture confidence in variables that have no evidence base.

The household model should be promoted only when at least one of the following becomes available:

- openly reusable household-size and household-composition marginals at useful geography;
- an approved anonymised household microdata agreement;
- a locally validated household generator whose calibration data and limitations can be published.

Until then, household coordination and vehicle access are scenario parameters with sensitivity ranges.

### 5.4 Dynamic daytime and nighttime population

Resident cells become time-varying presence through PFLOW activity states, not by applying a single citywide multiplier. For each simulation step:

`present(mesh, t) = stationary activities(mesh, t) + travellers currently on links(mesh, t)`

The prototype may use clearly labelled day/evening/night illustrative profiles. A research release must instead estimate activity start time, duration, purpose and destination using reusable Bangkok evidence. If no licensable travel diary is available, the system may run declared scenario priors, but those results remain “demonstration” and the uncertainty range must be shown.

### 5.5 Population validation gates

- Control-total error by source geography is below the declared tolerance.
- No negative weights or impossible age/sex categories.
- All agents have a valid home cell; building assignment may be null.
- Weighted age/sex distributions match held-out totals within confidence bounds.
- Daytime/nighttime totals conserve agents except for explicit external trips.
- Published small-area outputs satisfy minimum-count suppression and aggregation rules.
- Results are reviewed at 1 km or coarser before any 500 m public claim, reflecting known PFLOW people-flow reliability degradation at finer resolution and the privacy risk of sparse cells.

## 6. PFLOW-to-Bangkok pipeline

PFLOW supplies the contract and sequencing; Bangkok supplies the data, behaviour, network and validation.

### 6.1 Canonical stages

| Stage | Bangkok implementation | Inputs | Outputs | Required checks |
|---|---|---|---|---|
| P0. Sources | Snapshot approved datasets and licence evidence | Registry | Immutable raw objects | Access, licence, checksum |
| P1. People | Generate weighted/integerised synthetic people | Population controls, grid, buildings | `persons`, population QA | Marginal fit, geometry, uniqueness |
| P2. Activities | Generate daily chains | Persons, destinations, activity priors/calibration | PFLOW activity records | Time order, duration, purpose, destination |
| P3. Trips | Convert adjacent activities into trips | Activities, mode model | `trips` | Referential integrity, non-negative duration |
| P4. Trajectories | Route trips on dated network | Trips, OSM graph, mode rules | `waypoints`, link traversals | Connected path, speed/time plausibility |
| P5. Aggregates | Calculate mesh and link volumes | Activities, trajectories | 10-min mesh, hourly link tables | Conservation and duplicate checks |
| F1. Flood | Derive time-varying hazard surface | Extent, terrain/depth model, scenario | Depth/extent time slices | Observation/model labels, held-out score |
| F2. Network impact | Map water to edges | Flood surface, network, thresholds | Edge state by time/mode | Monotonicity, threshold provenance |
| E1. Cohort | Select evacuation population | Dynamic people, exposure, order rules | Agent evacuation state | Cohort reconciliation |
| E2. Evacuation | Simulate departure, route choice and refuge | Cohort, affected graph, destinations | Outcomes, routes, queues | No teleportation, capacity, failure reasons |
| V1. Validation | Compare with held-out Bangkok evidence | All outputs | Validation report | Predeclared metrics and gates |
| U1. Publish | Generate safe aggregate products | Reviewed outputs | Web tiles, tables, manifest | Privacy, status, attribution |

### 6.2 PFLOW record compatibility

Retain a lossless adapter to PFLOW v3.2 concepts:

- `PersonGenerator`: person and home records;
- `ActivityGenerator`: `person_id, age, gender_id, labor_id, start_time, duration, purpose_id, lon, lat, gcode`;
- trip/trajectory generation: trip IDs, modes, origin/destination time and ordered waypoints;
- `MeshVolumeCalculator`: population by 500 m mesh per 10 minutes;
- `LinkVolumeCalculator`: traffic/pedestrian volume by link per hour.

Mode IDs should remain compatible where possible: 0 walk, 1 bicycle, 2 bus, 3 car, 4 train, 8 taxi and 9 truck. Bangkok extensions use namespaced fields rather than silently reusing a PFLOW code.

Compatibility tests prove that files and semantics line up. They do not prove that Bangkok activity, mode or route behaviour is correct.

### 6.3 Activity and destination generation

Activities should be stored as explicit states rather than inferred only from trajectories:

- home;
- work;
- education;
- shopping/services;
- health/care;
- social/recreation;
- transfer/travel;
- evacuation/refuge;
- unknown.

The destination model should combine reachable facilities, land/building evidence, aggregate attraction weights and OD constraints. Missing evidence must result in an `unknown` or scenario-based destination class, not an invented precise venue.

The PFLOW technical material describes transferable non-parametric components, but Bangkok transferability must be treated as a hypothesis. Activity frequency, departure time, mode share, trip suppression, telework, school travel and ageing effects require local tests.

### 6.4 Trajectory generation

Use a dated, mode-specific OSM graph with:

- explicit direction and access rules;
- walk, cycle and vehicle speeds by edge class;
- transit as a separate later integration unless reusable schedules and routing data pass the gate;
- stable `network_version` and edge identifiers;
- route failure reasons rather than straight-line fallbacks;
- trip-scoped mode lookup keyed by `(person_or_vehicle_key, trip_id)`.

A* or another documented shortest-path algorithm is sufficient for the baseline. Dynamic rerouting may be added after the static affected-graph model passes conservation and route-validity tests.

## 7. Flood, buildings and evacuation

### 7.1 Flood extent and depth

Maintain separate layer roles:

- **observed extent** from GISTDA and independently classified Sentinel-1;
- **modelled extent/depth** from a declared hydraulic or proxy model;
- **scenario forcing** such as rainfall, river stage and tide;
- **validation measurements** that are licensed for the intended use.

An extent polygon is not a depth surface. The prototype may visualise a demonstration depth, but a research run needs a documented depth method and held-out validation. The exact rainfall source remains unresolved because public access without explicit reuse permission fails the project’s data gate.

### 7.2 Edge impedance

For every network edge, time and mode, store:

- maximum and representative depth;
- observation/model source role;
- speed multiplier;
- capacity multiplier;
- closure flag;
- threshold-set version;
- reason code and uncertainty.

Thresholds must be mode- and vehicle-class-specific and tested as sensitivity parameters. A deterministic threshold should never be presented as a universal safety fact.

### 7.3 Building model

Building fields should include footprint source, height estimate, confidence, occupancy/use evidence, ground elevation if available, exposure depth and accessibility. Derived storeys or capacity must include the formula and uncertainty.

Refuge eligibility is a separate reviewed entity with:

- verified operator/authority;
- accessible entrance and hours;
- usable floors/areas;
- capacity and current availability assumptions;
- structural and flood-safety assessment;
- access mode constraints;
- review timestamp.

Unverified tall buildings may be shown as exposure assets, never as recommended refuges.

### 7.4 Evacuation state machine

Each synthetic person follows an auditable state machine:

`not eligible → exposed/eligible → warned → deciding → departed → en route → arrived | stranded | shelter full | route failed | did not depart`

Key behaviour modules:

- warning reach and delay;
- compliance/departure decision;
- preparation delay;
- household/assistance scenario, where applicable;
- mode availability and choice;
- destination choice under capacity;
- route choice and replanning interval;
- pedestrian/vehicle link congestion;
- refuge admission and overflow.

The MVP can use mesoscopic agent routing. Microscopic pedestrian simulation such as JuPedSim is optional for selected bottlenecks after the city-scale model identifies them; it should not be used to imply citywide precision.

## 8. System architecture

```text
Open source catalogues
        │
        ▼
licence gate ──► immutable raw store + licence snapshots
        │
        ▼
spatial staging ──► geometry/CRS/quality reports
        │
        ├──► population controls ─► weighted persons
        ├──► OSM/buildings ───────► mode networks + assets
        └──► flood observations ──► extent/depth time slices
                                      │
weighted persons ─► activities ─► trips ─► trajectories
        │                              │
        └──────── dynamic presence ◄───┘
                       │
flood + graph + refuges + warning/departure scenarios
                       │
                       ▼
                evacuation engine
                       │
                       ▼
DuckDB/Parquet run outputs ─► validation/privacy gates
                       │
                       ▼
FastAPI/query service ─► React + MapLibre/deck.gl website
```

### 8.1 Components

- **Source registry service:** machine-readable access, licence, version and approval status.
- **Ingestion workers:** download/API snapshot, checksum and raw metadata.
- **Spatial staging:** CRS checks, geometry repair reporting, clipping and crosswalks.
- **Population builder:** control reconciliation, weighting, optional integerisation and QA.
- **PFLOW adapter:** people, activities, trips, trajectories, meshes and links.
- **Flood processor:** observations, model slices and edge/building intersections.
- **Evacuation runner:** scenario state machine, network assignment and capacity.
- **Validator:** contract, conservation, plausibility, held-out accuracy and privacy gates.
- **Publisher:** aggregate Parquet, PMTiles/vector tiles, reports and manifests.
- **Web/API:** run construction, progress, maps, comparisons and exports.

### 8.2 Storage

Use a simple layout before introducing distributed infrastructure:

```text
data/
  registry/       source metadata and licence snapshots
  raw/            immutable downloaded objects
  staged/         CRS-normalised and quality-reported inputs
  curated/        population, graph, building and hazard versions
runs/<run_id>/
  manifest.json
  persons.parquet
  activities.parquet
  trips.parquet
  waypoints.parquet
  mesh_volume.parquet
  link_volume.parquet
  flood_edges.parquet
  evacuation_outcomes.parquet
  validation.json
  report/
```

Parquet plus DuckDB is recommended for the pilot because it is reproducible, portable and fast for analytical reads. Add PostgreSQL/PostGIS when concurrent write workflows, role-based editing or long-lived refuge inventories justify it. Object storage holds immutable raw and run artefacts.

### 8.3 Canonical tables

| Table | Key | Purpose |
|---|---|---|
| `population_cells` | population version + cell | resident and demographic estimates |
| `persons` | run + person | synthetic agents and weights |
| `activities` | run + person + sequence | time, purpose and destination |
| `trips` | run + trip | adjacent activity movement and mode |
| `waypoints` | run + trip + sequence | ordered trajectory points |
| `mesh_volume` | run + mesh + time | stationary and travelling population |
| `network_edges` | network version + edge | mode-specific graph |
| `link_volume` | run + edge + time | assignment volume |
| `flood_slices` | hazard version + time + cell | observed/modelled water state |
| `edge_states` | run + edge + time + mode | flood impedance/closure |
| `buildings` | building version + building | footprint, height and exposure |
| `refuges` | refuge version + refuge | verified capacity and access |
| `evacuation_states` | run + person + time | state transitions and reasons |
| `validation_runs` | run + check | metrics, thresholds and results |
| `ingest_log` | source snapshot | provenance and processing results |

All spatial tables record CRS, geometry validity result and source lineage. Join checks assert expected cardinality so that one-to-many intersections do not silently inflate population or exposure.

## 9. Run orchestration and API

### 9.1 Run state machine

`draft → validating inputs → queued → population → activities → trips → trajectories → flood impact → evacuation → aggregating → validating outputs → published | failed | cancelled`

Each stage writes an immutable checkpoint and can be retried from its inputs. A stage key is a hash of code version, source versions and parameters; identical work can be reused. Failed stages preserve logs and partial outputs but cannot be published.

### 9.2 Minimum API

| Method and path | Purpose |
|---|---|
| `GET /v1/sources` | Approved/verify/rejected registry and licence status |
| `GET /v1/populations` | Available population versions and QA summaries |
| `POST /v1/populations` | Request a population build |
| `GET /v1/scenarios` | Saved flood/evacuation scenarios |
| `POST /v1/runs` | Validate and create a run |
| `GET /v1/runs/{id}` | Stage, progress, warnings and manifest |
| `POST /v1/runs/{id}/cancel` | Cancel at a checkpoint |
| `GET /v1/runs/{id}/stats` | Aggregate KPIs and uncertainty |
| `GET /v1/runs/{id}/mesh?time=` | Time-slice dynamic population/exposure |
| `GET /v1/runs/{id}/links?time=&mode=` | Link state and volume |
| `GET /v1/runs/{id}/trips/{trip_id}` | One synthetic trip/trajectory |
| `GET /v1/runs/{id}/buildings` | Aggregated exposure; protected fields omitted |
| `GET /v1/runs/{id}/validation` | Checks, thresholds and evidence |
| `GET /v1/runs/{id}/export` | Manifested public artefact bundle |

Create operations accept idempotency keys. Large endpoints return columnar data or vector tiles, not oversized JSON. Public APIs never expose a full person-level daily trace set.

## 10. Website plan

### 10.1 Scenario Lab

- flood controls: rainfall, river anomaly, tide and observation/model status;
- population controls: day/evening/night or a clock time, population version and cohort rule;
- map layers: population, flood, height, routes and verified refuges;
- PFLOW stage rail: people → activities → trips → trajectories → flood/evacuation;
- headline metrics: people present, exposed cohort, road capacity loss, clearance time and unserved agents;
- timeline playback with visible model timestamp;
- click details that name source, model status and uncertainty.

### 10.2 Population page

- five-quantity population explainer;
- 24-hour present-population profile;
- demographic and geographic reconciliation cards;
- source and licence status;
- population-version QA and limitations;
- explicit “synthetic, not real individuals” notice.

### 10.3 Data Registry

- access/licence gate and exact resource links;
- version, retrieval date, format, geography, time and role;
- approved, verify or rejected state;
- licence snapshot/checksum in production;
- filter for population, flood, buildings, networks and validation.

### 10.4 Method and run detail

- PFLOW-to-Bangkok stage definitions;
- inputs, parameters, warnings and output counts per stage;
- validation panels for population, mobility, flood, network and evacuation;
- scenario comparison with uncertainty rather than a single winner;
- downloadable run manifest and citations.

## 11. Validation framework

### 11.1 Population

- control-total absolute/relative error;
- age/sex distribution error by held-out geography;
- building allocation coverage and residual-grid share;
- day/night conservation;
- sparse-cell and disclosure-risk report.

### 11.2 Mobility/PFLOW

- trip count, rate and purpose distribution;
- departure-time and duration distributions;
- mode share and trip-length distribution;
- OD matrix similarity;
- mesh-volume correlation and error at 1 km, then 500 m only if supported;
- link-volume error against reusable counts;
- route validity and unreachable-trip rate.

PFLOW’s published performance is useful prior evidence, not Bangkok validation. The people-flow material reports stronger reliability at 1 km and above than at 500 m, while rural commuting is weaker. The release must report Bangkok-specific results and never substitute schema checks for ground truth.

### 11.3 Flood

- intersection-over-union, precision and recall for held-out observed extent;
- depth RMSE/MAE and bias where reusable measurements exist;
- wet/dry road classification accuracy;
- time-of-onset and recession error.

### 11.4 Evacuation

- conservation of people across states;
- clearance-time distribution, not only the mean;
- unserved/stranded share and reason;
- refuge overflow and arrival profile;
- route failure and replanning rate;
- sensitivity to warning delay, compliance, speed, capacity, vehicle access and threshold set;
- subgroup distribution of outcomes, with privacy-safe reporting.

### 11.5 Promotion gates

| Status | Evidence required |
|---|---|
| Demonstration | Schema and conservation checks; every assumption labelled |
| Research | Approved inputs; held-out Bangkok evaluation; uncertainty report |
| Reviewed | Independent technical review; agency/user review; reproducible release |
| Operational | Named owner; live-data agreements; incident procedures; monitoring; legal/privacy/security review |

## 12. Privacy, security and responsible use

- Generate non-real IDs and do not retain linkable source identifiers.
- Never ingest personal mobile, call-detail or location traces into the open-data core.
- Publish aggregate cells/links with minimum-count suppression; start at 1 km for population and mobility products.
- Apply role-based access to any future restricted calibration data; do not copy it into public run artefacts.
- Validate all uploaded paths/formats and isolate compute jobs.
- Sign or checksum run manifests and published artefacts.
- Record who promoted a run and why.
- Show warnings when users compare scenarios outside calibrated ranges.
- Add a misuse statement: outputs support planning and research, not individual surveillance, enforcement or real-time rescue directions.

## 13. Scale and performance plan

### 13.1 Pilot assumptions

Start with 2–4 contrasting districts or a corridor/catchment-sized area, approximately 100,000–500,000 represented people, a 24-hour baseline and a 3–6-hour flood/evacuation window. Use weighted agents for fast calibration; use integerised agents only for stages that require discrete queues or capacity.

### 13.2 Bangkok scale

For millions of agents, partition Parquet by run, date/time bucket and spatial tile; route by mode and OD batch; aggregate during computation; publish tiles instead of full trajectories. Detailed agent playback is sampled and capped at 500 visible trajectories. Run orchestration should support horizontal workers, but a distributed platform is not necessary until profiling shows that a well-partitioned single-node DuckDB/Parquet workflow is inadequate.

### 13.3 Service budgets

- `stats` p99 under 200 ms for published aggregate runs;
- trip search p99 under 1 s for result sets up to 10,000 rows;
- one trajectory under 500 ms;
- initial map under 2.5 s on a normal broadband laptop;
- simulation progress event no more than once per second;
- no synchronous browser request waits for a full simulation.

## 14. Delivery roadmap

### Phase 0 — decisions and governance (2 weeks)

- select the pilot area and a dated administrative boundary;
- approve analysis CRS and aggregation grid;
- appoint scientific, data/licensing and emergency-management reviewers;
- define “research” promotion thresholds;
- freeze registry v1 and population definition vocabulary.

**Exit:** signed decision record; no unresolved licence in the required critical path.

### Phase 1 — open population baseline (3–4 weeks)

- ingest WorldPop counts and age/sex surfaces plus approved DOPA/NHA controls;
- build spatial crosswalks and reconciliation pipeline;
- create weighted persons and population QA report;
- add population page, version picker and day/night demonstration profiles.

**Exit:** reproducible population version, control reconciliation and privacy review.

### Phase 2 — PFLOW-compatible Bangkok baseline (4–6 weeks)

- implement person/activity/trip/trajectory schemas and adapters;
- create a dated OSM mode network;
- implement destination/activity scenario priors with explicit status;
- generate mesh/link volumes and trajectory viewer;
- add structural validators and stage-level run UI.

**Exit:** one dry-day pilot run that passes contracts and conservation checks. It remains demonstration until behavioural validation passes.

### Phase 3 — mobility calibration (4–8 weeks, evidence dependent)

- identify reusable Bangkok OD, counts, schedules or survey evidence;
- calibrate activity timing, purpose, destination, mode and route parameters;
- hold out validation geographies/dates;
- document failure modes and supported resolution.

**Exit:** research-grade mobility baseline or an explicit evidence gap report.

### Phase 4 — flood and building exposure (5–7 weeks)

- ingest GISTDA/Sentinel-1 observations;
- implement and validate depth approach;
- intersect buildings and graph edges with time slices;
- validate Open Buildings height locally;
- publish exposure and closure uncertainty.

**Exit:** held-out extent/depth/road-impact report; unverified refuge claims remain absent.

### Phase 5 — evacuation engine (5–7 weeks)

- implement cohort, warning, departure, mode and destination scenarios;
- implement capacity, route failure and stranded states;
- run one-at-a-time sensitivity and ensemble scenarios;
- add comparisons, clearance distributions and equity-safe aggregates.

**Exit:** all agents reconcile to outcomes; sensitivity report identifies dominant assumptions.

### Phase 6 — pilot review and hardening (4–6 weeks)

- independent methodology and software review;
- tabletop sessions with Bangkok stakeholders and accessibility users;
- security, privacy, load and reproducibility tests;
- publish a versioned research release with limitations.

**Exit:** reviewed research tool. Operational status requires a separate governance programme.

Indicative end-to-end research prototype: **23–38 weeks**, with the largest schedule risk being availability and licence suitability of local mobility, rainfall/depth and refuge evidence.

## 15. Team and ownership

Minimum sustained team:

- product/research lead;
- population and transport modeller;
- flood/hydraulic modeller;
- geospatial/data engineer;
- simulation/backend engineer;
- frontend/data-visualisation engineer;
- part-time validation, licensing/privacy and emergency-management reviewers.

One person may cover multiple roles in the prototype, but validation approval should not be performed solely by the author of the model being reviewed.

## 16. Acceptance criteria for the first integrated prototype

1. The site contains Scenario, Population, Data Registry and Method views.
2. Population can be toggled on the map and switched between day, evening and night demonstration states.
3. Scenario metrics separately name people present and people exposed.
4. A visible PFLOW stage rail connects population, activities, trips, trajectories and flood evacuation.
5. The registry includes resident counts, age/sex and administrative control totals with licences.
6. The run manifest requires a population model, population version and seed.
7. A sample run can produce structurally valid person, activity, trip, trajectory, mesh, link and evacuation tables.
8. Every real input has a source URL, retrieval time, checksum and licence snapshot.
9. Public output contains no real individual trace and enforces aggregation rules.
10. The interface labels all current numeric results as illustrative.

## 17. Recommended decisions and strongest counterarguments

| Decision | Recommendation | Strongest counterargument / mitigation |
|---|---|---|
| Population unit | Weighted people first | Discrete queues need integers; integerise only for those stages and compare to weighted totals |
| Household model | Defer until evidence exists | Household coordination matters; expose it as sensitivity scenarios and prioritise licensable marginals |
| Storage | Parquet + DuckDB for pilot | Concurrent editing favours PostGIS; add it when refuge/data stewardship workflows require it |
| Aggregation | Projected square grid plus admin reports | H3 is easier across regions; preserve a crosswalk and revisit after Bangkok pilot |
| Public resolution | 1 km initial population/mobility products | 500 m is useful locally; allow only when validation and disclosure review support it |
| Routing | Mode-specific OSM + A* baseline | Transit realism is limited; add licensable schedules and dedicated routing as a later module |
| Evacuation | Mesoscopic city model | Bottleneck dynamics are coarse; couple selected sites to a microscopic pedestrian engine |
| Buildings | Height as exposure/capacity evidence only | Vertical evacuation needs building detail; create a verified refuge inventory rather than inferring safety |
| PFLOW | Preserve contracts, recalibrate behaviour | Reduces direct comparability; publish both adapter compliance and Bangkok calibration results |

## 18. Open decisions and revisit points

These choices must be resolved before research-grade simulation:

1. Exact pilot area and event/use case.
2. Approved projected analysis CRS and canonical aggregation grid.
3. Reusable rainfall forcing and measured depth evidence.
4. Reusable Bangkok activity/OD/mode evidence.
5. Administrative boundary version with explicit reuse terms.
6. Refuge authority, verification process and capacity definition.
7. Population privacy thresholds and whether any internal 500 m outputs are permitted.
8. Whether external trips across the pilot boundary are generated, absorbed or represented as boundary flows.
9. Which uncertainties require ensembles versus one-at-a-time sensitivity tests.
10. Promotion authority for research, reviewed and operational statuses.

Revisit the architecture when one pilot run exceeds a single-node memory budget, when multiple users must edit shared reference data, when near-real-time feeds are approved, or when an agency commits to operational ownership.

## 19. Immediate build slice

The next four implementation tickets should be:

1. **Population contract:** add population fields to the run schema and a versioned population configuration.
2. **Open population registry:** register WorldPop age/sex, DOPA/NHA subdistrict controls and NSO/DOPA trend totals.
3. **Population prototype:** add the Population page, map toggle, day/evening/night state and separate present/exposed metrics.
4. **PFLOW run rail:** expose people, activities, trips, trajectories and flood/evacuation stages in the Scenario Lab.

## 20. Research basis

The PFLOW design in this plan was checked against the project vault’s PFLOW pages:

- `src-ppflow-technical-guide.md`
- `src-pflow-people-flow-pipeline-v32.md`
- `people-flow-webapi-pipeline.md`
- `people-flow-reality-gap-analysis.md`
- `trajectory-viz-architecture-v02.md`

The geospatial safeguards follow the workflow principles described by Kassis et al., *Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents* (2026): explicit CRS, data provenance, geometry checks, join-cardinality checks and validation before interpretation.

