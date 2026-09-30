# BKK/FLOW

An open-data flood exposure, building and evacuation research platform for
Bangkok, built on the PFLOW people–activities–trips–trajectories contract.

> **Status: `demonstration`.** Every number this repository produces is
> modelled demonstration output built from a *declared flood scenario* and
> *uncalibrated behavioural priors*. It is not a forecast, not an early-warning
> product, and not evacuation advice. No building in this build is a verified
> refuge.

## What is here

| Component | Path | What it does |
|---|---|---|
| Pipeline | `pipeline/bkkflow/` | P0 sources → P1 people → P2 activities → P3 trips → P4 trajectories → P5 aggregates → F1/F2 flood impact → E1/E2 evacuation → V1 validation → U1 publish |
| CLI | `pipeline/run.py` | `ingest`, `run`, `run --baseline`, `validate`, `registry` |
| Report | `pipeline/report.py` | Figures and a written run summary |
| API | `api/` | FastAPI service over the immutable run artefacts |
| Site | `site/` | React + MapLibre frontend, reads only from the API |
| Contracts | `schemas/`, `docs/RUN_ARTIFACT_CONTRACT.md` | Run manifest schema and the run/API/website contract |
| Registry | `data/source-registry.json` | Licence-aware source gate: 12 resources, 3 states |
| Config | `config/` | Resolved pilot area, population and scenario configuration |

## The pilot

| Property | Value |
|---|---|
| Area of interest | Khlong San district (เขตคลองสาน), OSM relation `R3147280` |
| Area | 5.96 km² |
| Analysis CRS | `EPSG:32647` (WGS 84 / UTM 47N), explicitly justified in `config/pilot.json` |
| Resident baseline | WorldPop 2020 100 m counts, 678 occupied cells, **115,959 residents** |
| Network | 3,755 OSM ways → **7,514 directed edges, 6,701 nodes, 168.7 km** walkable |
| Buildings | 6,963 OSM footprints, 2,398 intersecting the AOI |

## City scale — Bangkok Metropolitan Administration

A second, larger scope covers the whole BMA. It is a **separate run** and
never silently substitutes for a pilot result.

| Property | Value |
|---|---|
| Area of interest | Bangkok (กรุงเทพมหานคร), admin level 4, OSM relation `R92277` |
| Area | **1,643.5 km²** |
| OSM source | one 42 MB regional PBF (BBBike), read locally via GDAL — no tiled Overpass, no rate limits |
| Network | 215,770 ways → **939,006 edges, 854,628 nodes, 26,744 km** |
| Buildings | **424,420** OSM footprints with height evidence recoverable |
| Resident baseline | WorldPop 2020 clipped to the BMA: **10,891,062 residents**, 181,662 cells |
| Public aggregation | 1 km fixed |
| Routing | compressed CSR index; a **full-city travel-time field takes ~2 s** and reaches 98.3% of nodes |

**Observed hazard layer (new):** JRC Global Surface Water v1.4, Landsat-derived
yearly water classification 1984-2021, ingested for 2010, 2011, 2012 and 2020.
This is the **first genuinely observational hazard data in the project** — every
other input is either a modelled surface or a declared scenario.

| year | observed water | share of classified area | excess vs 2010 |
|---|---:|---:|---:|
| 2010 | 114.2 km² | 7.63% | baseline |
| 2011 | 114.0 km² | 7.68% | −0.15 km² |
| **2012** | **137.8 km²** | **9.12%** | **+23.7 km²** |
| 2020 | 114.3 km² | 7.72% | +0.12 km² |

The 2012 signal is a real anomaly. **2011's flood is absent from this record**,
which is the product behaving as documented: an annual Landsat composite cannot
capture a flood lasting weeks. Every year here is a lower bound on extent.

**Destination candidates (new):** 1,400 records recovered from the OSM points
layer — 343 shelter tags, 296 health care, 296 education, 58 emergency service,
312 community facilities, 95 commerce. **Zero are verified.** A shelter tag is
someone's mapping decision, not an operator, a capacity or an inspection.

### Hazard screening (new)

Two city-scale screening layers, both driven by real data and both labelled as
screening rather than simulation.

**Connectivity under observed water.** The ways that held water in each observed
year are removed from the network, measured at the source 30 m classification,
and the question becomes whether exposed population can still reach a
destination on foot.

| year | ways closed | reachable | p50 |
|---|---:|---:|---:|
| 2010 | 57,836 (6.16%) | 71.5% | 42.9 min |
| 2011 | 56,545 (6.02%) | 72.8% | 43.8 min |
| 2012 | 61,743 (6.58%) | 68.7% | 41.9 min |
| 2020 | 57,532 (6.13%) | 71.5% | 43.8 min |

This is **not** an evacuation simulation: a yearly Landsat classification has
no depth, duration, flow direction or timing, and water is treated as
impassable at any depth.

**How much of that is the assumption?** Closing every water-affected way is a
choice. Re-running at 25% and 50% closure swings the absolute reachable share
across **20 percentage points**, and the year ranking does not survive: 2012 is
the worse year at 100% and 50% closure but marginally the better one at 25%. The
code reports year_ranking_stable_across_assumptions: false rather than
asserting a winner.

**Drainage-discharge index.** A relative index over the 1,693 grid cells built
from the mapped drainage network, basins and overflow paths. Monotonicity is
verified on real data (rho of drainage density against risk −0.78, distance
against risk +0.64). It is a screening index from infrastructure geometry only:
not a hydraulic model, not a depth, and blind to rainfall, river stage, tide,
pumping and gate operations.

**This run has no flood *depth* layer and no evacuation outcomes.** That is a decision
on the record, not an omission: the only reachable open terrain source carries
roughly 5–10 m of vertical error across a floodplain whose flood-relevant
elevation range is 0–2 m, so a stage-based depth surface would be a noise field
wearing the costume of a flood map. Measured evidence, including a transect
across the Chao Phraya in which the river channel is not resolved at all, is in
[`docs/CITY_SCALE_LIMITATIONS.md`](docs/CITY_SCALE_LIMITATIONS.md). Every
hazard field in the city statistics is `null` with a reason attached; a zero
would read as "no flooding", which is a different and false claim.

Routing is *not* the blocker — at 2 seconds per city-wide travel-time field,
evacuation at city scale becomes tractable the moment a defensible depth surface
exists.


## Quick start

```powershell
# 1. Stage licensed sources (AOI, OSM extract, WorldPop raster). ~300 MB, resumable.
python pipeline/run.py ingest

# 2. Execute a run. Writes runs/<run_id>/ with every artefact.
python pipeline/run.py run

# 3. Execute the dry baseline for comparison.
python pipeline/run.py run --baseline

# 4. City scale: stage the regional extract, then run the city baseline.
python pipeline/run.py ingest-city
python pipeline/run.py city
python pipeline/city_report.py <city_run_id>

# 5. Validate the newest run.
python pipeline/run.py validate

# 6. Generate figures and the run summary.
python pipeline/report.py <run_id> --compare <baseline_run_id>

# 7. Serve the API and the site.
uvicorn api.app:app --port 8000
cd site; pnpm install; pnpm dev
```

Tests:

```powershell
python -m pytest pipeline/tests -q   # 37 tests
python -m pytest api/tests -q         # 42 tests
cd site; pnpm build
```

## What the data is real, and what it is not

This distinction is the point of the project, so it is stated everywhere.

**Real and licence-checked**

- OpenStreetMap roads, buildings and water — ODbL 1.0, fetched via Overpass,
  checksummed, with retrieval timestamps.
- WorldPop 2020 resident counts — CC BY 4.0, downloaded, window-clipped in its
  native CRS with no resampling, checksummed.
- The area of interest — a real OSM administrative boundary, 5.96 km².

**Not real, and labelled as such in every artefact**

- **Flood depth** is a *scenario*: a distance-to-water decay, because no
  rainfall, river-stage or depth measurement passed the project's licence
  gate and the GISTDA host did not resolve from the build environment. There is
  no observed flood layer in this build.
- **Population is a resident baseline**, not a daytime or event-time
  population. Presence comes from scenario activity priors.
- **No external control total was ingested**, so population control error is
  recorded as *unavailable* rather than passing quietly.
- **Age structure is unknown for every person.** No age-structure source passed
  the licence gate, so `age_band` is `unknown` rather than an invented
  distribution.
- **Sex split, mobility, warning reach, compliance and preparation delay are
  declared priors**, not measurements.
- **Every destination is hypothetical and unverified.** There is no refuge
  inventory, so the model aims at labelled synthetic targets and makes no
  shelter claim.
- **Building height is unknown for 96.9%** of footprints in the AOI; the rest is
  tagged or derived from `building:levels` at an assumed 3.0 m per storey.

## Product principles

1. A source must be publicly accessible **and** explicitly reusable. A
   `verify` resource can never enter a run; the gate raises before any stage
   starts.
2. Observations, predictions and scenario assumptions stay visually and
   structurally distinct. `source_role` is a required column, not a caption.
3. Every run is reproducible from its manifest: immutable inputs, checksums,
   seeds, parameters, component versions, and a schema-validated manifest.
4. Building height is an exposure and capacity input — never proof that a
   building is a safe shelter. Height and refuge eligibility are separate
   fields with separate confidences.
5. **Resident population, time-of-day presence, exposed people and the
   evacuation cohort are four different quantities** and are never summed into
   one "affected people" figure.
6. A trip that cannot be routed records a failure reason. There is no
   straight-line fallback, because a straight line is a claim about a route that
   was never computed.
7. An unknown is written as `null`, never as `0`.

## Known limitations of this build

- **No usable terrain model, at any scale.** Two independent DEMs were measured
  and both fail: the AWS terrarium tiles read +5 m in central Bangkok where
  ground is 1-2 m, and the MitrEarth 30 m DEM reads +13.8 m at Khlong San with
  adjacent samples swinging 5-31 m. Bangkok's flood-relevant topography is the
  0-2 m band, so any DEM with larger error cannot support a depth model. This
  is the single blocker on city-scale depth and evacuation.
- **No rainfall forcing and no observed extent**, for licence and reachability
  reasons.
- **No calibrated mobility.** No licensable Bangkok travel diary was available,
  so activity timing, mode choice and destination choice are priors. The run
  cannot be promoted above `demonstration`.
- **No refuge inventory.** Destinations are hypothetical.
- **No building-level address or entrance network.** Buildings are exposed, not
  entered.
- **Single scenario per run.** The sensitivity matrix in `config/scenario.json`
  is declared but not yet executed as an ensemble.

## Attribution and data policy

Downloaded and derived geospatial data are deliberately git-ignored. Every real
input must be recoverable from a source URL, retrieval timestamp, request
parameters and a SHA-256 checksum recorded in the run manifest.

- OpenStreetMap contributors, ODbL 1.0
- WorldPop, CC BY 4.0
