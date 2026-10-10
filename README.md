# BKK/FLOW

An open-data flood exposure, building and evacuation research platform for
Bangkok, built on the PFLOW people–activities–trips–trajectories contract.

> **Status: `demonstration` — DONE_WITH_CONCERNS.** The four-area release uses
> declared flood scenarios and uncalibrated behaviour. The historical city run
> provides observed annual water and conditional connectivity screening but is
> superseded because it used an earlier source inventory. Neither is a forecast,
> warning product or evacuation recommendation. No destination is verified.
>
> See [current project status and owners](docs/IMPLEMENTATION_STATUS.md) for
> merged work, verified results, pending fixes and evidence gates.

## What is here

| Component | Path | What it does |
|---|---|---|
| Pipeline | `pipeline/bkkflow/` | P0 sources → P1 people → P2 activities → P3 trips → P4 trajectories → P5 aggregates → F1/F2 flood impact → E1/E2 evacuation → V1 validation → U1 publish |
| CLI | `pipeline/run.py` | `ingest`, `run`, `run --baseline`, `validate`, `registry` |
| Report | `pipeline/report.py` | Figures and a written run summary |
| API | `api/` | FastAPI service over the immutable run artefacts |
| Site | `site/` | React + MapLibre frontend, reads only from the API |
| Contracts | `schemas/`, `docs/RUN_ARTIFACT_CONTRACT.md` | Run manifest schema and the run/API/website contract |
| Registry | `data/source-registry.json` | Licence-aware source gate: 19 resources, 3 allowed status values |
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

## Historical city scale — Bangkok Metropolitan Administration

A second, larger scope covers the whole BMA. It is a **separate run** and
never silently substitutes for a pilot result. The table below documents an
immutable historical run; there is **no current city result** on the admitted
Geofabrik source. See the [release evidence record](docs/RELEASE_EVIDENCE_2026-10-10.md)
for the current four-area demonstration boundary.

| Property | Value |
|---|---|
| Area of interest | Bangkok (กรุงเทพมหานคร), admin level 4, OSM relation `R92277` |
| Area | **1,643.5 km²** |
| OSM source | historical BBBike Bangkok cache; superseded by the admitted Geofabrik staging inventory |
| Network | 235,678 ways → **1,038,811 edges, 949,151 nodes, 30,060.16 km** |
| Buildings | **272,116** footprints; height tagged for 577, derived from levels for 21,161, unknown for 250,378 |
| Resident baseline | WorldPop 2020: **10,891,061 modelled residents**, 181,662 raster cells |
| Public aggregation | 1 km, 1,693 population cells |
| Connectivity | pedestrian screening with fixed baseline anchors, 400 m snap tolerance and a 180 minute routing limit |

These results belong to immutable run
`be6a4e08-e2d7-4dd9-bf8b-4f2a02a12a81`, executed on 4 October 2026 at
`a5dfc51c59df65a27e136cbce594d73e09179181`. Merged `main` at `9278893`
has the same source tree. The run passed 8 internal checks; all 12 recorded
output hashes were verified. Source identity for this historical run is
externally recorded, not embedded in its manifest.

### Observed annual surface water

JRC Global Surface Water v1.4 distinguishes no observations (0), non-water (1),
seasonal water (2) and permanent water (3). The following replaces the withdrawn
pre-correction values and the unsupported claim that the 2011 flood was absent.

| Year | Water area | Classified area | Water share of classified area |
|---|---:|---:|---:|
| 2010 | 157.8473 km² | 272.0265 km² | 58.03% |
| 2011 | 170.7147 km² | 284.7396 km² | 59.95% |
| 2012 | 143.4223 km² | 281.2608 km² | 50.99% |
| 2020 | 173.7170 km² | 288.0152 km² | 60.32% |

About 83% of the BMA has no observations in each of these annual classifications.
It must not be counted as dry land. These are annual surface-water classifications,
including permanent water, not event-specific flood footprints or depth.

### Conditional connectivity

Reachable share of modelled residents in population cells overlapping a
water-containing 1 km cell, under nested closure subsets of water-affected edges:

| Year | 100% wet-edge closure | 50% closure | 25% closure |
|---|---:|---:|---:|
| 2010 | 96.4737% | 97.2481% | 97.7858% |
| 2011 | 95.8942% | 96.5484% | 97.6087% |
| 2012 | 96.7831% | 97.0658% | 97.4778% |
| 2020 | 95.5462% | 96.9035% | 97.5644% |

All 12 cases were reproduced on 4 October. Reopening roads never decreases
reachability; the worst-ranked year changes with the closure assumption. These
percentages are not evacuation success rates. Routing is undirected; vehicle
one-way restrictions are not enforced. Foot access and snapping remain assumptions.

There are **1,034 unverified destination candidates**: 236 shelter tags,
232 education, 225 health, 207 community, 83 commerce and 51 emergency records.
They provide neither usable capacity nor a guarantee of safe access.

Source coverage is not mapping completeness. The 50 OSM district polygons leave
76.1429 km² of the BMA geometry unreconciled; its cause is unverified. The saved
water inventory has 4,681 features and 3,242.94 km of line geometry. The drainage
index is an infrastructure-geometry screen, not a hydraulic model.

**City flood depth and evacuation outcomes remain null with explicit reasons.**
Terrain, datum, hydraulic forcing, event validation and operator-verified
capacity are still required. See [limitations](docs/CITY_SCALE_LIMITATIONS.md)
and [the current evidence gates](docs/IMPLEMENTATION_STATUS.md).


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
python -m pytest pipeline/tests api/tests -q
cd site
pnpm test
pnpm build
pnpm lint
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
  gate and the GISTDA host did not resolve from the build environment. The city separately provides observed annual water extent, not event depth.
- **Population is a resident baseline**, not a daytime or event-time
  population. Presence comes from scenario activity priors.
- **No external control total is ingested by the run pipeline.** The paper audit
  independently reconciled NSO/DOPA controls for all 50 districts; those counts
  are comparison evidence, not a replacement for modelled or event-time residents.
- **Age bands use admitted per-cell WorldPop 2026 modelled rasters.** Cells
  without valid raster coverage remain explicitly `unknown`; known-band shares
  are conditional on covered cells. The 2026 structure is applied to the 2020
  resident baseline, so the years differ. See the
  [measured coverage gaps](docs/IMPLEMENTATION_STATUS.md#age-structure-enabled-per-cell--north-10-october-2026).
- **Sex split, mobility, warning reach, compliance and preparation delay are
  declared priors**, not measurements.
- **Pilot destinations are hypothetical; city candidates are unverified OSM
  records.** Neither is an operational shelter inventory.
- **At city scale, height is unknown for 250,378 of 272,116 footprints (92.0%).**
  The remaining 8.0% is tagged or derived from `building:levels` at an assumed
  3.0 m per storey. These shares describe the city inventory, not the pilot.

## Product principles

1. A source must be publicly accessible **and** explicitly reusable. A
   `verify` resource can never enter a run; the gate raises before any stage
   starts.
2. Observations, predictions and scenario assumptions stay visually and
   structurally distinct. `source_role` is a required column, not a caption.
3. Manifests record inputs, checksums, seeds, parameters and component versions.
   New runners also record source identity and check for source drift; legacy
   manifests lack that field. This supports auditing, not a blanket replay guarantee.
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
  blocks city-scale depth and evacuation. Copernicus GLO-30 is also excluded:
  its official specification describes a DSM with <4 m absolute vertical
  accuracy, still larger than the signal of interest. An RTARF open LiDAR
  coverage index is now registered, but the underlying elevation tiles and
  their Bangkok coverage have not been obtained.
- **No reusable event rainfall or water-level forcing.** JRC annual observed
  water extent is available, but it has no within-year timing and no depth.
- **No calibrated mobility.** OTP aggregate controls are available and expose
  substantial trip-rate and modal mismatch. The two-mode generator is not
  calibrated; activity, destination and behaviour parameters remain priors.
- **No verified refuge inventory.** Pilot destinations are hypothetical and city
  tags are unverified.
- **No building-level address or entrance network.** Buildings are exposed, not
  entered.
- **One scenario per run.** City closure sensitivities were reproduced; the paper
  separately ran pilot one-at-a-time, seed and sampling checks. Neither is an
  interaction-aware uncertainty analysis. Pilot replay, open-flooded-edge cost
  and weighted-agent semantics still need resolution.

## Attribution and data policy

Downloaded and derived geospatial data are deliberately git-ignored. Every real
input must be recoverable from a source URL, retrieval timestamp, request
parameters and a SHA-256 checksum recorded in the run manifest.

- OpenStreetMap contributors, ODbL 1.0
- WorldPop, CC BY 4.0
