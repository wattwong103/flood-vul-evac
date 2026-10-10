# Pseudo-PFLOW (Japan) vs BKK/FLOW (Bangkok) — capability gap

Purpose: answer "check what they have, check github, and see what we can do".
Written 10 October 2026. Every Pseudo-PFLOW claim below is cited; every
BKK/FLOW claim is from this repository's code or docs.

**Headline: BKK/FLOW is not yet better than Pseudo-PFLOW as a mobility dataset.**
Pseudo-PFLOW has census-derived person attributes, calibrated behaviour and
validated accuracy. BKK/FLOW now has modelled per-cell age for covered
population, but still lacks census household composition, calibrated behaviour
and external accuracy validation; sex remains a scenario prior. What BKK/FLOW
has that Pseudo-PFLOW does not is **evidence integrity and a hazard dimension**.
That is a real differentiator, but it is not a substitute, and claiming
otherwise would be the fastest way to lose a reviewer's trust.

---

## 1. What Pseudo-PFLOW actually delivers

### Products

| Product | Content |
|---|---|
| Population | Per-person household composition, age, gender, employment status, home address |
| Activity | Per-person daily "when / where / what", with start time, duration, purpose, location |
| Trip | Per-person "who / when / what purpose / from where → to where / what mode" |
| Trajectory | Per-person position every few seconds, GPS-like, with link id |
| Dynamic population | 500 m mesh, **every 10 minutes** |
| Link volume | Road-network traffic volume, **hourly** |
| Business traffic | Freight truck and taxi one-day trajectories, separate dataset from v3.0 |

Seven activity types: home, work, school, shopping, dining, medical, other.

*Sources: [Kashiyama et al. 2022, arXiv:2205.00657](https://arxiv.org/abs/2205.00657);
[Kashiyama et al., nationwide dataset paper](http://sekilab.iis.u-tokyo.ac.jp/wp-content/uploads/poster_pseudopflow_pang.pdf);
[Pseudo-PFLOW data provision page](https://pflow.csis.u-tokyo.ac.jp/data-provision-service/about-pseudo-people-flow-data/);
[Specification v2.0](https://pflowwp.sekilab.global/wp-content/uploads/Pseudo-PFLOW-Specification-ver2.0.pdf).*

### Scale and claimed accuracy

- All **1,724 municipalities**, 47 prefectures, approximately **130 million people**.
- **R² = 0.81** against mobile-phone location data at 1000 × 1000 m resolution.
- Coefficient of determination **0.5 – 0.98** across population distribution, trip volume and trip coverage.

*Sources: arXiv:2205.00657; Shibuya et al. (researchmap 50276768); poster PDF.*

### How the generator works — from the local implementation

The local Java workspace at `H:\Dropbox\PFLOW\Pseudo-PFLOW` (`README.md`) gives
the actual pipeline:

| Step | Entry point | What it does |
|---|---|---|
| 1 | `pseudo.pre.PersonGenerator` | Household CSV → Person CSV (census household data) |
| 2 | `pseudo.gen.ActivityGenerator` | Census + **Markov chain + multinomial logit** → Activity CSV |
| 3 | `pseudo.gen.TripGenerator_WebAPI_refactor` | Activity → Trip + Trajectory, routing via **CSIS WebAPI** |
| 4 | `pseudo.gen.FileJoinner` | Trajectory → ZIP per city |
| 5 | `pseudo.aggr.MeshVolumeCalculator` | Trajectory → 500 m mesh population per 10 min |
| 6 | `pseudo.aggr.LinkVolumeCalculator` | Trajectory → link volume per hour |

A legacy offline path exists: `pseudo.gen.TripGenerator` (local mode choice)
plus `pseudo.gen.TrajectoryGenerator` (trip + DRM road network → trajectory).

Two details matter for any comparison:

- **Routing is an external credentialed service.** The mainline pipeline calls
  the CSIS WebAPI for road *and transit* routing, needs `PFLOW_API_USER` /
  `PFLOW_API_PASS`, and fails fast when unavailable. The offline path uses a DRM
  road network.
- **Behaviour is actively tuned.** A Latin-Hypercube framework
  (`scripts/tuning/`) calibrates mode choice over **7 parameters** against
  prefecture-specific mode-share targets. For prefecture 22 the reported best
  loss is **214.39 vs a 320.77 baseline**.

### GitHub status — checked 10 October 2026

The 2022 JHPCN report states the generation code is published at
`https://github.com/sekilab/DSPFlow`. That URL now returns **HTTP 404**, via
both the web UI and the REST API. The repository is therefore not publicly
reachable under that name — it may be private, renamed or withdrawn.

This matters: the code is not publicly verifiable by a third party at the
cited location, and the dataset itself is distributed only through JoRAS on
application. **Reproducibility by an outside group is currently weak.**

---

## 2. Head-to-head

| Capability | Pseudo-PFLOW (JP) | BKK/FLOW (Bangkok) | Verdict |
|---|---|---|---|
| Person age / sex / household | Census-derived, per person | Modelled per-cell age for covered population; missing coverage stays `unknown`; sex is a scenario prior; no household synthesis | **JP ahead** |
| Behaviour calibration | Markov + MNL, LHS-tuned to mode-share targets | Two-mode generator, explicitly uncalibrated; OTP control 1.97 trips/person/day vs pilot audit 3.712 | **JP ahead** |
| Accuracy validation | R² 0.81 vs mobile phone; R² 0.5–0.98 across metrics | Internal checks only; a calibrated-mobility claim is explicitly rejected | **JP ahead** |
| Geographic scale | 1,724 municipalities, 130 M people | 5.96 km² pilot + 1,643 km² city | **JP ahead** |
| Mesh cadence | 500 m every 10 min | 1 km public grid; 300 s flood slices | **JP ahead** |
| Transit routing | Road + transit via WebAPI | Walk + vehicle only; city routing is **undirected** | **JP ahead** |
| Freight (truck/taxi) | Separate dataset | None | **JP ahead** |
| **Flood / hazard** | **None** | JRC observed annual water; scenario depth; connectivity screening | **BKK ahead** |
| **Evacuation** | **None** | Warning reach, compliance, delay, capacity, arrival/unserved/trapped | **BKK ahead** |
| **Source licence gate** | Sources pulled from an opaque `S3://pseudo-pflow/processing` bucket | Public **and** explicitly reusable required; `verify` can never enter a run | **BKK ahead** |
| **Observation/scenario separation** | Not stated | `source_role` is a required column, not a caption | **BKK ahead** |
| **Unknowns** | — | Unknown written as `null`, never `0` | **BKK ahead** |
| **Denominators** | Manifest = prefecture, mfactor, file counts, timestamp | Explicit sample denominators, no silent reweighting, terminal conservation ΣW_k = W_C | **BKK ahead** |
| **Independent verification** | Validation script on the same outputs | BKK-015e reconstructs a run from saved artefacts *without* the runner's helpers, to 1e-6 / 0.01 tolerances | **BKK ahead** |
| **Run immutability** | — | Source digest before/after publication; drift refuses publication | **BKK ahead** |
| **Offline reproducibility** | Needs CSIS WebAPI credentials for the mainline path | Fully local, no external service | **BKK ahead** |

The pattern is consistent: **Pseudo-PFLOW wins on behavioural realism and
scale; BKK/FLOW wins on evidence discipline.** Neither is "better" overall —
they are different axes.

---

## 3. Historical age-attribute gap and its resolution

Pseudo-PFLOW's first product is per-person demographics. Before per-cell age was
enabled, BKK/FLOW shipped **`age_band = "unknown"` for 100% of people**.

That was the right call for the evidence available to that code path: an
invented age distribution presented as data would have been worse. The audit
then found that its justification was contradicted by the project's own source
registry, which prompted the source acquisition and per-cell work below.

The pre-enablement runner recorded in this audit hardcoded:

```python
age_bands=None,  # no age source passed the gate: recorded as unknown
```

and reported `"age_structure_source": "none_passed_licence_gate"`.
The city runner similarly used a declared sex prior. These are historical
diagnostics, not the current age-availability state; sex remains a prior.

At that stage `data/source-registry.json` already contained **two approved,
licence-cleared sources that were not yet wired in**:

| source_id | Dataset | Licence | Status |
|---|---|---|---|
| `worldpop-tha-age-sex-2026-r2025a` | Thailand age and sex structures 2026 R2025A | CC BY 4.0 | `approved` |
| `nso-dopa-population-district-sex-2564-2568` | Registered population by area, sex, district, 2021–2025 | CC Attribution | `approved` |

The base capability to apply one age mapping was **already implemented**:
`population.assign_demographics(cells, *, sex_shares, age_bands)` normalised
and applied band weights, but no caller then supplied the source. The current
implementation also accepts per-cell bands and reports missing coverage.

The audit therefore moved from plumbing to the geographic applicability test
below. That test led to the current per-cell implementation, rather than use of
the unsuitable national marginal.

### Feasibility verified 10 October 2026 — with two corrections

The source was probed, not assumed. Dataset: **Thailand 100m Age and Sex
Structures, 2026, R2025A v1, Constrained**, EPSG:4326, float32, nodata −99999,
CC BY 4.0, DOI `10.5258/SOTON/WP00841`.

Download pattern is `tha_{sex}_{band}_2026_CN_100m_R2025A_v1.tif` where
`sex` ∈ {m, f, t} and `band` ∈ {00, 01, 05, 10 … 90} (**20** bands).

**Correction 1 — at the feasibility stage this required one wiring step plus a
2.5 GB acquisition, not just wiring.** The marginals are not published as a
table; they must be derived from the rasters:

| Need | Files | Size |
|---|---:|---:|
| Age-band marginals | 20 × `tha_t_*` | ≈ 2.3 GB |
| Sex split | `tha_T_M_*`, `tha_T_F_*` | ≈ 232 MB |
| **Total** | **22** | **≈ 2.5 GB** |

An earlier revision said 19 bands and 21 files. Both were wrong; the count is
verified from the acquired files.

### Marginals now acquired and computed

All 22 rasters were downloaded and summed. Evidence records, tracked under
`data/curated/population/` because `data/staged/` is deliberately git-ignored:

| File | Contents |
|---|---|
| `age_sex_national_marginals.json` | totals, shares, per-file SHA-256, applicability status |
| `age_sex_national_totals.json` | raw unrounded per-band counts |
| `age_sex_source_checksums.json` | SHA-256 and byte size for all 22 rasters |

| Quantity | Value |
|---|---:|
| Male | 34,806,145 |
| Female | 36,786,775 |
| M + F | 71,592,920 |
| Σ 20 age bands | 71,592,911 |
| **Residual** | **−9 people (−1.3 × 10⁻⁷)** |

The two independent routes — 20 age bands versus two sex totals — agree to
within **9 people out of 71.6 million**. That is a strong internal check on both
the acquisition and the computation.

Derived national structure:

| Group | Share |
|---|---:|
| Under 15 | **14.25 %** |
| Working age 20–64 | 63.50 % |
| 65 and over | 16.35 % |
| Male / female | 48.62 % / 51.38 % |

### Historical national-marginal decision — do not apply these to the pilot AOIs

**Sex needs no change.** The measured national split (48.62 / 51.38) sits within
**0.28 percentage points** of the existing declared prior (48.9 / 51.1). The
prior was already close; leave it.

**Age must not be applied at national level.** These are *national* marginals.
The four pilot AOIs are inner-Bangkok districts — Khlong San 5.96 km², Din Daeng
8.46 km², Sai Mai 43.34 km², Min Buri 59.99 km². Assigning a **14.25 %** national
under-15 share to every cell of an inner-Bangkok district would materially
overstate children and distort trip generation, because school-age and
pre-school children do not drive and travel on a different pattern.

At this audit stage the national-marginal artefact was recorded as
`status: NOT_APPLIED`, and the then-visible `age_band: unknown` gap stayed open.
That historical decision remains correct for the national marginal, but the
availability statement is superseded by the per-cell implementation below.

### Per-cell sampling changed the recommendation and is now implemented

The national marginal was rejected above on the grounds that it would erase
spatial variation. That claim was then **tested rather than asserted** by
sampling the acquired rasters at every pilot population cell with a
nearest-neighbour lookup — which is the declared reprojection the grid mismatch
calls for.

Artefact: `data/curated/population/age_sex_aoi_comparison.json`.

| Geography | under-15 | working 20–64 | 65+ |
|---|---:|---:|---:|
| **National Thailand** | **14.25 %** | 63.50 % | 16.35 % |
| Khlong San (678 cells) | 9.53 % | 65.63 % | 19.29 % |
| Din Daeng (1,019 cells) | 9.42 % | 70.53 % | 14.45 % |
| Sai Mai (5,205 cells) | 12.05 % | 69.70 % | 12.34 % |
| Min Buri (7,206 cells) | 13.12 % | 70.31 % | 9.48 % |

Divergence from applying the national marginal:

| AOI | under-15 error | 65+ error |
|---|---:|---:|
| Khlong San | −4.71 pp | +2.94 pp |
| Din Daeng | −4.83 pp | −1.90 pp |
| Sai Mai | −2.19 pp | −4.01 pp |
| Min Buri | −1.12 pp | **−6.87 pp** |

The national marginal is not a small approximation error. Across the four AOIs
the **65+ share ranges from 9.48 % to 19.29 %** — a factor of two — and the
national figure (16.35 %) is wrong by up to **6.87 pp in Min Buri**.

That difference matters for truthful demographic reporting, but it must not be
translated into an assisted-evacuation effect. The current model assigns
`assistance_need` from the sampled mobility profile's declared assistance flag,
not from `age_band`; it is not an independently calibrated probability draw.

**Therefore: per-cell age shares are the right reporting route, and they are now
implemented.** The rasters are acquired, checksummed and approved, and
`assign_demographics` accepts per-cell bands. This closes the age-availability
gap; it does not calibrate assistance or evacuation behaviour.

Temporal note: age/sex is **2026** while the population baseline is a **2020**
modelled surface. The comparison is structural, not contemporaneous, and any use
must declare that mismatch.

### Grid mismatch

Same CRS (EPSG:4326), resolution (0.0008333), dtype (float32) and nodata
(−99999), but **different dimensions**:

| Raster | Size | Bounds |
|---|---|---|
| `tha_t_30` (age/sex) | 9953 × 17824 | 97.3433, 5.6125, 105.6375, 20.4658 |
| `tha_ppp_2020` (population) | 9952 × 17816 | 97.3454, 5.6163, 105.6387, 20.4629 |

One column and eight rows apart. Consequence:

- **The national comparison is grid-safe but geographically unsuitable.** It
  aggregates each raster independently, so the one-column/eight-row mismatch
  does not affect the national percentages reported above.
- **Per-cell age structure now uses an explicit nearest-neighbour lookup.** The
  implemented path samples the age rasters at population-cell centres and
  reports uncovered population separately rather than silently aligning grids.

This is exactly the class of silent misalignment that would corrupt results
without raising an error. It is recorded here rather than left to be discovered
mid-implementation.

### What the implemented per-cell age wiring does and does not fix

Now fixed:
- `age_band` is sourced for covered population cells; missing coverage remains
  explicit as `unknown` and is reported rather than imputed.
- The age-attribute availability gap against Pseudo-PFLOW is closed, subject to
  the coverage and temporal caveats above.

Still **not** fixed:
- `sex_split` remains a declared scenario prior. The two sex-total rasters are
  acquisition QA inputs, not local sex calibration.
- Household composition. WorldPop age/sex is *modelled aggregate*; the registry
  note is explicit: "do not treat cells as individual records or exact
  household composition". Pseudo-PFLOW's census household synthesis stays ahead.
- Any behavioural calibration. That is the separate, larger gap below.

---

## 4. Remaining gaps, in priority order

| # | Gap vs Pseudo-PFLOW | Cost | Why it matters |
|---|---|---|---|
| 1 | **Age/sex validation and contemporaneity** | Medium | Per-cell age is implemented and coverage is reported, but the 2026 age structure is applied to a 2020 resident baseline, sex remains a declared prior, and new age-structured runs still need correct version labels and release evidence. |
| 2 | **Behaviour calibration** | High | Pseudo-PFLOW tunes 7 parameters to mode-share targets; BKK/FLOW declares priors. The paper already rejects a calibrated-mobility claim on the 1.97 vs 3.712 trips/person/day mismatch. Adopting a similar LHS framework against BMA Household Travel Survey targets is the honest path. |
| 3 | **Output cadence** | Medium | 500 m / 10 min mesh vs 1 km public grid. Not a correctness gap, but it limits comparability. |
| 4 | **Directionality** | Low | City routing is undirected; vehicle one-way restrictions unenforced. Already tracked as BKK-017. |
| 5 | **Transit** | High | No transit mode at all. Bangkok without transit is a structural difference, not a bug. |

Gap 4 is a tractable engineering change. Gap 1 requires validation and new-run
evidence rather than more wiring. Gaps 2 and 5 are research projects.

---

## 5. Where to claim superiority, honestly

The defensible claim is **not** "a better Pseudo-PFLOW". It is:

> A flood-exposure and evacuation platform built on the PFLOW people–activities–
> trips–trajectories contract, with a licence-gated provenance chain, immutable
> runs, explicit sample denominators, independent replay auditing, and a hazard
> dimension that Pseudo-PFLOW does not have — at the cost of uncalibrated
> behaviour and coarser aggregate cadence.

Anything stronger is not currently supported by the evidence. The value of this
document is that the list above is checkable, and most of it can be closed by
wiring sources that are *already approved in our own registry*.

---

## 6. Open questions for North

The earlier age-wiring question is resolved: per-cell age is implemented, while
the existing eight release bundles remain unchanged and do not gain age
assignments retrospectively. Any new age-structured run must carry its current
population version and coverage report.

1. Is the BMA Household Travel Survey obtainable with reuse terms? It is the
   only credible route to closing the calibration gap, and without it gap 2 is
   permanent.
2. Does the withdrawn Pseudo-PFLOW GitHub repository need requesting from the
   Sekimoto lab for comparison, or is the specification v2.0 plus the local
   Java workspace sufficient?

DONE_WITH_CONCERNS
