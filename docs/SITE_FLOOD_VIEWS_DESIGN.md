# Site flood views — design (BKK-055)

**Status:** design only. Implementation waits for North's approval of this note.

**Date:** 20 October 2026. **Baseline:** `main` at `aca1436` (PR #93).

**Purpose:** add three reader-facing views to the BKK/FLOW site so that a
visitor can see a flood, see whether people can still move, and see which flood
observations the project holds and models with. The paper's story is currently
almost absent from the site; this note closes that gap without loosening any
claim boundary.

## 1. Why

The site has six screens (Scenario lab, Population, Data registry, Method,
Observed & assets, Run detail). Each one shows a single run's artefacts. The
paper's main results — the four-area dry/moderate comparison, sensitivity,
the claim boundary — barely appear, and the site never names Sai Mai, Din Daeng
or Min Buri.

North described what a reader should be able to do, in this order:

1. **See the flood:** "how big, deep the flood is, and can they move or not".
2. **Flood observations:** which flood observations the project has and can use,
   and "we should be modeling using our data too" — replay mapped past floods
   through roads and trips.
3. **Trips cut off:** "where and how commute are cut off".

Past and what-if floods only. A live view during a real flood is out of scope.

## 2. Goals, non-goals and anti-goals

**Goals**

- A reader can answer three questions for any flood shown: how big, how deep,
  can people move (walking and car/motorcycle separately where depth exists).
- A reader can see every flood observation the project holds or has assessed,
  what it marks inside each pilot, how the model uses it and whether it may be
  reused.
- Mapped past floods can drive the model (roads, trips, exits), not only be
  displayed.
- A reader can see which everyday trips inside a district are cut off, how,
  and whether people can still reach the roads that leave the district.

**Non-goals**

- Live monitoring, warning, routing or any real-time feed.
- Real cross-city commutes. They need calibrated city-scale trips
  (BKK-038, BKK-040) and stay future work.
- Changing the paper, the admitted 11 October release or its checksums.
- Calibrating mobility or flood behaviour.

**Anti-goals** (a build that does these has failed, even if it works)

- Observed or mapped water and scenario depth appearing in one layer or one
  colour family.
- Unknown depth or missing coverage shown as zero or as dry.
- An observed or mapped footprint becoming a depth surface.
- Calling the modelled trips "commutes", or implying they leave the district.
- Any citywide connectivity result presented as current before BKK-040 passes.
- Site numbers that a reader could mistake for the paper's Table 4 values.
- Replaying or scoring 2011 outside the pilot AOIs, which would spend the
  event reserved for BKK-036C.

## 3. Constraints this design inherits

- **Run contract** (`docs/RUN_ARTIFACT_CONTRACT.md`). Runs are immutable; the
  site reads only from the API (§6); every numeric result carries
  `validation_status` and model time; observed, modelled and scenario flood stay
  visually distinct; every map has a table view; no endpoint returns a
  person-level trajectory set (§5) — a single trip lookup is the finest grain.
- **Public aggregation:** runs declare
  `projected_square_grid_100m_internal_1000m_public`
  (`pipeline/bkkflow/runner.py:870`). Public neighbourhood shading uses the 1 km
  grid unless North changes that rule.
- **Extent never becomes depth.** The BKK-053 design note (paper folder,
  `analysis/observed-extent-check-design.md` §3) states and tests that observed
  geometry never enters `build_depth_surface` or `build_flood_slices`
  (`pipeline/bkkflow/flood.py:101`, `:208`).
- **Mapped flood positives in the pilots** (same note, update of 20 October):
  GISTDA-derived extents redistributed by MitrEarth, labelled
  `source_role='mapped'` in the source module. PR #94 (open at `aca1436`) marks
  2010 and 2011 reliable alongside 2006 and changes the curated parquet SHA-256
  to `61c911cf…8499`. Share of each pilot mapped as flooded:

  | Pilot | 2006 | 2010 | 2011 |
  |---|---:|---:|---:|
  | Khlong San | 0.0% | 0.0% | 47.6% |
  | Sai Mai | 11.4% | 2.4% | 74.9% |
  | Din Daeng | 0.0% | 0.0% | 0.3% |
  | Min Buri | 27.3% | 12.7% | 54.4% |

- **JRC yearly water:** code 0 covers 86.4–99.6% of every pilot, but since
  BKK-054b code 0 outside the Maximum Water Extent counts as known not-water
  (`pipeline/bkkflow/sources/gsw.py:97`); only 0.8–1.8% of the BMA is unknown
  each year. The unknown share per pilot has not been measured with that
  decoder.
- **MitrEarth display:** BKK-053 D8 (aggregate statistics only) governs journal
  figures and is unchanged. For the public site North decided on 20 October
  that the mapped footprints may be shown (§10, decision 1).
- **Held-out data (BKK-053 D1 and D9(a), decided 20 October):** 2011 is used
  inside the four pilot AOIs and is therefore "seen" there; 2011 **outside** the
  pilots is reserved for BKK-036C. No view may replay or score 2011 outside the
  pilot AOIs. Any further layer used as a model input is spent the same way.
- **GISTDA `disasters-03`:** approved, but whether it is a one-day extent or a
  2011–2023 recurrence product is unresolved. It is no longer needed for 2011.
- **Depth thresholds** (`THRESHOLD_SETS`, `pipeline/bkkflow/flood.py:33`,
  version `bkk-demo-thresholds-v0.1`): walking slows at 0.10 m, halves at
  0.25 m, closes at 0.50 m; car/motorcycle (mode 3) slows at 0.05 m, halves at
  0.15 m, closes at 0.30 m. The moderate preset peaks at 0.55 m.
- **Trips stay inside the district.** The network is clipped to the AOI
  (`pipeline/bkkflow/network.py:176`); destinations are OSM-tagged buildings
  drawn around a target distance of 3.5 km for work, 1.2 km for education and
  0.8 km otherwise (`pipeline/bkkflow/mobility.py:277`); modes are walking and
  one car/motorcycle code (`:340`). The earlier Khlong San prototype
  averaged 1.9 km per trip against 12.6 km in OTP's 2017 survey, and fails the
  mobility control audit.
- **City results:** none may be cited as current until BKK-040 passes. The
  19 October city run `55cc7d9d` is not an admitted city result.
- **Workflow:** tests first, PRs under about 300 changed lines, branch and PR,
  human merge. Contract and schema changes run the full suite.

## 4. What North decided (20 October 2026)

Rough mockups were reviewed in a local browser session; they are not committed.

### 4.1 View 2 — See the flood

Two tabs that never mix: **Past (observed)** and **What-if (scenario)**. Both
show the same three readings as tiles above a map.

| Reading | What-if (four pilots, clock 18:00–22:00, peak 19:00) | Past (citywide years) |
|---|---|---|
| How big | flooded area and share of the district at the selected time | water area seen during the year, shown as a minimum |
| How deep | deepest water; area deeper than 0.30 m (cars stop) | **Unknown** — shown as a dashed tile, never zero |
| Can people move | share of road length open / slowed / closed, separately for walking and car/motorcycle; roads coloured the same way on the map | **Not yet** — needs an admitted citywide run |

- What-if depth uses a hatched purple family; observed water is solid blue;
  "no usable observation" is hatched grey.
- A **depth ruler** beside the what-if map draws the declared thresholds for
  both modes and the scenario peak, so a reader sees why a road closes.
- Past years: 2010, 2011, 2012, 2020 and the 1984–2021 ever-water extent. The
  page states that a yearly layer misses short floods; the registry singles out
  2011, which shows less water than 2020 in this record.
- The Past tab also offers the mapped event extents (2006, 2010, 2011) inside
  the pilot AOIs, in their own "mapped" style, citing MitrEarth and GISTDA.

### 4.2 View 1 — Flood observations, and modelling with them

**Part 1, "What we have":** one row per flood observation held or assessed, with
what it marks inside each pilot (coverage bars where known), how the model uses
it, and its reuse status. Rows: GISTDA mapped extents (2006, 2010, 2011) via
MitrEarth; JRC yearly water;
JRC ever-water; MitrEarth water bodies; GISTDA `disasters-03`; Sentinel-1;
BMA flood-risk and watch list 2023; BMA five-minute water levels and TMD
rainfall (listed, with the reason they cannot be used). This complements the
Data registry screen, which stays the place for every source's licence state.

**Part 2, "Modelling with our data":** replay a mapped past flood through the
model. The footprint closes every road it touches, for every mode alike,
because it carries no depth. The result reads like view 2 (how big; depth
Unknown; road length closed) and its cut-off trips feed view 3. A replayed flood
has no clock. North reviewed this with 2006 as the only replayable year and
2011 waiting on `disasters-03`; the BKK-053 update supersedes that. Replayable
inside the pilot AOIs only: 2006 in Sai Mai and Min Buri; 2010 in Sai Mai and
Min Buri; 2011 in Khlong San, Sai Mai and Min Buri (2010 and 2011 once PR #94
merges). Din Daeng has almost no mapped flood in any year (0.3% in 2011) and
shows that fact rather than a replay.

### 4.3 View 3 — Trips cut off, and can people get out?

Scope B: everyday trips **inside the district**, plus whether people can still
reach the roads that leave it. Works with what-if floods (with the clock) and
replayed floods (static).

- **Trips:** each routed trip is checked against the roads closed or slowed
  when it departs, then classed **unaffected**, **detour** (with extra minutes)
  or **no route**. Breakdowns by mode and by the model's own purposes
  (work, education, shopping and services, health care, social and recreation).
  A ranked list shows the closed road segments that cut the most trips, each
  with the depth and threshold that closed it.
- **Exits:** an exit is a point where a mapped road crosses the district
  boundary, shown as open, slowed or closed. Each neighbourhood is shaded by
  whether its people can reach an open exit directly, only the long way round,
  or not at all. Headlines: exits still open; share of people present who can
  reach one on foot; the same by car/motorcycle, counted only over people whose
  mobility profile gives vehicle access. The page states that reaching
  an exit says nothing about the road beyond it.
- A standing caveat: synthetic, uncalibrated trips that stay inside the
  district.

## 5. Proposed implementation (for review)

### 5.1 View 2 summary — API only

The three readings can be derived from existing artefacts (`flood_slices`,
`edge_states`, `network_edges`), so no pipeline stage is needed.

- `GET /v1/runs/{id}/flood-summary?time=` returns, per model time: flooded
  area and its share of the AOI; maximum depth; area above each mode's closing
  depth; and per mode the edge length open, slowed and closed. Every value
  carries `source_role`, threshold set version and `validation_status`.
  Past-year depth and movement are returned as null with a reason, never
  omitted.
- "Flooded area" uses a fixed **0.15 m flood-area threshold** defined in the
  summary itself, not the cohort's `exposure_threshold`, which is 0.0 on dry
  runs (`pipeline/bkkflow/runner.py:702`) and would count every dry cell. It is
  0.15 m rather than any depth above zero because the BKK-053 note shows "any
  depth" covers 89–100% of every pilot. A dry run reports 0 km² flooded with
  the reason "declared dry scenario", which is a scenario value, not missing
  data.
- Past tab: the yearly water area is decoded with the BKK-054b share decoder.
  The ever-water extent is used today only as a share denominator and has no
  route (`pipeline/bkkflow/city_runner.py:122`), so BKK-055c also adds a small
  endpoint for it. "How big" for a past year reports seasonal and permanent
  water separately, headlining seasonal water as a minimum and stating that it
  includes paddies and ponds.

### 5.2 Replay of a mapped or observed extent — pipeline

- New flood source kind `extent_replay`, chosen by configuration, with a
  registry id, a year and the pinned curated-parquet SHA-256. It must refuse a
  source whose registry status is not `approved`, a year not marked reliable,
  any geometry outside the pilot AOI (D1), and a missing or unreadable layer.
  A pilot where the layer has no positives returns a null result with a reason.
- Edge closure is a **new vector-footprint function**. It borrows the
  along-edge sampling idea of `edges_in_water`
  (`pipeline/bkkflow/observed_evac.py:200`) but cannot reuse it: that function
  samples the citywide JRC raster for one year, loaded for the `bangkok-bma`
  AOI, not a vector footprint. Its `None` branch (`:210-213`) also treats an
  absent mask as "nothing closed"; the replay function must refuse instead.
- Replay closures are **static**: an edge touching the footprint is closed for
  every mode for the whole day, so every trip evaluated in §5.3 sees the same
  state. `edge_states` for a replay run hold one row per edge and mode with
  `time_s = null`, `depth_m = null` and a reason code naming the source and
  year. `GET /v1/runs/{id}/links` serves them without a time parameter and says
  the run is static.
- Footprint cells are written with `source_role = mapped` and null depth. This
  is a contract change: `mapped` joins the `flood_slices.source_role`
  vocabulary (`docs/RUN_ARTIFACT_CONTRACT.md:110`, currently `observed,
  modelled, scenario`) and `depth_m` becomes nullable for replay runs. It needs
  a schema version bump and the full suite.
- The API contract changes too. `GET /v1/runs/{id}/flood` currently returns
  "positive-depth flood cells" (`docs/RUN_ARTIFACT_CONTRACT.md`, §5), so a
  null-depth footprint would never reach the site. For replay runs it returns
  the footprint cells with `source_role = mapped`, `depth_m = null`, no time
  parameter, and the MitrEarth and GISTDA attribution and permitted-purpose
  statement from the registry (§10, decision 1). The contract's §5 row and
  §6 rule 2 are updated in the same PR, and an API test covers a replay run.
- Replay runs skip cohort selection and evacuation, because cohort selection
  needs a depth surface (`pipeline/bkkflow/runner.py:702`). They publish those
  outputs as null with a reason, as city runs do for depth. People, trips,
  trip outcomes and exits run as normal.
- A regression test asserts the footprint never reaches `build_depth_surface`
  or `build_flood_slices`.
- The manifest records the replay source, year, parquet hash, registry status
  and the D1/D9 "seen" status.

### 5.3 Trip outcomes — pipeline

- New artefact `trip_outcomes.parquet`: `trip_id, mode, dest_purpose,
  depart_time_s, origin_cell, outcome, dry_time_s, flood_time_s,
  extra_time_s, blocking_edge_id`. `outcome` ∈ `unaffected, detour, no_route,
  not_routed_dry`. Trips that had no route in dry conditions are counted
  separately, never as flood effects.
- Method: compare each routed trip's dry route with `edge_states` at its
  departure time for its mode (the static state for a replay). If nothing on
  the route is closed or slowed it is unaffected; otherwise re-route on the
  mode graph at that time. Closed edges are removed; slowed edges stay, with
  travel time divided by their `speed_multiplier`. A slower or longer route is
  a detour; no route is `no_route`. Reuse the existing routing
  graph and `route_trips` (`pipeline/bkkflow/mobility.py:402`) rather than a
  second router.
- Aggregates for the API: outcome shares by mode, purpose, time window and
  public 1 km cell; and per closed edge, the weighted trips whose dry route
  crossed it and that ended as detour or no route.
- Denominators: for a what-if flood, trips departing inside the flood window
  (18:00–22:00); for a replay, all trips of the day. Every share states its
  denominator.

### 5.4 Exits and exit access — pipeline

- Exits are the network nodes created where the AOI clip cuts an edge. Each exit
  takes the state of its adjacent edge per mode and time: open, slowed or
  closed. Open and slowed exits both count as reachable exits; slowed ones are
  flagged as such.
- Exit access: a multi-source shortest path from all reachable exits per mode
  and time, using the same impedance rule as §5.3 (closed edges removed,
  slowed edges kept at their reduced speed). Each 100 m cell gets its travel
  time to the nearest reachable exit, compared with the dry time. Classes: **direct**,
  **long way round** (more than 1.5 times the dry time), **no open exit**.
  Published at the 1 km public grid, weighted by people present at the selected
  time for a what-if flood, and by the resident baseline for a replay, which
  has no clock. Car/motorcycle access is computed only for people with vehicle
  access.
- New artefacts `exits.parquet` and `exit_access.parquet`, plus contract text.

### 5.5 Observation catalogue

- Add a `flood_observation` block to each relevant registry entry: what it
  measures, cadence, temporal coverage and model use (`replay input`,
  `plausibility check`, `mask`, `context`, `none`) with the reason.
- Per-pilot coverage is computed by a script into a generated, Git-ignored
  inventory with source hashes, not typed into the registry.
- `GET /v1/observations` joins the two. Coverage that was never measured is
  returned as null, not zero.

### 5.6 Site

- Three new screens, placed first in the navigation: **The flood**,
  **Trips cut off**, **Flood observations**. The existing six stay unchanged.
- Each screen follows the website contract: labels, model time, Bangkok frame
  with pilot extent, and a table view for every map.
- View 3 never draws individual trips. Outcomes are shown by 1 km cell and by
  closed edge; an optional single-trip example uses the existing one-trip
  lookup granularity.

## 6. Which runs the views show

The trip, exit and replay outputs do not exist in any current run, and the
admitted 11 October release cannot be changed. Options:

**Decided by North, 20 October: option 1.**

1. **New demonstration runs** from the new code for each pilot
   (dry, moderate, and replay where the 2006 layer has positives), audited and
   published like other runs, and labelled on every screen as separate from the
   paper's release.
2. **Derived bundles** over existing immutable runs, stored outside each run
   directory with the source run's identity and hashes. This would later allow
   the admitted release once BKK-047 exposes it, but needs a new
   derived-artefact contract.
3. **Wait for BKK-047**, which is blocked on BKK-044.

## 7. Ordered tasks

Each task is one branch and one PR, tests first.

| Task | Content | Depends on |
|---|---|---|
| BKK-055a | This design note and the `tasks.md` rows | — |
| BKK-055b | API `flood-summary` endpoint (§5.1) | 055a |
| BKK-055c | Site: The flood screen (§4.1) on existing runs | 055b |
| BKK-055d | Pipeline: trip outcomes (§5.3) and contract text | 055a |
| BKK-055e | Pipeline: exits and exit access (§5.4) | 055d |
| BKK-055f | API: trip-outcome and exit aggregates | 055d, 055e |
| BKK-055g | Site: Trips cut off screen (§4.3) | 055f |
| BKK-055h | Pipeline: extent replay (§5.2), schema bump, full suite | 055a; PR #94 for 2010/2011 |
| BKK-055i | Observation catalogue (§5.5) | 055a |
| BKK-055j | Site: Flood observations screen with replay panel (§4.2) | 055h, 055i |
| BKK-055k | Produce, audit and publish the demonstration runs (§6) | 055d, 055e, 055h |

BKK-055b/c can start in parallel with 055d; 055h and 055i are independent of the
trip work.

## 8. Where this could go wrong

- **Paper and site disagree.** New runs give different numbers from Table 4.
  Mitigation: every screen names its run, commit and status, and says it is not
  the paper's release.
- **Replay read as observed depth.** Mitigation: null depth in the data, a
  dashed "Unknown" tile, and the regression test in §5.2.
- **Exits read as a safe way out.** Mitigation: the page states that the road
  beyond the boundary is not modelled.
- **2011 read as the whole 2011 flood.** Mitigation: past areas are labelled as
  minimums with the reason.
- **Public cells too coarse.** Khlong San is about six 1 km cells; neighbourhood
  shading may say little there. See §9.

## 9. Calls made in this note

These were not discussed with North and a builder may revisit them:

- "How big" uses a fixed 0.15 m flood-area threshold, separate from the
  cohort's exposure threshold (§5.1).
- Slowed roads stay routable at reduced speed, and slowed exits count as
  reachable (§5.3, §5.4).
- Replay closures are static for the whole day (§5.2).
- "Long way round" means more than 1.5 times the dry travel time.
- Trip outcomes compare against the trip's departure time only, not each edge's
  state when the traveller reaches it.
- Navigation names and placement in §5.6.
- Neighbourhood shading uses the public 1 km grid.
- Past "how big" headlines seasonal water as a minimum, with permanent water
  shown separately (§5.1).
- Trip-outcome denominators: the flood window for what-if floods, the whole day
  for replays (§5.3).
- Exit access weights people present (what-if) or residents (replay); vehicle
  access only for people with a vehicle profile (§5.4).
- Replay runs skip cohort selection and evacuation and publish them as null
  with a reason (§5.2).
## 10. Decisions by North (20 October 2026)

1. **MitrEarth footprints on the public site: allowed.** D8 (aggregate
   statistics only) was written for journal figures and still governs them. On
   the site, the mapped footprints, the roads they close and the 1 km shading
   may be shown, citing MitrEarth and GISTDA, under the registry's
   permitted-purpose terms (social benefit, teaching and disaster response).
2. **Runs: option 1 (§6).** New demonstration runs from the new code, labelled
   on every screen as separate from the paper's 11 October release.
