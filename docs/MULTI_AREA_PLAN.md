# Four-area pilot comparison contract

**Task:** BKK-020

**Authorised scope:** Khlong San, Sai Mai, Din Daeng and Min Buri

**Status:** implementation contract; no comparative result is authorised by this document

North approved these four study areas and the method choices below on 4 October
2026. The work remains a controlled demonstration. It is not a representative
sample of Bangkok, a calibrated mobility model, a hydraulic reconstruction, an
operational evacuation plan or a forecast. Implementers do not merge PRs.

## Ordered tasks and acceptance criteria

| Task | Required change | Acceptance evidence |
|---|---|---|
| BKK-020 | Freeze this scope, method, metric and release contract | Four named AOIs, paired-run design, equations, claim limits and ordered gates are explicit; legacy and new evidence cannot be pooled. |
| BKK-021 | Add explicit per-AOI configuration and runner/CLI parameters | Every named AOI has isolated curated inputs and version IDs; unknown or mismatched configurations fail; saved run identity uses the selected AOI. |
| BKK-022 | Stage each AOI from the admitted regional OSM and WorldPop sources | Registry approval, source/layer/geometry hashes, exact relation ID, valid polygon, expected CRS, scoped caches and reopen/hash checks pass; generated data stays out of Git. |
| BKK-023 | Make every run immutable and independently identifiable | Effective seed, sample cap, active scenario, source hashes, code commit/tree/source digest and output hashes are recorded; source/config drift, schema error or output-integrity failure blocks publication. |
| BKK-015a | Apply flood impedance to every open peak-time walking edge | For edge length \(L_e\), dry speed \(v_e\) and multiplier \(m_e\), routing cost is \(L_e/(v_e m_e)\) for \(0<m_e\leq1\); \(m_e=0\) edges are absent. Tests cover slowdown, closure and parallel-edge selection. |
| BKK-015b | Use one exact weighted-clearance definition in pipeline and API | Clearance is time since warning, never absolute event time. Pipeline statistics, generic reports and every API route return the inverse weighted empirical-CDF values defined below. |
| BKK-015c | Use one fixed cohort for each AOI's dry/moderate pair | Dry and moderate runs contain the same sampled person IDs and weights in the order-area cohort. Flood exposure is reported separately and never changes cohort membership. |
| BKK-015d | Record and enforce sample denominators | Full and sampled row counts and weight sums are saved. Presence, exposure, cohort, state and clearance outputs identify their sample denominator and are never labelled full-district estimates. No silent reweighting is permitted. |
| BKK-015d1a | Conserve integerized-capacity fragments | Fractional source weights remain exact across unique, source-linked terminal records while shelter capacity stays integerized. |
| BKK-015d1b | Construct the denominator contract | F/S/P/C/E/A quantities, terminal states, shares and conservation are constructed without reweighting. |
| BKK-015d2 | Validate saved denominator-contract readback | Required declarations and cross-field identities reject the reproduced contradictory payloads; stable summation preserves a valid reordered all-arrived result. |
| BKK-015d3 | Publish canonical denominators | The runner writes and registers `denominators.json`; `stats.json` uses the same exact quantities for paired dry/moderate runs. |
| BKK-015d4 | Expose canonical denominators through the API | Stats and evacuation routes expose the same validated contract; missing or invalid legacy contracts remain null with a warning and are never reconstructed. |
| BKK-015d5 | Harden corrupt denominator readback | Parked MEDIUM follow-up: validate exclusive terminal-source counts, equal-cardinality subset weights, all-present exposure weights, typed pair identity values and malformed clearance-section shapes. |
| BKK-015e | Independently reconstruct one source-pinned run from saved artefacts | An auditor that does not call the runner's result-building helpers reconstructs cohort membership, peak costs/closures, destination assignment/capacity, terminal conservation and weighted metrics within the tolerances below. Repeating the runner is only a separate repeatability check. |
| BKK-024a | Generate a checked, area-generic comparison report | The report reads the saved AOI label, rejects cross-AOI or contract-mismatched pairs, states all denominators and limitations, and contains no hard-coded Khlong San or causal-isolation claim. |
| BKK-024 | Generate and audit the four-area comparison | Exactly eight new immutable runs—one dry and one moderate run per AOI—have unique IDs and one retained commit/config bundle. Pair and cross-area audits pass before any number is sent to the paper. |

Each implementation PR stays near 300 changed lines, adds the regression tests
that would catch its failure, and receives fresh-context and cross-harness review.
CRITICAL and HIGH findings block readiness. These tasks are ordered gates:
BKK-024 release runs do not begin merely because staging is complete.

## Frozen common run contract

### Areas and admitted inputs

- Khlong San: OSM relation `R3147280`.
- Sai Mai: OSM relation `R2938035`.
- Din Daeng: OSM relation `R2938031`.
- Min Buri: OSM relation `R3146413`.
- Boundaries are OSM administrative reporting geometries, not authoritative BMA
  controls or hydraulic catchments.
- OSM is the verified complete 29 September 2026 Thailand Geofabrik extract,
  ODbL 1.0. Population is the same 2020 WorldPop count raster, CC BY 4.0.
  Preserve source-native raster counts and the declared pixel-inclusion rule;
  do not rescale them to 2025 registrations.
- Analysis uses `EPSG:32647`; stored geographic outputs use `OGC:CRS84`.
  Public population and mobility reporting begins at 1 km. No real trajectories
  or personal records are introduced.

### Parameters held equal

- Population, activity and evacuation seed: `29092026`.
- Maximum sampled simulation rows: `1200` per AOI.
- One fixed sampled order-area cohort per AOI is used in both pair members.
- Pair members use identical population/person tables, mobility priors, warning,
  compliance, preparation-delay draws, routing assumptions, destination set,
  assumed destination capacities and metric denominators.
- Flood comparison: dry versus the moderate distance-to-water demonstration,
  18:00–22:00 with a 19:00 peak, 50 m internal scenario cells and threshold set
  `bkk-demo-thresholds-v0.1`. The active dry/moderate state is saved explicitly.
- Evacuation assumptions remain warning reach `0.92`, compliance `0.78`,
  preparation delay mean `900 s` and standard deviation `600 s`, with three
  hypothetical, unverified destinations of assumed `2,000-person` capacity each.
- Sensitivity vocabulary remains severity low/moderate/high and compliance
  `0.60/0.78/0.90` at fixed source and seed. This release executes only dry and
  moderate at compliance `0.78`; every other case is explicitly unexecuted.
  One-at-a-time cases are not an interaction-aware uncertainty analysis.

All eight release runs must retain the same Git commit and tree, scoped source
digest, effective configuration bytes/digest and staged source hashes. The
checkout must remain quiescent from pre-run capture through publication. A
changed source, configuration, dependency selection or staged input requires a
new run set; it is not patched into an existing set. Fresh Khlong San runs use
this contract. No legacy Khlong San run is pooled with the comparison.

## Cohort and denominator contract

For AOI \(a\), let \(F_a\) be all weighted person rows, \(S_a\subseteq F_a\)
the deterministic capped sample, \(P_a\subseteq S_a\) the rows present at the
scenario time, and \(O_a\) the fixed order-area rule. The paired cohort is

\[
C_a = P_a \cap O_a.
\]

The same person IDs and weights in \(C_a\) are used for dry and moderate runs.
Scenario exposure is a separate subset \(E_{a,s}\subseteq P_a\); it never
defines or changes \(C_a\). Thus `people_exposed` is reported with denominator
sampled-present weight, while evacuation outcomes use cohort weight.

Every run records at least:

- full row count \(N_F=|F_a|\) and full weight \(W_F=\sum_{i\in F_a}w_i\);
- sampled row count \(N_S=|S_a|\) and sampled weight \(W_S=\sum_{i\in S_a}w_i\);
- sampled-present weight \(W_P\), exposed weight \(W_E\), cohort weight \(W_C\);
- terminal weights \(W_A\) arrived, \(W_U\) unserved and each component terminal
  state, plus the denominator used for every displayed share.

Sampling preserves source row weights but does not make \(W_S=W_F\) and does not
expand outcomes to a district total. Full resident weight is contextual input;
sample presence, exposure, cohort and terminal weights are sample-only results.
Reports must not place them on one scale or call them full-district estimates.
No Horvitz–Thompson, ratio, calibration or other estimator is implied. Adding
one requires a separate approved method and validation task.

Terminal conservation is mandatory in each run:

\[
\sum_{k\in K} W_k = W_C,
\quad
K=\{\text{arrived, shelter-full, stranded, route-failed, did-not-depart}\}.
\]

State shares use \(W_C\). Exposure share uses \(W_P\). Clearance quantiles use
arrived weight \(W_A\). A zero denominator produces a labelled null, not zero.

## Weighted-clearance contract

For every arrived state, clearance is

\[
c_i=(t^{arrival}_i-t^{warning})/60
\]

in minutes, paired with its finite positive sample weight \(w_i\). Sort by
\(c_i\). For \(q\in\{0.05,0.50,0.95\}\), the inverse weighted empirical CDF is

\[
Q(q)=\min\left\{c_j:\sum_{i:c_i\leq c_j}w_i\geq qW_A\right\},
\quad W_A=\sum_iw_i.
\]

This definition performs no row replication, rounding of weights or interpolation.
Invalid/non-positive arrived weights fail validation; no arrived weight returns
null quantiles. Pipeline output, report output and all API endpoints use exactly
this definition and unit.

## Required paired outputs and checks

Each dry/moderate pair records or derives from saved artefacts:

- run ID, AOI ID/name/relation, code/config/source identities and active scenario;
- \(N_F,W_F,N_S,W_S,W_P,W_E,W_C\) and every terminal-state weight;
- exposure share \(W_E/W_P\), terminal shares \(W_k/W_C\), and p5/median/p95
  clearance over arrived sample weight \(W_A\);
- peak eligible walking-edge count, open slowed-edge count, closed-edge count and
  the denominator for any mean speed/capacity-loss statistic;
- hypothetical destination IDs, assumed capacities, admitted sample weight and
  remaining capacity under the declared integerisation rule;
- conservation residual, validation status, output row counts and content hashes;
- the sensitivity cases executed and those still pending.

A pair is invalid if AOI identity, cohort IDs/weights, source/config/code identity,
destinations, assumptions or denominators differ. Reports must fail rather than
compare mismatched runs.

## Independent replay and tolerances

The BKK-015e auditor reads the saved manifest and artefacts as its inputs and
implements its own reconstruction path. It must not call the runner's cohort,
route-result, capacity-allocation or summary builders. It verifies:

1. exact AOI, source, code, configuration, person/cohort/destination IDs, row
   counts, closure flags, terminal labels and output hashes;
2. independently reconstructed peak open-edge costs and shortest routes;
3. destination choice, admitted/overflow weights and remaining assumed capacity;
4. terminal conservation and all denominator assignments;
5. inverse weighted empirical-CDF clearance statistics.

Identity and categorical checks are exact. Aggregated reported weights and
clearance minutes must match the independently reconstructed values within
`0.01` in their published units; unrounded edge cost and conservation checks use
absolute tolerance `1e-6`. Any larger residual, unexplained tie or missing input
fails the audit. A second execution with the same retained bundle may establish
repeatability, but cannot substitute for this independent correctness check.

## Scientific and publication gates

Stage and verify input identity before computation. A complete regional source
footprint does not prove OSM feature completeness, boundary authority, vertical
accuracy or population-concept agreement. Invalid, missing or ambiguous geometry,
unapproved licences and changed hashes block staging rather than being guessed.
Named AOIs never fall back to Khlong San caches.

No release run starts until BKK-015a–e and BKK-024a pass their tests and reviews.
Afterwards, generate exactly one new dry and one new moderate run for each AOI,
then freeze their IDs and audit bundle. Paper insertion begins only after all
eight immutable runs pass source/code/config identity, schema, output-integrity,
pair, denominator, conservation and independent-replay checks.

Allowed wording is limited to a **within-model demonstration contrast under fixed
declared assumptions**. Results do not support causal, hydraulic, operational,
predictive, safety, capacity-validity, representative-of-Bangkok or full-district
population claims. Destinations and capacities remain hypothetical; mobility and
behaviour remain uncalibrated; sensitivities remain incomplete. The paper chat
receives only checked run IDs, source hashes, numerical evidence, denominators
and limitations. North owns scientific decisions and every merge.

DONE_WITH_CONCERNS
