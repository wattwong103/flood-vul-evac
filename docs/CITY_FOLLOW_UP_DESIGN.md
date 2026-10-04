# City correctness and map-delivery follow-up

User-authorized scope: fix the concerns left by the JRC, complete-coverage and
immutable-run changes. Existing runs remain immutable; new results use new IDs.

## Ordered tasks and acceptance criteria

1. **BKK-005A — comparable connectivity scenarios.** Keep origin and destination
   anchors on the baseline walking graph, including isolated nodes after closure.
   Use a reproducible nested ordering of wet edges. Reopening roads must not reduce
   reachability on regression fixtures. Keep the existing 400 m access tolerance
   and three-hour routing bound, and disclose both. Test empty graphs and bounds.
2. **BKK-005B — aligned exposure.** Replace nearest-centre matching with positive
   area overlap of the two 1 km cell footprints. Count each population cell once.
   Test offset grids and boundary-only contact. This is population in cells that
   overlap water-containing cells, not a count of people standing in water.
3. **BKK-006A — verified raster reuse.** All JRC consumers validate the staged
   raster hash against retrieval evidence. Recover missing sidecars only from
   matching original HTTP cache records. A missing record is an explicit error,
   never a newly invented download date. Count zero-class pixels even when the
   TIFF declares zero as nodata. Test changed bytes, offline reuse and AOI masks.
4. **BKK-006B — faithful source metadata and counts.** WorldPop uses its own
   retrieval record, not the AOI date. Mapped-water counts describe the saved
   layer. Store large source coverage geometry once per run with a manifest hash.
   Validate custom coverage paths and malformed polygon input. Keep full hash
   checks unless measured evidence justifies a safe replacement.
5. **BKK-004A/B — spatial map delivery.** Build an immutable run-local spatial
   index of public road/building features, then serve bounded viewport pages.
   The UI follows the viewport and states when more detail requires zooming.
   Paging must be deterministic and must reach features on both sides of the AOI.
   Missing indexes stay explicit for old runs; no shared mutable fallback.
6. **BKK-007 — report and UI regressions.** Correct validation markup, test a null
   observation-share figure, include unknown-height buildings, and remove unused
   one-shot patch scripts after checking references.

## Method choices

Fixed anchors are preferred to re-snapping because otherwise two scenarios change
both access locations and roads. Seeded permutation prefixes are preferred to
independent samples because they compare nested closure sets. These are sensitivity
assumptions, not probabilities inferred from annual water observations.

Positive footprint overlap is preferred to shifting the established population
grid: it preserves the public aggregation and makes offset-grid semantics exact.
It remains a coarse exposure proxy. A raster/population overlay would be a separate
method requiring resolution and population-allocation assumptions.

For maps, viewport queries using SQLite RTree are preferred to new vector-tile
infrastructure. SQLite is already available in Python and supports indexed spatial
lookup and stable paging without adding a service. Only public run layers enter
the index. Prebuilt tiles remain an alternative for a later hosted deployment.

## Verification and delivery

Tests precede fixes. Each implementation task is an ordered branch/PR, normally
under about 300 changed lines, with acceptance criteria in its PR body. Run focused
regressions followed by the Python/API suite and frontend checks where applicable.
Obtain fresh-context and cross-harness Claude reviews, fix critical/high findings,
and report other findings. Regenerate a new city run, verify output hashes, compare
closure scenarios, exercise spatial API pages and inspect the browser. A human
merges the PRs.

Scientific data limits remain explicit: no verified destination capacity/safety,
no calibrated mobility or administrative population controls, no event water depth
or timing, and no proof of OSM mapping completeness. Source coverage alone cannot
resolve these limits. Do not manufacture unavailable evidence to clear a concern.
