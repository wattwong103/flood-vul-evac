# BKK/FLOW point-observation skill check

**Protocol version:** `psk-v1`
**Status:** decisions locked (BKK-056a); harness not built (BKK-056b); no real run (BKK-056c)
**Applies to:** the BKK-056b harness and every BKK-056c run
**Decided by:** North, 10 November 2026

This note records North's choices D1–D6 for BKK-056 (`tasks.md`). It is the
protocol the BKK-056b harness implements and the BKK-056c record locks. It
reuses the observed-extent check's `oec-v1` rules where the two checks meet,
and names each one by file and line, so a change to `oec-v1` cannot silently
change `psk-v1`.

## 1. Question and boundary

The check scores flood surfaces against **timed point observations**: road
flood-sensor depths and citizen flood reports. BKK-053 (`oec-v1`) scores
surfaces against mapped extent; this scores them against points.

- It is a plausibility check with baselines. It is **not calibration**, and it
  is **not** the held-out validation of BKK-036C, which may reuse it.
- No observation reaches `build_depth_surface` (`pipeline/bkkflow/flood.py:101`)
  or `build_flood_slices` (`pipeline/bkkflow/flood.py:208`).
- Nothing here edits the admitted release or cites a city result before
  BKK-040.

## 2. Decisions

North chose these on 10 November 2026 in structured decision prompts. The
prompts offered the options listed under BKK-056 in `tasks.md` (PR #104), plus
three the prompts added: the 80% and 75% shares for D2b, and "timed surfaces
only" for D6. Two choices differ from the recommended option: D2b and D5.

Labels marked **ASSUMPTION** below are this note's readings of those choices.
North confirmed all of them unchanged on 10 November 2026, in review of PR
#105, so they bind BKK-056b like the choices themselves.

| # | Decision | Chosen | Not chosen |
|---|---|---|---|
| D1 | Scoring unit | 100 m blocks in EPSG:32647, as in `oec-v1`; published only at 1 km | the 1 km grid; the surface's native grid |
| D2a | Sensor wet depth | window maximum ≥ 0.15 m | 0.10 m |
| D2b | Sensor observed dry | below 0.15 m at every reported reading, **and** at least 90% of scheduled readings reported | below the threshold at every scheduled reading (recommended); a share of 80% or 75% |
| D2c | Report controls | `not_reported` blocks drawn from blocks with exposure above zero | every in-domain block |
| D3 | Baseline ladder | the full ladder (section 3.3) | the exposure rung only |
| D3 | Exposure proxy | building cover | people present |
| D4 | Bootstrap block length | `oec-v1`'s correlogram rule with its not-estimable fallback | a fixed length |
| D5 | Claim rule | **report differences and intervals, with no claim rule** | "adds skill over rung k" when the paired 95% interval's lower bound is above 0 (recommended) |
| D6 | Time | as written in BKK-056 (section 3.6) | timed surfaces only |

## 3. The protocol

### 3.1 Unit (D1)

- A block is 100 m: an exact 2 × 2 group of `oec-v1`'s 50 m lattice points in
  EPSG:32647 (`pipeline/bkkflow/observed_extent.py:26-28`). Every label,
  score and rung is computed on these blocks.
- Any map or table of labels or scores that leaves the run directory is
  aggregated to 1 km cells first.
- **ASSUMPTION:** case-level metrics (AUC, intervals, null p), which carry no
  location, are published as computed. D1's 1 km rule is read as applying to
  anything mapped or tabulated by place.
- **ASSUMPTION** (approved with the BKK-056b plan): a block enters a case when
  every candidate evaluated at least half its area inside the AOI (`oec-v1`'s
  `MIN_EVALUABLE`). Each surface's domain is found on its own
  (`point_skill_scores.block_scores`), and the case keeps the blocks in every
  candidate's domain. There is no channel mask, because the labels are points,
  not mapped extent.

### 3.2 Labels (D2)

**Road sensors.** For each block holding a sensor and each event window:

- `observed_wet`: the window maximum of the reported depth is ≥ 0.15 m. This
  equals `oec-v1`'s `SECONDARY_DEPTH_M` (`pipeline/bkkflow/observed_extent.py:32`)
  and the API's flood-area threshold `FLOOD_AREA_THRESHOLD_M`
  (`api/flood_summary.py:38`).
- `observed_dry`: the sensor reported at least 90% of its scheduled readings
  in the window, and every reported reading is below 0.15 m.
- `unknown`: anything else. A gap never makes a block dry, and a block with
  fewer than 90% of its readings is never dry.

**Citizen reports.** Reports are presence-only.

- `reported`: at least one report falls in the block within the window.
- `not_reported`: an in-domain block with no report in the window and with
  building cover (section 3.3) above zero. It is never `observed_dry`.
- **ASSUMPTION:** every block that qualifies as `not_reported` is a control,
  with no sampling, as oec-v1 uses every block.

**ASSUMPTION:** sensor labels and report labels answer different questions (dry
versus not reported), so they are scored as separate cases and never pooled.

**Minimum.** As in `oec-v1` (`pipeline/bkkflow/observed_extent_stats.py:48`), a
case with fewer than 30 positives or fewer than 30 negatives is
`undefined_*`, with null metrics, never 0 or 0.5.

### 3.3 Baseline ladder (D3)

Every candidate surface is reported against every rung. A rung whose input
does not exist is reported as null with a reason, never dropped. Chance is the
null distribution; the other rungs are scores, and the paired differences in
section 3.5 are taken against them only.

| Rung | Definition | Input today |
|---|---|---|
| Chance | `oec-v1`'s toroidal-shift null (`pipeline/bkkflow/observed_extent_stats.py:132`) | always |
| Exposure | share of the block covered by OSM building footprints | footprints are loaded (`pipeline/bkkflow/sources/osm.py:252`); `point_skill.building_cover` computes block cover (BKK-056b) |
| Channel | distance to `oec-v1`'s channel mask, the union of MitrEarth water bodies and GSW permanent water (`pipeline/bkkflow/observed_extent_stats.py:51`) | yes |
| Rain-only | defined in BKK-056b (section 5) | needs admitted event forcing (BKK-036B) |
| Persistence | defined in BKK-056b (section 5) | needs a prior observation of the same kind |

There is no elevation rung until BKK-036A admits a bare-earth surface: the
available DSMs are insufficient for Bangkok depth
(`docs/CITY_SCALE_LIMITATIONS.md:91`).

Building cover is mandatory for report cases: it is both the exposure rung and
D2c's control pool, because reports follow where people can see and file
them.

- The definition, the share of the block covered by OSM building footprints,
  is the wording of the option North chose.
- OSM footprints are present-day, not event-time. This is the same limitation
  as oec-v1's assumption A7 (`pipeline/bkkflow/observed_extent.py:59`), and
  any result carries it.
- **ASSUMPTION:** higher cover ranks as more likely positive, and nearer to
  channel ranks as wetter, as in oec-v1.

### 3.4 Statistic, null and interval (D4)

- **AUC:** `oec-v1`'s `auc` unchanged (`pipeline/bkkflow/observed_extent_stats.py:89`):
  Mann-Whitney, ties count 1/2. It ranks the lower value as wetter, so higher
  surface depths are negated before scoring. The TOC curve is reported in the
  score's own units.
- **Chance:** the toroidal-shift null; p = (1 + k) / (1 + n) over defined
  shifts, as in `oec-v1`. A shifted label is scored wherever it lands in the
  case's domain (North, 10 November 2026, Q6). `oec-v1` scores it only where a
  label already sat. On sparse sensor labels that left 60–80% of shifts
  undefined. On `oec-v1`'s fixtures the two rules give the same result.
- **Interval:** a paired spatial block bootstrap, percentile 95%. The block
  length is the first lag at which the label correlogram is ≤ 0.05
  (`RANGE_THRESHOLD`, `pipeline/bkkflow/observed_extent_stats.py:27`).
- **Fallback:** as `oec-v1`'s option (c): if the correlogram stays above 0.05
  up to half the shorter grid side, the case has no interval, with status
  `interval_not_estimable` and the lags and r values examined. A case whose
  labels hold one class only, or whose qualifying lags (below) all have an
  undefined r, is locked as undefined.
- **Sparse labels** (North, 10 November 2026, Q7, amending D4): a correlogram
  lag counts only with at least 30 label pairs. BKK-056b's sparse fixture found
  why. On 70–262 spatially independent sensor labels, `oec-v1`'s rule picked
  lengths of 100 m to over 600 m, from lags holding a median of 3.5–4 pairs. If
  no lag qualifies, the case takes the fallback with reason
  `no_lag_with_min_pairs`: no interval, but the AUC and the null are kept.
  Lags that qualify but never fall to 0.05 keep `oec-v1`'s reason. Dense report
  cases and `oec-v1`'s fixtures are unaffected.
- The null, bootstrap, correlogram and TOC are new code, because `oec-v1`'s are
  bound to its rows; on `oec-v1`'s fixtures they must reproduce `oec-v1`'s
  results. `oec-v1`'s code, `PROTOCOL` and tests stay untouched.

### 3.5 Reporting, with no claim rule (D5)

For each case, the record reports:

- for the candidate and for each score rung (exposure, channel, rain-only,
  persistence): AUC, TOC, toroidal-null p (the Chance rung) and the
  block-bootstrap 95% interval;
- for the candidate against each score rung: the paired difference
  AUC(candidate) − AUC(rung) and its paired 95% interval.

There is **no verdict field**. Neither the record nor any text generated from
it says that a surface "adds skill", "beats" or "outperforms" a rung; a reader
gets the numbers and intervals. Under the D4 fallback both intervals are null.

### 3.6 Time (D6)

- A **timed surface** (one with an issue time t and a lead) is scored against
  observations in [t, t + lead].
- A **declared scenario** has no calendar date. Its peak rank is scored
  against every observation in the event window, as spatial plausibility in
  the manner of BKK-053.
- A pilot scenario is a distance-to-water decay (`pipeline/bkkflow/flood.py`),
  so its rank equals the channel rung's rank. That comparison shows no
  difference **by construction**; the record states this rather than
  reporting it as a finding.
- **ASSUMPTION** (approved with the BKK-056b plan): the scenario decays from
  OSM water, while the channel rung uses the MitrEarth ∪ GSW mask. Their ranks
  are close but not identical, so the record says both are distance-to-water
  ranks from different water layers rather than "equal".
- Windows are closed at both ends. The rain-only accumulation for a timed
  surface is the closed [t − hours, t]. The persistence window has the same
  length and ends where the scoring window starts, read half-open, so no
  observation is in both.

### 3.7 Privacy

These restate rules already set for BKK-056c in `tasks.md`:

- Citizen reports are aggregated to 100 m blocks at ingest. No report text,
  photo or report id is kept.
- Run outputs stay outside Git.
- North decides privacy and consent for any citizen-report source before it
  is ingested.

A minimum report count per published 1 km cell is still open (section 5).

## 4. Changes to BKK-056b's acceptance criteria

`tasks.md` was written before D5 and D2b were chosen, so it assumes a verdict
exists and has no test for D2b's 90% share. **ASSUMPTION** (labelled for
North's review of this PR): two BKK-056b criteria change and one is added.

| Criterion in `tasks.md` (PR #104) | Under `psk-v1` |
|---|---|
| per rung and candidate, "… paired difference interval and D5 verdict"; under the fallback "the verdict is `not_available`" | the same quantities without a verdict field; under the fallback both intervals are null |
| the planted reporting-bias fixture "beats chance … yet fails the recommended D5 rule against the exposure rung" | it beats chance (toroidal-null p < 0.05), and the lower bound of its defined paired difference interval against the exposure rung is not above 0 |
| (none) | new, for D2b: with readings all below 0.15 m, 89% reported gives `unknown` and 90% gives `observed_dry`; a block with fewer than 90% reported and a maximum ≥ 0.15 m gives `observed_wet`; a gap never makes a block dry |

The fixture still shows the failure BKK-056 exists to catch: a surface that
only tracks exposure beats chance but not the exposure rung. An interval
wholly below 0 passes too, as it would have failed the old rule. The bound is
a test assertion only; the record itself still carries no verdict.

## 5. Open points, decided in later PRs

None of these was put to North in BKK-056a. Each is proposed in the PR that
needs it and approved by North there, never chosen silently.

### Decided for BKK-056b (North, 10 November 2026)

North chose these in structured prompts in the BKK-056b session, from two to
four options each. One choice differs from the recommended option: the
rain-only rung's interpolation.

| Point | Chosen |
|---|---|
| Several sensors in one block | Wet if any sensor is wet. Dry only if every sensor is dry under D2b. Otherwise unknown. The record counts multi-sensor blocks and wet/dry conflicts. |
| Surface to block score | The wettest of the block's four 50 m lattice points: the maximum depth or index, or the nearest point for a distance rung. Points evaluated but not stored tie at the bottom, and AUC ties count 1/2. A coarser surface gives each point its cell's value. |
| Reported block with zero building cover | Both classes of a report case use only blocks with cover above zero. The record counts the reported blocks left out. |
| Rain-only rung | Inverse-distance weighting, power 2, over every admitted gauge with a complete accumulation in the window. A block centre on a gauge takes that gauge's value. A timed surface uses a locked number of hours before t; a declared scenario uses the event window. Chosen over the recommended nearest gauge. |
| Persistence rung | The same kind of observation in the equal-length window just before the scoring window: a sensor block's maximum depth, or a block's report count. A block with no prior observation ties at the bottom. |
| Building cover floor | A block with less than 1 m² of footprint has no cover, so a reprojection sliver never makes a building-free block a report control. Decided in review of the BKK-056b labels PR. |
| Chance and the correlogram on sparse labels | Section 3.4 (Q6 and Q7). |

### Still open

- **Minimum reports per published 1 km cell** (BKK-056c): a floor below which
  a cell is suppressed, so no published cell points to a single reporter.
- **The rain-only rung's accumulation hours before t** (BKK-056c): locked in the
  record with the other windows.
- **Scheduled readings** (BKK-056c): each sensor's reporting interval, taken
  from the admitted source and recorded at ingest, which D2b's 90% share
  counts against.
  Ingest also maps the source's sentinel values (negative or out-of-range
  depths) to gaps; the harness refuses any depth below 0 m rather than guess.
- **Event windows, seeds and held-out reservations** (BKK-056c): locked in the
  record before any score, naming the dates, areas and observations reserved
  for BKK-036B/C.
