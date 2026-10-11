# BKK/FLOW project state

Updated 11 October 2026. **DONE_WITH_CONCERNS; demonstration only.**
This page is the shared implementation/evidence handoff. Internal validation
does not establish empirical validity or operational readiness.

> **Current snapshot.** PRs #73--#76 are merged. The authorised replacement
> four-pilot release was freshly staged and executed from clean merged commit
> `db0a96b`; all eight runs, eight saved-run replays and four fixed-cohort pair
> publications pass. Its external root/ledger/ZIP passed independent admission.
> Exact source, run, metric and archive identities are in
> [`RELEASE_EVIDENCE_2026-10-11.md`](RELEASE_EVIDENCE_2026-10-11.md) and the
> current [`HANDOFF_2026-10-11.md`](HANDOFF_2026-10-11.md). Later sections
> retain explicitly dated 4--10 October evidence and should not be read as a
> newer source or release snapshot.

## Current source and release status

At the 10 October source-only handoff, `main` was merge commit
`b1c36077c25726d8b77e5f804f750fa76a44a724` through merged PR #70. Merged
`main` subsequently advanced to `bb16608ab704912ee4801b4fd8bedfed29b6f638`
through PR #72. The accepted demonstration runs were produced earlier at
`f4662880523c71a8439750a7fca282c5d488d97e`, source tree
`1fe700d33c2ed6c18aa1adc23caa09c9cf39d773`. Current source and release source
are deliberately recorded as different boundaries.

PR #65 merged a generated checksum ledger before the source-only handoff. The
subsequent reconciliation removed that ledger from the tracked tree while retaining it in Git
history and inside the independently verified external evidence package. PR #67
merged truthful partial-age-coverage reporting for future outputs, and PR #70
made the city API contracts self-contained without rerunning the city. None of
these changes rewrites or reattributes the immutable release files.

Verification evidence is not additive. For example, the exact #73 integration
head `9c6d84f` passed 290 pipeline tests; #74 passed 19 frontend tests plus build
and lint; #75 passed 94 API tests. These are separate commands on separate
reviewed heads, not a single 403-test repository run and not empirical model
validation.

The implementation sequence includes:

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
- [PR #55](https://github.com/wattwong103/flood-vul-evac/pull/55) closed the
  saved-publication to both-API fractional-clearance regression gate.
- [PRs #56–#59](https://github.com/wattwong103/flood-vul-evac/pulls?q=is%3Apr+is%3Amerged)
  re-froze the admitted OSM snapshot, enabled per-cell age/sex inputs and
  restored the complete test gate before the release was executed.
- [PR #60](https://github.com/wattwong103/flood-vul-evac/pull/60) recorded the
  eight-run release and its limitations.
- [PRs #61–#64](https://github.com/wattwong103/flood-vul-evac/pulls?q=is%3Apr+is%3Amerged)
  improve future manifest identity, pair-report publication, the unexercised
  terrain path and repository lint. They do not reattribute the earlier runs.

The [four-area contract](MULTI_AREA_PLAN.md) remains authoritative. The first
two release attempts remain immutable negative evidence:
The first release attempt stopped on saved-WKT precision. Its two Khlong San
bundles are immutable negative evidence. The second attempt stopped on the
Din Daeng denominator replay after completing five of eight planned bundles.
Those five bundles and their eight-ID plan are also immutable negative evidence;
they cannot be pooled with a later release even though the preserved Din Daeng
bundle passes read-only replay under the corrected #51 source.

An earlier common-boundary set was executed on 10 October: eight run IDs, 8/8
run audits and 4/4 pair audits passed. It remains immutable historical
demonstration evidence at `f466288`; it is no longer the current paper/app
boundary. Current uses must follow the admitted `db0a96b` replacement and
exact P/C and age-coverage denominators in
[the 11 October release record](RELEASE_EVIDENCE_2026-10-11.md).

## OSM source re-freeze, 10 October 2026 — city numbers superseded

Approved by North on 10 October 2026 after the staging blocker fired.

The four-area contract admitted `geofabrik-thailand-osm-20260929`. On
10 October its dated publisher URL `thailand-260929.osm.pbf` returned **404**,
so the admitted source was no longer publicly retrievable and staging all four
AOIs failed at the licence gate. Independently, the local city cache had been
built from the **BBBike** Bangkok extract, a different clipped city rectangle
from the admitted national source.

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

### The staged city inventory changed materially

Rebuilding the city cache from the admitted source produced a substantially
larger network and building inventory. This is a source-to-source staging
comparison, not a measurement of ground-truth completeness:

| Layer | BBBike cache (was) | Geofabrik 261009 (now) | Staged inventory delta |
|---|---:|---:|---:|
| Road ways | 235,678 | 403,830 | **+71%** |
| Buildings | 272,116 | 427,580 | **+57%** |
| Water features | 4,681 | 7,144 | +53% |
| Modelled residents | 10,891,061 | 10,891,061 | unchanged |

**Consequence: the historical city run `be6a4e08-e2d7-4dd9-bf8b-4f2a02a12a81`
and every number derived from it — including the README's city table and the
76.1429 km² unreconciled-area figure — were computed on the earlier, smaller
BBBike-derived inventory rather than the admitted source. Those figures remain
true statements about that immutable run; they must no longer be presented as
current city results.**

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

Merged verification evidence through PR #64 records **363 passed, 6 failed**
for the Python/API suite. The same six pre-existing
`test_city_endpoints.py` failures recorded below remain the known stale-city-run
condition; repository-wide Python lint is clean.

## Historical city-scale implementation and verified run

[PRs #1–#14](https://github.com/wattwong103/flood-vul-evac/pulls?q=is%3Apr+is%3Amerged)
were human-merged by 4 October. Historical main at `9278893` has source tree
`07708a7f72ae62832bcd00de6b9771df3da1bb6a`, matching tested commit
`a5dfc51c59df65a27e136cbce594d73e09179181`.

Immutable city run `be6a4e08-e2d7-4dd9-bf8b-4f2a02a12a81` executed entirely
at that commit on 4 October: 831 seconds, 8/8 internal checks, zero schema
issues and 12/12 recorded output hashes verified. Source identity is external
evidence for this historical run, not a field retrospectively added to its manifest.
The source-matched test gate was 212 Python/API and 14 frontend tests; the
frontend build and ESLint passed with 11 warnings. No GitHub CI checks are
configured.

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
frontend tests; the frontend production build and ESLint passed with 11
warnings.
Fresh city run `4ecad6e0-c072-46e5-b818-6c4f3f259eaf` completed in 857.3 seconds
at source `0ecf18a2107631a23442da3c3274cea3dbe6507d`, tree
`638ba97c225669cc759992f333e8b70c6d59cb4f`. Its manifest records clean scoped
source and `matched_before_publication`, with source digest
`6e5fd057a252eab56a3400868a7ef0f1d7226ab6649cda6c49fc0d3aa56d24eb`.
It passed 8/8 internal checks with zero schema issues. This is a new run;
the historical evidence above remains attributed to its original source.
Later README/status edits only document this result and correct city height
coverage to 92.0% unknown; they do not change the executable source.

The README city table belongs to `be6a4e08`, not `4ecad6e0`. The later
`4ecad6e0` verification reproduced the same headline network, building and
population inventories, but it is a separate historical run and does not
reattribute that table. Neither run is current after the OSM source re-freeze.

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
| CLOSED MEDIUM API fractional-seconds round-trip | A real publication now survives saved Parquet/manifest readback through both clearance routes with fractional event seconds, with the canonical non-null denominator contract | Merged in #55. `api/tests/test_publication_roundtrip.py` recomputes the weighted-clearance definition independently rather than calling the pipeline helper; it fails on whole-second truncation and absolute-event-time regressions. No production change was needed. |
| MEDIUM BKK-024 release evidence | **Executed 10 October 2026**: eight runs on one boundary `f466288`/tree `1fe700d3`, 8/8 run audits and 4/4 pair audits pass; all four pair reports are published | The release is demonstration evidence. `population_version` is stale and requires re-staging plus a new release to correct. Release manifests predate #61's age block; current source is fixed for future runs without reattributing these files. |
| CLOSED MEDIUM age-coverage reporting | Three AOIs contain a small nonzero unknown-age population weight. The old warning incorrectly implied that every person was unknown, while known-band shares were normalized only over covered cells. | Merged in #67: new outputs report covered/unknown cell and weight denominators, use a covered-cell basis label and issue complete/partial/none warnings without changing assignment, assistance or immutable release files. |
| HIGH city result superseded | Every city number, including the README city table and the 76.1429 km² unreconciled-area figure, was derived from the earlier BBBike cache. Geofabrik staging produced 71% more road ways and 57% more buildings, but that delta is not a completeness estimate. No city run exists on the re-frozen source. | North + implementer: decide whether to re-run the city baseline on `geofabrik-thailand-osm-20261009`, and resolve the unattributed `bangkok-bma` AOI polygon first. Until then the city layer has **no current result** and its README numbers must not be cited. |
| MEDIUM BKK-009 boundaries | 76.1429 km² of the BMA lies outside the 50 OSM district union; cause unverified | Data steward + North: acquire authoritative geometry with reuse terms and reconcile the difference. The [BMA 50-district catalog](https://data.go.th/en/dataset/50) currently says “License not specified,” so it is a lead, not an admitted input. |
| MEDIUM BKK-009 population | Controls audited, not ingested or concept-matched | North selects resident/registered/de-facto target; implementer adds district crosswalk, date matching and reconciliation tests. |
| HIGH scientific gate: terrain/event | Actual bare-earth tiles, datum, forcing and held-out validation absent | Data steward: pursue the [RTARF-published catalog of RTSD LiDAR surveys](https://data.go.th/en/dataset/lidar-1) and [GISTDA event extent](https://opendata.gistda.or.th/th/dataset/disasters-03). A coverage index or extent product is not depth. |
| HIGH scientific gate: destinations | No verified capacity, operator, accessibility, inspection date or flood-safe access | North/data steward: obtain district/operator records through [BMA NOW](https://now.bangkok.go.th) and institutional channels; record reuse terms and retrieval evidence. |
| MEDIUM BKK-016 calibration/uncertainty | Two-mode priors, weighted-agent draws and one-at-a-time sensitivity | Scientific owner: define OTP target population, modes/purposes/distributions, weighted-agent interpretation and interaction-aware uncertainty before calibration claims. |
| MEDIUM BKK-017 driving | City routing is undirected | Implementer: preserve one-way/access restrictions and test direction before publishing vehicle results. Current reported screen is pedestrian. |
| MEDIUM BKK-018 failed-run visibility | New source-tracked runs are intentionally hidden until published; manifest-bearing failures appear in API `skipped`, but the warning lacks the failure reason | Implementer: expose operator-facing failure state/reason without serving unfinished scientific results. Runs without a manifest still require local diagnostics. |
| LOW BKK-019 display consistency | City stage table is complete, but the rail uses pilot stage names; an error phase with no error object would display loading | Implementer: use scale-specific stage names and preserve the error-state invariant. Current statistics hook supplies an error object on failure. |
| LOW maintenance | Repeated viewport counts, visibility-toggle refetches, anchor-loop performance, historical frontend lint warnings | Implementer: profile first; preserve public-layer completeness and method semantics. |

## Handoff and use

North owns review and merge. The paper session owns manuscript and figure edits.
The four-area release passed its internal run and pair gates and may be used
only as demonstration evidence with its `db0a96b` boundary, exact P/C and
age-coverage denominators and stated limitations. Implementation changes do not
automatically replace paper results, and superseded city numbers remain out of
scope. Historical evidence and fresh verification are separately identified in
every PR handoff.

Run `python -m pytest pipeline/tests api/tests -q`, then `pnpm test`, `pnpm build`
and `pnpm lint` from `site/`. Record the actual output and run UUID when promoting
any new evidence. Internal success alone never promotes a run beyond demonstration.

### Known pre-existing test failures, 10 October 2026

Merged verification evidence through PR #64 reports **363 passed, 6 failed, 0
errors**. All six failures are in `api/tests/test_city_endpoints.py` and are
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

Fixing all six requires regenerating the city run. **North decided on 10 October
2026 that the city run is NOT re-run.** Consequences, recorded rather than
smoothed over:

- The six `test_city_endpoints.py` failures **remain**. They are a known,
  documented stale-run condition, not a regression from any change here. Any
  green-suite claim must exclude them explicitly.
- The city numbers derived from run `be6a4e08` stay in the README and stay
  **superseded**: they were computed from the earlier BBBike cache rather than
  the admitted Geofabrik source. The city layer therefore has **no current
  result**; the observed inventory delta is not a completeness estimate.
- The verified fix path remains documented above, so the decision is reversible
  if the city layer is ever needed.

## Eight-run release executed — 10 October 2026

The eight-run release is complete. All eight runs were produced on one frozen
boundary and every run and pair gate passes.

| | |
|---|---|
| Commit | `f4662880523c71a8439750a7fca282c5d488d97e` |
| Source tree | `1fe700d33c2ed6c18aa1adc23caa09c9cf39d773` |
| Working tree at capture | clean |
| Source digest verification | `matched_before_publication` on all 8 |
| OSM source | `geofabrik-thailand-osm-20261009` |

All eight manifests carry the **same** commit, tree, verification status and
OSM source. There is exactly one boundary across the release.

| AOI | Area | dry run | moderate run |
|---|---|---|---|
| Khlong San | 5.96 km² | `2c4dcb04-a332-4f86-971c-771ba48fad3f` | `ebc2e5fc-6040-42e1-bb21-7f7e7d376aa7` |
| Sai Mai | 43.34 km² | `40fec9c2-f21a-43a7-9e5c-4f29cf3b40e2` | `547379f5-bc92-47be-9c46-487f7c9dabf2` |
| Din Daeng | 8.46 km² | `924a7bfa-c80d-421d-b675-8432ec1c94d2` | `b9c3f055-1079-4313-a5a5-f019f2c5a65d` |
| Min Buri | 59.99 km² | `547d0b10-7ded-47bf-a17b-23647f7e060b` | `d3dd91f1-cb9a-482e-88e0-371482a0cdd9` |

### Gates

- **Run audits: 8 / 8 pass** (`run.py validate`).
- **Pair audits: 4 / 4 `PASS`** (`report.load_checked_pair`).
- **Fixed cohort holds**: dry and moderate carry an identical cohort weight in
  every pair — 5310.9433 (Khlong San), 1392.4893 (Sai Mai), 6201.5745
  (Din Daeng), 809.9507 (Min Buri).

Per-cell age structure is configured and supplies known ages in all eight
(`age_structure_mode: per_cell`, `age_structure_source:
worldpop-tha-age-sex-2026-r2025a`). Coverage is not complete in three AOIs.
The release reports the basis as `population_weighted_over_cells`, but its
known-band shares are actually normalized over covered cells only.

### Two defects found while recording this

**1. `population_version` does not distinguish age-structured runs.** The eight
runs record `bkk-pop-v0.2-<aoi>-2020`, which is the value the *staged pilot
bundle* supplies. For named pilots that value takes precedence over
`config/population.json`, so bumping the config's `population_version` to
`bkk-pop-v0.3-khlongsan-2020-agesex` had **no effect on these runs**. A run with
per-cell age and a run without it therefore carry the same version string, which
breaks the rule that a changed population must carry a changed version. Closing
this properly requires re-staging the four pilots with a bumped version and
re-running the release; changing the config alone cannot do it.

**2. Release `manifest.population_model` omits the age structure.** The mode,
source and basis are recorded in `population_qa.json`, but not in the canonical
release manifests. PR #61 adds this identity to manifests of future runs; it
does not rewrite or reattribute the eight immutable release manifests.

### Pair artefacts now published

The four pair reports were generated successfully from the outset but could not
be published: `report.publish_pair_report` writes into a scratch directory
inside the run directory and then atomically renames it, and the rename was
refused because the repository sits inside a Dropbox-synced folder.

The lock was measured rather than assumed. A scratch directory written with four
files and then renamed was **refused immediately and succeeded after 15
seconds**, once the sync client released its handle. Both
`ERROR_ACCESS_DENIED` and `ERROR_SHARING_VIOLATION` surface as
`PermissionError` on Windows.

Two defects followed, both fixed on `fix/pair-report-atomic-publish`:

1. **The atomic rename had no retry.** `_publish_atomic` now re-attempts while a
   handle clears. The rename stays atomic — it is never replaced by a copy or a
   file-by-file move — so the publication guarantee is unchanged; only the wait
   is added.
2. **Cleanup masked the real error.** `tempfile.TemporaryDirectory.__exit__`
   raised during removal and swallowed whatever the block had raised, replacing
   a real failure with an unrelated `PermissionError`. Cleanup is now explicit
   and never raises. This is why the true cause went undiagnosed for so long.

All four pair reports are published with `audit_status: PASS`:

| AOI | pair report | artefacts |
|---|---|---:|
| Khlong San | `khlong-san-pair-report-2c4dcb04…-ebc2e5fc…` | 4 |
| Sai Mai | `sai-mai-pair-report-40fec9c2…-547379f5…` | 4 |
| Din Daeng | `din-daeng-pair-report-924a7bfa…-b9c3f055…` | 4 |
| Min Buri | `min-buri-pair-report-547d0b10…-d3dd91f1…` | 4 |

Each contains three PNG figures and one evidence markdown file.

## Age structure enabled per cell — North, 10 October 2026

`config/population.json` now sets `age_structure.mode: "per_cell"` with
`raster_dir: data/staged/population/agesex`. Age is sampled from 20 total-sex
WorldPop age-band rasters at each population cell centre, supplying a known
band for most people rather than assigning a national marginal. Two additional
male/female national-total rasters support acquisition QA only; the run keeps
sex as a declared prior rather than presenting those totals as local sex data.

| | |
|---|---|
| `population_version` in config | `bkk-pop-v0.3-khlongsan-2020-agesex` — **not** what the eight release runs record; see the defect above |
| Source | `worldpop-tha-age-sex-2026-r2025a`, CC BY 4.0, DOI 10.5258/SOTON/WP00841 |
| Acquisition | 22 rasters, 2.5 GB: 20 age bands used by the runner + 2 national sex-total QA rasters; all under `data/staged/` (git-ignored) |
| Reprojection | nearest-neighbour at cell centres; age grid 9953×17824 vs population 9952×17816 |

Why per cell rather than the national marginal: the national 65+ share is
16.35 %, but the four pilot AOIs actually run **9.48 % to 19.29 %**. A national
marginal would flatten that spatial variation and misstate AOI age composition,
worst in Min Buri by 6.87 pp. It would not change `assistance_need`, which the
current model derives from the sampled mobility profile's declared assistance
flag rather than age; it is not an independently calibrated probability draw.

Reported release `age_bands` for a `per_cell` run is a
**population-weighted aggregate over covered cells**. The release label
`age_band_basis: population_weighted_over_cells` is therefore misleading; the
next reporting fix will use a covered-cell label and publish coverage
denominators for new runs. It must not be read as a national marginal or as
complete AOI coverage.

Measured unknown-age gaps in the immutable release are:

| AOI | Unknown rows / total | Unknown population weight / total | Unknown weight share |
|---|---:|---:|---:|
| Khlong San | 82 / 25,562 | 4,250.8360 / 115,958.6556 | 3.67% |
| Sai Mai | 46 / 207,326 | 798.8647 / 281,949.0760 | 0.28% |
| Din Daeng | 0 / 40,760 | 0 / 207,118.4482 | 0.00% |
| Min Buri | 686 / 275,206 | 4,859.2443 / 273,891.4475 | 1.77% |

A missing raster file in the required set **aborts the run** with
`FileNotFoundError`; it does not fall back to a national figure. Nodata at an
individual sampled cell remains explicitly `unknown`, which is the partial
coverage now being reported more accurately.

Temporal caveat, carried in the config warnings: the age/sex rasters are 2026
estimates applied to a 2020 resident baseline. The structure is plausible but
not contemporaneous.

Existing small marginal and source-checksum metadata are tracked under
`data/curated/population/`; the 2.5 GB rasters and run outputs are not. A fresh
clone must acquire the rasters before any age-structured run.

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
