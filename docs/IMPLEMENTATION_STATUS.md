# BKK/FLOW project state

Updated 4 October 2026. **DONE_WITH_CONCERNS; demonstration only.**
This page is the shared implementation/evidence handoff. Internal validation
does not establish empirical validity or operational readiness.

## Merged implementation and verified run

[PRs #1–#14](https://github.com/wattwong103/flood-vul-evac/pulls?q=is%3Apr+is%3Amerged)
are human-merged. Main at `9278893` has source tree
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

## Current concern-fix branch

The [accepted task plan](CONCERN_RESOLUTION_PLAN.md) defines this follow-up.
These changes are proposed through ordered PRs; their presence in this document
does not mean the human has merged them or that an older run used them.

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

| Severity / task | What remains | Next owner and acceptance gate |
|---|---|---|
| MEDIUM BKK-009 boundaries | 76.1429 km² of the BMA lies outside the 50 OSM district union; cause unverified | Data steward + North: acquire authoritative geometry with reuse terms and reconcile the difference. The [BMA 50-district catalog](https://data.go.th/en/dataset/50) currently says “License not specified,” so it is a lead, not an admitted input. |
| MEDIUM BKK-009 population | Controls audited, not ingested or concept-matched | North selects resident/registered/de-facto target; implementer adds district crosswalk, date matching and reconciliation tests. |
| HIGH scientific gate: terrain/event | Actual bare-earth tiles, datum, forcing and held-out validation absent | Data steward: pursue [RTSD LiDAR catalog](https://data.go.th/en/dataset/lidar-1) and [GISTDA event extent](https://opendata.gistda.or.th/th/dataset/disasters-03). A coverage index or extent product is not depth. |
| HIGH scientific gate: destinations | No verified capacity, operator, accessibility, inspection date or flood-safe access | North/data steward: obtain district/operator records through [BMA NOW](https://now.bangkok.go.th) and institutional channels; record reuse terms and retrieval evidence. |
| MEDIUM BKK-015 pilot replay/cost | Legacy pilot replay differs by 53.67 weighted arrivals; open flooded edges use dry cost; percentiles cap weighted repetitions | Implementer + scientific owner: regression-tested impedance and exact weighted statistics, then a fresh source-pinned run and replay. Legacy pilot `a0d11a4d-6c75-4723-90cf-b634e2f2a230` is not submission-ready. |
| MEDIUM BKK-016 calibration/uncertainty | Two-mode priors, weighted-agent draws and one-at-a-time sensitivity | Scientific owner: define OTP target population, modes/purposes/distributions, weighted-agent interpretation and interaction-aware uncertainty before calibration claims. |
| MEDIUM BKK-017 driving | City routing is undirected | Implementer: preserve one-way/access restrictions and test direction before publishing vehicle results. Current reported screen is pedestrian. |
| MEDIUM BKK-018 failed-run visibility | New source-tracked runs are intentionally hidden until published; manifest-bearing failures appear in API `skipped`, but the warning lacks the failure reason | Implementer: expose operator-facing failure state/reason without serving unfinished scientific results. Runs without a manifest still require local diagnostics. |
| LOW BKK-019 display consistency | City stage table is complete, but the rail uses pilot stage names; an error phase with no error object would display loading | Implementer: use scale-specific stage names and preserve the error-state invariant. Current statistics hook supplies an error object on failure. |
| LOW maintenance | Repeated viewport counts, visibility-toggle refetches, anchor-loop performance, existing lint warnings | Implementer: profile first; preserve public-layer completeness and method semantics. |

## Handoff and use

North owns review and merge. The paper session owns manuscript and figure edits;
it has the immutable run, exact numbers, source tree and caveats. Implementation
changes do not automatically replace paper results. Historical evidence and
fresh verification are separately identified in every PR handoff.

Run `python -m pytest pipeline/tests api/tests -q`, then `pnpm test`, `pnpm build`
and `pnpm lint` from `site/`. Record the actual output and run UUID when promoting
any new evidence. Internal success alone never promotes a run beyond demonstration.

DONE_WITH_CONCERNS
