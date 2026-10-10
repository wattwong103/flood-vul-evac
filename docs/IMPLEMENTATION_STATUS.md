# BKK/FLOW project state

Updated 10 October 2026. **DONE_WITH_CONCERNS; demonstration only.**
This page is the shared implementation/evidence handoff. Internal validation
does not establish empirical validity or operational readiness.

## Current source and release status

Current `main` is merge commit `21c6841d238c62a6e451097fefeb683e9ae7afad`
with source tree `23a072809fb6f319fbbf7f6c3461436a82deefab`.
Four human-merged PRs establish the present four-area implementation boundary:

- [PR #49](https://github.com/wattwong103/flood-vul-evac/pull/49) landed the
  reviewed 43-commit four-area, denominator, replay-audit and report stack.
- [PR #50](https://github.com/wattwong103/flood-vul-evac/pull/50) preserved
  full-precision saved network WKT under the unchanged `1e-6 m` replay tolerance.
- [PR #51](https://github.com/wattwong103/flood-vul-evac/pull/51) made the
  independent replay sum original terminal outcome records rather than rounded
  state subtotals, while retaining exact contract equality and the unchanged
  `1e-6` conservation tolerance.
- [PR #53](https://github.com/wattwong103/flood-vul-evac/pull/53) closed the
  BKK-021F named-pilot identity/traversal regression matrix as tests-only
  coverage, with no production, configuration or method change.

This source is implemented and reviewed; it is not an accepted comparative
release. The [four-area contract](MULTI_AREA_PLAN.md) remains authoritative.
The first release attempt stopped on saved-WKT precision. Its two Khlong San
bundles are immutable negative evidence. The second attempt stopped on the
Din Daeng denominator replay after completing five of eight planned bundles.
Those five bundles and their eight-ID plan are also immutable negative evidence;
they cannot be pooled with a later release even though the preserved Din Daeng
bundle passes read-only replay under the corrected #51 source.

No complete, common-boundary eight-run set has been executed or accepted.
Both named pre-release regression gates are now merged or proposed as
tests-only change: the named-pilot identity/traversal matrix through #53, and
the pipeline-to-saved-artifact-to-both-API fractional-seconds round-trip
regression on branch `task/api-fractional-roundtrip`. Once that second gate
merges, the precondition is to freeze one merged
source/configuration/environment boundary, issue eight new run IDs and audit
all eight runs plus all four pairs. Until that happens, no four-area numerical
result is approved for the paper.

## OSM source re-freeze, 10 October 2026 — city numbers superseded

Approved by North on 10 October 2026 after the staging blocker fired.

The four-area contract admitted `geofabrik-thailand-osm-20260929`. On
10 October its dated publisher URL `thailand-260929.osm.pbf` returned **404**,
so the admitted source was no longer publicly retrievable and staging all four
AOIs failed at the licence gate. Independently, the local city cache had in
fact been built from the **BBBike** Bangkok extract, which the registry already
described as an incomplete city rectangle.

The source is now re-frozen on **`geofabrik-thailand-osm-20261009`**:

| Item | Value |
|---|---|
| Dated URL | `https://download.geofabrik.de/asia/thailand-261009.osm.pbf` (never the rotating `-latest` alias) |
| Size | 328,454,828 bytes |
| SHA-256 | `013730abb5ccf132631ff964947671efd09e642880518ec5d15d9366ec877d00` |
| Coverage polygon | `thailand.poly`, SHA-256 `a0ac1e0a8f1de80356a7c92684cd6d8f068eb4ef4ae84ad3288134e63b1e72c7` |
| Licence | ODbL 1.0, unchanged |

The withdrawn `20260929` entry is kept with `status: verify` — not deleted —
because frozen configurations and published manifests reference it by id. It
can no longer enter a run.

### The BBBike extract was materially incomplete

Rebuilding the city cache from the admitted source changes the network and
building inventory by a large margin:

| Layer | BBBike cache (was) | Geofabrik 261009 (now) | Change |
|---|---:|---:|---:|
| Road ways | 235,678 | 403,830 | **+71%** |
| Buildings | 272,116 | 427,580 | **+57%** |
| Water features | 4,681 | 7,144 | +53% |
| Modelled residents | 10,891,061 | 10,891,061 | unchanged |

**Consequence: the historical city run `be6a4e08-e2d7-4dd9-bf8b-4f2a02a12a81`
and every number derived from it — including the README's city table and the
76.1429 km² unreconciled-area figure — were computed on a source now known to
be materially incomplete. Those figures remain true statements about that
immutable run; they must no longer be presented as current city results.**

A new city run on the re-frozen source has **not** been executed. Until it is,
the city layer has no current result. The README city table still shows the
superseded BBBike-derived numbers and must not be cited.

### Pilot layer is unaffected and fully staged

All four frozen AOIs were re-derived from the admitted extract. Boundary areas
and geometry hashes are **byte-identical** to the 2026-09-29 extract, so the
frozen four-area contract survives the re-freeze intact — only the network
source hash moves.

| AOI | Relation | Area km² | Coverage | Stage |
|---|---|---:|---|---|
| Khlong San | R3147280 | 5.9607 | contained | `complete` |
| Sai Mai | R2938035 | 43.3383 | contained | `complete` |
| Din Daeng | R2938031 | 8.4589 | contained | `complete` |
| Min Buri | R3146413 | 59.9852 | contained | `complete` |

All four carry `source_sha256.osm = 013730ab…` and report
`EPSG:32647`. The pilot path is provenance-clean: each boundary is re-read from
the PBF by relation id and hash-verified.

**Separate gap, city layer only:** `data/curated/aoi/bangkok-bma.provenance.json`
records `source_id: null`, `resource_url: null` and `osm_relation_id: null`. The
BMA AOI polygon used to clip the city extract has no recorded origin and was
**not** re-derived from the admitted source. The pilot path does not depend on
it. Re-deriving it would move the city geometry again and is a North decision.

Full Python/API suite with #55 merged in: **346 passed, 6 failed** — the same six
pre-existing `test_city_endpoints.py` failures recorded below, unchanged by the
re-freeze. Measured on the #56 branch alone the count is 344, because #55's two
new round-trip tests are not present there.

## Historical city-scale implementation and verified run

[PRs #1–#14](https://github.com/wattwong103/flood-vul-evac/pulls?q=is%3Apr+is%3Amerged)
were human-merged by 4 October. Historical main at `9278893` has source tree
`07708a7f72ae62832bcd00de6b9771df3da1bb6a`, matching tested commit
`a5dfc51c59df65a27e136cbce594d73e09179181`.

Immutable city run `be6a4e08-e2d7-4dd9-bf8b-4f2a02a12a81` executed entirely
at that commit on 4 October: 831 seconds, 8/8 internal checks, zero schema
issues and 12/12 recorded output hashes verified. Source identity is external
evidence for this historical run, not a field retrospectively added to its manifest.
The source-matched test gate was 212 Python/API and 14 frontend tests; build and
lint passed, with 11 existing lint warnings. No GitHub CI checks are configured.

| Result | Verified value | Interpretation |
|---|---|---|
| Network | 1,038,811 edges; 949,151 nodes; 30,060.16 km | Complete source extent; OSM completeness is unverified. |
| Buildings | 272,116; 250,378 unknown height | Tags/levels do not establish structural safety. |
| Population | 10,891,061.3023; 181,662 source cells | Modelled 2020 residents, not people present during a flood. |
| Public population grid | 1,693 cells, 1 km | Coarse aggregation, not building occupancy. |
| Destinations | 1,034 candidates; zero verified | No usable capacity or safe-access guarantee. |
| Annual water | 157.8473 / 170.7147 / 143.4223 / 173.7170 km² | 2010 / 2011 / 2012 / 2020; about 83% no-observation area. |
| Depth / city evacuation | Not computed, null with reasons | Terrain, forcing and validation gates remain open. |

The [README](../README.md#conditional-connectivity) records all 12 independently
reproduced closure cases. Fixed baseline anchors, 400 m snapping and a 180 minute
limit are disclosed. Reopening is monotonic, but the worst-ranked year changes
with the closure fraction. Travel percentiles are unweighted reachable-cell
summaries, not clearance times. Vehicle one-way restrictions remain unenforced.

The earlier 114–138 km² JRC table, 2012 anomaly, “2011 flood absent” claim,
939,006-edge city inventory and roughly 71% reachability figures are withdrawn.
Older immutable runs remain historical evidence, not the current baseline.

## Historical BKK-009 concern-fix sequence

The [BKK-009 plan](CONCERN_RESOLUTION_PLAN.md) records this completed historical
sequence. These changes were subsequently merged. They do not alter or become
part of the older city runs attributed above.

| Task | Implemented change | Evidence / remaining limit |
|---|---|---|
| BKK-010 | One definition of grid size, snap tolerance and routing cutoff | 43 targeted tests; numerical method unchanged. |
| BKK-011 | Shared WorldPop URL, explicit missing-source and cross-drive diagnostics | 14 source tests; original hashes/retrieval gates retained. |
| BKK-012 | Private index build, atomic installation without replacement | 13 index/API tests, including interruption, competing writer and incompatible version. Filesystem must support hard links. |
| BKK-013 | Statistics gate and actual validation-check display | 17 frontend tests and production build; missing statistics are explained, stale-run map details hidden. |
| BKK-014 | Source identity in new manifests; detected drift blocks publication | Source-change, Git-unavailable, schema and immutable-pilot tests. Before/after checking cannot detect a transient edit restored between checks or freeze installed dependencies. |

Independent review and final combined verification are recorded in the linked
PR descriptions. Generated runs and data stay outside Git. The app serves real
saved artifacts; it does not fabricate absent hazard or capacity fields.

Final combined verification on 4 October passed 230 Python/API tests and 17
frontend tests; production build and lint passed (11 existing lint warnings).
Fresh city run `4ecad6e0-c072-46e5-b818-6c4f3f259eaf` completed in 857.3 seconds
at source `0ecf18a2107631a23442da3c3274cea3dbe6507d`, tree
`638ba97c225669cc759992f333e8b70c6d59cb4f`. Its manifest records clean scoped
source and `matched_before_publication`, with source digest
`6e5fd057a252eab56a3400868a7ef0f1d7226ab6649cda6c49fc0d3aa56d24eb`.
It passed 8/8 internal checks with zero schema issues. This is a new run;
the historical evidence above remains attributed to its original source.
Later README/status edits only document this result and correct city height
coverage to 92.0% unknown; they do not change the executable source.

## External evidence now available

The paper audit staged and independently reconciled the official
[NSO/DOPA registration dataset](https://data.go.th/dataset/0405_01_0005).
Rechecking its 15,090-row CSV on 4 October reproduced zero reconciliation error:

| Year | Registered Bangkok population | Districts | District sum minus city total |
|---|---:|---:|---:|
| 2021 | 5,527,994 | 50 | 0 |
| 2022 | 5,494,932 | 50 | 0 |
| 2023 | 5,471,588 | 50 | 0 |
| 2024 | 5,455,020 | 50 | 0 |
| 2025 | 5,422,568 | 50 | 0 |

Source CSV SHA-256:
`7c24d89223d0709df54baa65f84bd3149fd2d26feeef252b83361237ad372a5a`.
These are registration controls, not event-time population. Pipeline ingestion,
boundary matching and choice of population concept remain separate work.

The [OTP survey report](https://www.otp.go.th/uploads/tiny_uploads/ProjectOTP/2560/Projcet01/2.2-TDS_Exsum_EN_Final_20180515.pdf)
provides a 2017 control of 1.97 trips/person/day. The paper's legacy pilot audit
found 3.712, plus missing modal alternatives. This rejects a calibrated-mobility
claim; post-hoc multiplication alone cannot repair mode/destination behaviour.

## Remaining concerns, acceptance gates and owners

Owners below identify the next role; no external organisation has accepted an
assignment or been contacted on the project's behalf.

The earlier BKK-015 flooded-cost, fixed-cohort, weighted-quantile and denominator
defects are closed in merged source through #49. The two release-discovered
serialization and replay-summation defects are closed in merged source through
#50 and #51. These source closures do not retroactively validate either failed
release attempt.

| Severity / task | What remains | Next owner and acceptance gate |
|---|---|---|
| CLOSED MEDIUM BKK-021F named-pilot identity | Rejection matrix for configured AOI identity, direct traversal IDs and missing scoped inputs is covered by #53 | Merged tests-only coverage; bounded to the named cases, not exhaustive identity hardening. Three LOW follow-ups are parked in the PR description. |
| CLOSED MEDIUM API fractional-seconds round-trip | A real publication now survives saved Parquet/manifest readback through both clearance routes with fractional event seconds, with the canonical non-null denominator contract | `api/tests/test_publication_roundtrip.py` (#55, pending merge). Recomputes the weighted-clearance definition independently rather than calling the pipeline helper; verified to fail on both whole-second truncation and absolute-event-time regressions. No production change: the pipeline and both routes were already correct. |
| MEDIUM BKK-024 release evidence | No complete eight-run set exists. Staging precondition is now **satisfied**: all four AOIs staged `complete` on the re-frozen `geofabrik-thailand-osm-20261009` source. | North + implementer: both pre-release gates are now covered, so freeze one code/config/environment bundle, create eight new IDs, execute all pairs and pass all run and pair audits. |
| HIGH city result superseded | Every city number, including the README city table and the 76.1429 km² unreconciled-area figure, was derived from the BBBike extract now known to be ~57–71% incomplete. No city run exists on the re-frozen source. | North + implementer: decide whether to re-run the city baseline on `geofabrik-thailand-osm-20261009`, and resolve the unattributed `bangkok-bma` AOI polygon first. Until then the city layer has **no current result** and its README numbers must not be cited. |
| MEDIUM BKK-009 boundaries | 76.1429 km² of the BMA lies outside the 50 OSM district union; cause unverified | Data steward + North: acquire authoritative geometry with reuse terms and reconcile the difference. The [BMA 50-district catalog](https://data.go.th/en/dataset/50) currently says “License not specified,” so it is a lead, not an admitted input. |
| MEDIUM BKK-009 population | Controls audited, not ingested or concept-matched | North selects resident/registered/de-facto target; implementer adds district crosswalk, date matching and reconciliation tests. |
| HIGH scientific gate: terrain/event | Actual bare-earth tiles, datum, forcing and held-out validation absent | Data steward: pursue [RTSD LiDAR catalog](https://data.go.th/en/dataset/lidar-1) and [GISTDA event extent](https://opendata.gistda.or.th/th/dataset/disasters-03). A coverage index or extent product is not depth. |
| HIGH scientific gate: destinations | No verified capacity, operator, accessibility, inspection date or flood-safe access | North/data steward: obtain district/operator records through [BMA NOW](https://now.bangkok.go.th) and institutional channels; record reuse terms and retrieval evidence. |
| MEDIUM BKK-016 calibration/uncertainty | Two-mode priors, weighted-agent draws and one-at-a-time sensitivity | Scientific owner: define OTP target population, modes/purposes/distributions, weighted-agent interpretation and interaction-aware uncertainty before calibration claims. |
| MEDIUM BKK-017 driving | City routing is undirected | Implementer: preserve one-way/access restrictions and test direction before publishing vehicle results. Current reported screen is pedestrian. |
| MEDIUM BKK-018 failed-run visibility | New source-tracked runs are intentionally hidden until published; manifest-bearing failures appear in API `skipped`, but the warning lacks the failure reason | Implementer: expose operator-facing failure state/reason without serving unfinished scientific results. Runs without a manifest still require local diagnostics. |
| LOW BKK-019 display consistency | City stage table is complete, but the rail uses pilot stage names; an error phase with no error object would display loading | Implementer: use scale-specific stage names and preserve the error-state invariant. Current statistics hook supplies an error object on failure. |
| LOW maintenance | Repeated viewport counts, visibility-toggle refetches, anchor-loop performance, existing lint warnings | Implementer: profile first; preserve public-layer completeness and method semantics. |

## Handoff and use

North owns review and merge. The paper session owns manuscript and figure edits;
it has the historical immutable city run, its exact numbers, source tree and
caveats. Implementation changes do not automatically replace paper results.
No four-area number is handed to the paper until the new eight-run release gate
passes. Historical evidence and fresh verification are separately identified in
every PR handoff.

Run `python -m pytest pipeline/tests api/tests -q`, then `pnpm test`, `pnpm build`
and `pnpm lint` from `site/`. Record the actual output and run UUID when promoting
any new evidence. Internal success alone never promotes a run beyond demonstration.

### Known pre-existing test failures, 10 October 2026

The combined suite currently reports **346 passed, 6 failed, 0 errors** on this
machine. All six failures are in `api/tests/test_city_endpoints.py` and are
unrelated to the fractional-seconds work. They reproduce with that test file run
alone, with no other change present.

They have **one cause: the selected run is stale.**

`_city_run_id()` in `api/tests/test_city_endpoints.py` selects the newest run
holding `observed_water.json` + `manifest.json`, which resolves to
`784ffce7-7ee0-4af8-8a49-2e9844dd487a`. That run predates later pipeline work:

| Evidence | Detail |
|---|---|
| Its `observed_water.json` was retrieved | `2026-09-30T13:20:15Z` |
| Current note wording introduced by | `1455bf0`, **2026-10-01** |
| `observed_water_cells.parquet` in the run | **absent** |
| `observed_water_cells.parquet` in `data/curated/city/` | present, 140 KB |

`pipeline/bkkflow/sources/gsw.py:295-302` already emits both phrases the
wording test requires — `"Annual water classes are not event-flood extent…"`
and `"…no observations is not dry land."` **The code is correct; the run
predates it.** The test must not be relaxed to match stale output.

The five artefact failures share that root cause, and falling back to the shared
cache would be wrong by design: `api/app.py:1619` states *"this run has no
immutable observed-water cell snapshot; regenerate the run"*, and
`api/tests/test_api.py:175-187` deliberately plants a cache file belonging to a
*different* run and asserts the selected run's own snapshot wins.

**Fix: regenerate the city run.** One action resolves all six failures *and*
replaces the BBBike-derived city numbers with ones from the re-frozen Geofabrik
source, so it must happen before any evidence is promoted.

That the fix works is verified from the code, not assumed. `city_runner.py`
writes all three missing artefacts into the run directory and registers each as
a manifest output:

| Output | Written by | Registered at |
|---|---|---|
| `observed_water_cells.parquet` | `build_observed_cells.build(out_dir=run_dir)` | `city_runner.py:666` |
| `destinations.parquet` | `destinations_source.extract_destinations(out_dir=run_dir, …)` | `city_runner.py:307`, `:672` |
| `observed_water.json` | current `gsw.py` notes | `city_runner.py:673` |

A fresh run therefore carries its own immutable snapshots and the current note
wording, which is exactly what the five artefact tests and the wording test
require.

Recording this correctly matters. An earlier revision of this note attributed
the six failures to two independent causes and proposed changing run selection.
That was wrong, and that change would have broken the per-run snapshot contract.

DONE_WITH_CONCERNS
