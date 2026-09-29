# Implementation status against the plan

**Date:** 30 September 2026
**Scope of this build:** the plan's §19 immediate build slice and §16 acceptance
criteria for the first integrated prototype, executed on a real pilot area with
real open data.

Status vocabulary: **met**, **partly met**, **not met**, **not attempted**.

## §16 acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Site contains Scenario, Population, Data Registry and Method views | met | `site/src/screens/{ScenarioLab,Population,DataRegistry,Method,RunDetail}.tsx` |
| 2 | Population toggles on the map, switches day/evening/night | partly met | Map layer and time-of-day control exist; the three states share one scenario-derived presence curve rather than three separately evidenced profiles |
| 3 | Scenario metrics name people present and people exposed separately | met | `stats.json → population.people_present / people_exposed`; never summed |
| 4 | Visible PFLOW stage rail connecting population → activities → trips → trajectories → flood evacuation | met | `run_state.json → stages[]`, rendered in Run Detail |
| 5 | Registry includes resident counts, age/sex and administrative control totals with licences | partly met | All registered with licences; **age/sex and control totals registered but not ingested** (licence/scope), and the registry states this per source |
| 6 | Run manifest requires population model, population version and seed | met | `schemas/pflow-bkk-run.schema.json`; 0 schema errors on the published run |
| 7 | A sample run produces structurally valid person, activity, trip, trajectory, mesh, link and evacuation tables | met | 17/17 validation checks pass; 14 artefacts written |
| 8 | Every real input has source URL, retrieval time, checksum and licence snapshot | met | `manifest.json → source_versions[]` (4 entries) |
| 9 | Public output contains no real individual trace and enforces aggregation rules | met | Synthetic `p_<hex>` ids; `privacy.no_real_identifiers` check; 1 km public grid configured |
| 10 | The interface labels all current numeric results as illustrative | met | `validation_status` carried in every API payload and rendered on the site |

## What the run actually produced

| Quantity | Value | Provenance |
|---|---|---|
| Resident baseline (weighted) | 115,959 | WorldPop 2020, real, window-clipped, checksummed |
| People present at 18:00 | 102,878 | Scenario activity priors over a 1,200-agent weighted sample |
| People exposed (≥0.15 m) | 89,527 (87.0% of present) | Scenario depth surface |
| Evacuation cohort | 89,527 | Present ∧ exposed ∧ in order area |
| Ways closed at peak | 1,002 of 7,514 | Mode-specific depth thresholds |
| Buildings with scenario water | 2,177 of 2,398 | Footprint sampling |
| Clearance time | see `report/SUMMARY.md` | Uncalibrated priors |
| Destinations | 3, **all hypothetical and unverified** | No refuge inventory exists |

## Deviations from the plan, and why

1. **No external control total was ingested.** The DOPA/NHA subdistrict CSV was
   not retrievable within the agreed AOI-scoped data budget. Control error is
   therefore reported as `unavailable` rather than passing silently. The
   reconciliation code path exists, is unit-tested, and has never run against
   real controls — so it should be exercised before it is relied on.
2. **No age/sex rasters.** Country-wide age/sex surfaces were out of the agreed
   budget. `age_band` is `unknown` for every person.
3. **No observed flood layer.** The GISTDA host did not resolve from the build
   environment. Depth is a declared scenario.
4. **No terrain model.** The highest-value gap. Without elevation the depth
   surface is distance-to-water only and cannot represent inland basins.
5. **Open Buildings 2.5D was not ingested.** The delivery route requires an
   authenticated bucket. Height therefore comes from OSM tags and levels only,
   covering 3.1% of AOI footprints. This is why the height coverage warning
   fires on every run.
6. **Sex split is a prior**, since the subdistrict sex control was not ingested.

## Bugs the test suite caught in pipeline code

These were found by `pipeline/tests`, not by inspection, and each would have
corrupted a result:

- `reconcile_to_controls` referenced a `factor` column it never created — it
  would have crashed on first use with real controls. The path had never been
  executed because no controls were ingested.
- Closed highways arrive from Overpass as `LinearRing`, not `LineString`, so
  they were silently dropped from the network (74 ways in the real extract).
- `linemerge` raises when `unary_union` returns a bare `LineString`.
- The routing graph collapses parallel ways, so removing a closed edge after
  the fact deleted connections that were still open on another way.
- The cohort depth lookup applied the WGS84→analysis transform in reverse.

## Next acquisitions, in priority order

1. **Terrain/DEM** — unlocks a real depth model and removes drainage blindness.
2. **Rainfall and river-stage forcing** that passes the two-part licence gate.
3. **GISTDA or Sentinel-1 observed extent** — converts `source_role` from
   `scenario` toward `observed` and enables real validation.
4. **An administrative control total** (DOPA/NHA) to close the population QA gap.
5. **An age/sex marginal** and a **refuge inventory** — the two remaining
   fields that must never be invented.
6. **Sensitivity ensemble execution** over the declared severity × compliance
   matrix.
