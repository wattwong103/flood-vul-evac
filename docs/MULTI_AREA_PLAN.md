# Four-area pilot implementation plan

Task BKK-020. North authorised four total study areas in the coordination chat on 4 October 2026; the coordinated selection is Khlong San, Sai Mai, Din Daeng and Min Buri. This is an extension of the demonstration, not a representative Bangkok sample or a hydraulic district model. Existing PRs are not merged by the implementer.

## Ordered tasks and acceptance criteria

| Task | Source changes | Acceptance evidence |
|---|---|---|
| BKK-020 | Record scope, common contract and implementation order | Explicit four AOIs, no invented paper results; old and new run evidence separately identified. |
| BKK-021 | Explicit per-AOI pilot configuration and runner/CLI parameters | Default Khlong San invocation remains compatible; every named AOI uses its own curated inputs and version IDs; unknown/mismatched configurations fail; dry and flooded fixture runs publish source identity. |
| BKK-022 | Reuse verified local regional OSM and WorldPop sources to stage each AOI | Registry approval, source/layer/geometry hashes, valid nonempty polygon with exact relation ID, expected CRS, scoped caches, complete source footprint, output reopen/hash checks; no silent reuse after tampering. No generated data in Git. |
| BKK-023 | Common scenario and input evidence in each immutable run | Same population raster, scenario parameters, sample cap, seeds and sensitivity vocabulary; effective configurations and input hashes are recorded. Schema and output checks gate publication. |
| BKK-024 | Generate and audit the four-area comparison; generic reports | Fresh dry/moderate pair for all four areas, unique run IDs, matching source identity, checks/hashes/replay diagnostics; report labels use saved AOI identity. Scientific limits and unexecuted sensitivity cases are explicit. |

Each implementation PR stays near 300 changed lines and includes a regression test. Review in fresh context and separately across harnesses before ready status. The separate pilot source-identity handoff defect discovered during preparation is repaired in PR #24 before this stack is promoted.

## Common comparison contract

Reuse the existing demonstration assumptions to isolate the effect of AOI/data, rather than calibrating on the four outcomes. Alternatives are recalibration against OTP or a catchment/hydraulic model; both need new scientific evidence and separate approval.

- AOIs: OSM relations R3147280 (Khlong San), R2938035 (Sai Mai), R2938031 (Din Daeng), R3146413 (Min Buri). They are OSM administrative reporting areas, not authoritative BMA controls or hydraulic boundaries.
- Source: the verified complete 29 September 2026 Thailand Geofabrik extract, ODbL 1.0, and the same 2020 WorldPop count raster, CC BY 4.0. Preserve source-native raster counts and document pixel inclusion/threshold policy. Do not rescale to 2025 registrations.
- Analysis CRS remains EPSG:32647; storage OGC:CRS84; public population/mobility aggregation starts at 1 km. No real trajectories are introduced.
- Same seed 29092026 and maximum 1,200 weighted sampled agents per AOI. A weighted record is a simulation unit, not a validated independent-person behavioural model. Scenario demographic/mobility priors remain uncalibrated.
- Same dry comparison and moderate distance-to-water demonstration window (18:00–22:00, peak 19:00), 50 m internal depth cells and existing threshold version. Remove the misleading area/event-specific 2011-analogue label for new multi-area configurations; no event reconstruction is implied.
- Same warning/compliance/preparation assumptions and three hypothetical destinations with assumed 2,000-person capacity each. Record capacities as assumptions, never verified operational capacity. Equal assumptions do not imply equal service adequacy across differently sized AOIs.
- Sensitivity contract retains low/moderate/high scenario severity and compliance 0.60/0.78/0.90 at fixed source/seed. Initial publication covers dry/moderate pairs; any other case not executed remains explicitly pending. One-at-a-time cases are not an interaction-aware uncertainty assessment.
- Fresh Khlong San runs use the same new staged-source contract as the three additional areas. Its legacy run is not silently pooled with the new comparison.

## Scientific gates and failure modes

Stage and verify input identity before computation. A complete regional source footprint is not proof of OSM feature completeness, vertical accuracy, or population-concept agreement. Invalid/missing/ambiguous boundaries, unapproved licences and changed hashes block staging rather than being guessed or silently repaired.

New area support must never fall back to Khlong San's cached population, OSM or water. Every area name, version, area measure and cache identity must agree. Source/configuration changes during execution must keep a run unpublished. Saved configurations must support an independent replay audit.

Keep BKK-015 pilot cost/replay/weighted-percentile findings explicit. A new immutable run does not itself fix them. If the independent replay still disagrees, report that failure and correct the implementation before using new aggregate outcomes as comparative paper evidence. Do not turn parked calibration/method questions into empirical claims.

The paper chat owns manuscript and figures. Send only checked run identities, source hashes, numerical evidence and limitations. North owns scientific decisions and all merges.

DONE_WITH_CONCERNS
