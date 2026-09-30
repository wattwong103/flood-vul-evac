# Implementation status against the plan

**Date:** 30 September 2026
**Scope:** the plan's §16 acceptance criteria and §19 build slice, executed
across two scopes — a 5.96 km² pilot and the 1,643.5 km² Bangkok Metropolitan
Administration — on real, licence-checked open data.

Status vocabulary: **met**, **partly met**, **not met**.

Everything below is `demonstration` status. No run in this repository has been
promoted, and nothing here is a forecast or a warning product.

## What the two scopes are

| | Pilot — Khlong San | City — Bangkok BMA |
|---|---|---|
| Area | 5.96 km² | 1,643.5 km² |
| OSM boundary | relation `R3147280`, admin level 7 | relation `R92277`, admin level 4 |
| Network | 7,514 edges / 6,701 nodes / 169 km | 939,006 edges / 854,628 nodes / 26,744 km |
| Residents | 115,959 | 10,891,061 |
| Buildings in AOI | 2,398 | 255,098 |
| **Flood depth** | scenario (canal-decay) | **not derived** — no defensible DEM |
| **Evacuation** | full state machine | **not derived** — needs depth |
| Observed water | — | JRC Global Surface Water, 4 years |
| Drainage | — | 2,390 km mapped network, 137 basins |
| Hazard screening | — | connectivity under observed water; drainage-discharge index |
| Validation | 17/17 checks | 8/8 checks, 0 manifest schema errors |

The pilot is the only scope with depth and evacuation. The city scope carries
everything that does not require depth.

## §16 acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Scenario, Population, Data Registry, Method views | met | plus Observed & assets, and Run Detail |
| 2 | Population map toggle and day/evening/night | partly met | the three states share one scenario-derived presence curve, not three evidenced profiles |
| 3 | Present and exposed named separately | met | never summed; asserted by an API test |
| 4 | Visible PFLOW stage rail | met | 12 stages in the city run |
| 5 | Registry carries counts, age/sex, control totals, licences | partly met | all registered; **age/sex and control totals registered but not ingested** |
| 6 | Manifest requires population model, version, seed | met | 0 schema errors |
| 7 | Structurally valid person/activity/trip/trajectory/mesh/link/evacuation tables | met | 17/17 pilot checks; 8/8 city checks |
| 8 | Every real input has URL, retrieval time, checksum, licence | met | `source_versions[]` |
| 9 | No real individual traces; aggregation enforced | met | synthetic `p_<hex>` ids, 1 km public grid |
| 10 | Interface labels numeric results as illustrative | met | `validation_status` on every payload |

## Plan exit criteria

**Phase 1 — open-data city baseline, map tiles, source attribution, coverage
dashboard: met at city scale.** A reproducible city run over the whole BMA
exists, with checksums, licence states, and a 1 km public aggregation.

**Phase 2 — flood runs reproducing known extents, calibrated time-to-flood,
demonstrated inter-district differences: partly met.** Extent is comparable
across three independent products and two years; depth and time-to-flood are
not, so no calibration is possible. Inter-district differences are visible in
the drainage index and the connectivity screening.

**Phase 3 — validated, reviewed, operational: not met and not attempted.**

## What each source contributes, and what it cannot

| Source | Role | Cannot give |
|---|---|---|
| OpenStreetMap (ODbL) | network, buildings, water, 1,400 destination candidates | verified refuge capacity, building occupancy |
| WorldPop 2020 (CC BY 4.0) | resident baseline at 100 m | presence at any moment; control totals |
| **JRC Global Surface Water** (CC BY 4.0) | **observed water extent 1984–2021** | depth, duration, flow direction, within-year timing |
| MitrEarth (Chulalongkorn) | mapped flood extent, 2,390 km drainage, basins, overflow paths, 268 villages | DEM accuracy; 2010/2011 extents unusable |
| AWS terrain tiles | — **not used** | ±5–10 m error exceeds the 0–2 m flood-relevant range |
| GISTDA open data (Open Data Common) | registered, reachable, **needs a key** | not ingested |

## Findings this build produced

1. **The 2011 Bangkok flood is invisible in the annual Landsat record.** The
   JRC record shows no anomaly in 2011 (−0.15 km²) and a clear one in 2012
   (+23.7 km²). A flood lasting weeks inside a year cannot be captured by an
   annual composite. This is a property of the observation, not a data gap.

2. **2012 is not reliably the worst year for connectivity.** Closing every
   water-affected way is an assumption. At 100% and 50% closure 2012 is the
   worse year; at 25% it is marginally the better one. The ranking does not
   survive its own sensitivity test, and the code reports
   `year_ranking_stable_across_assumptions: false` rather than asserting a
   winner. The absolute reachable share swings 20 percentage points across the
   assumption range and must be read as assumption-driven.

3. **The MitrEarth DEM is unusable.** +13.8 m at Khlong San where ground is
   1–2 m, with adjacent 30 m samples swinging 5–31 m across a floodplain with
   about 1 m of true relief. Same SRTM lineage as the terrain tiles already
   rejected. Excluded on fitness, independently of the licence decision.

4. **Only 2006 of the three mapped flood-extent years is usable.** 2010 and
   2011 contain self-intersecting rings whose apparent areas are arbitrary; the
   pipeline discards them, derives no area for them, and marks both years
   unreliable. Publishing the 5.0 km² that survived would have been as wrong as
   the 772 km² the broken ring claimed.

5. **Bangkok's flood-relevant topography is 0–2 m.** Any DEM with errors
   larger than that range cannot support a depth model, which is why depth is
   absent at city scale rather than merely uncalibrated.

## Open gaps, in priority order

1. Resolve the RTARF Central Basin LiDAR lead: prove Bangkok coverage, obtain
   the underlying 1 m elevation tiles under explicit reuse terms, identify the
   vertical datum and ground classification, and validate held-out benchmarks.
   The open download currently exposes only a survey-coverage index.
2. Obtain event forcing and validation together: reusable rainfall, river/tide
   levels and time-specific GISTDA or Sentinel-1 flood extent. Terrain alone
   cannot produce a defensible city depth surface.
3. A refuge inventory. Until one exists, no destination may be called a
   refuge and no arrival implies usable shelter.
4. Ingest the already registered DOPA/NSO administrative controls and report
   reconciliation by district without relabelling registered residents as
   people present.
5. Ingest the registered age/sex marginal and preserve its modelled status.
6. Destination capacity by class, as a declared scenario rather than an
   observation.

## Verification

The current verification count is recorded by the test commands at release
time rather than copied into this document. Each run re-validates itself: 17
checks in the pilot, 8 in the city, and the manifest against the committed JSON
Schema.
