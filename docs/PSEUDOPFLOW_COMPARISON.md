# Pseudo-PFLOW (Japan) vs BKK/FLOW (Bangkok) — capability gap

Purpose: answer "check what they have, check github, and see what we can do".
Written 10 October 2026. Every Pseudo-PFLOW claim below is cited; every
BKK/FLOW claim is from this repository's code or docs.

**Headline: BKK/FLOW is not yet better than Pseudo-PFLOW as a mobility dataset.**
Pseudo-PFLOW has census-derived person attributes, calibrated behaviour and
validated accuracy. BKK/FLOW has none of those yet. What BKK/FLOW has that
Pseudo-PFLOW does not is **evidence integrity and a hazard dimension**. That is
a real differentiator, but it is not a substitute, and claiming otherwise
would be the fastest way to lose a reviewer's trust.

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
| Person age / sex / household | Census-derived, per person | **`age_band` = `unknown` for every person**; sex split is a config literal | **JP far ahead** |
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

## 3. The single biggest actionable gap

Pseudo-PFLOW's first product is per-person demographics. BKK/FLOW currently
ships **`age_band = "unknown"` for 100% of people**.

That is the right call *as things stand* — an invented age distribution
presented as data would be worse. But the justification recorded in the code
is now **contradicted by the project's own source registry**.

`pipeline/bkkflow/runner.py:321` hardcodes:

```python
age_bands=None,  # no age source passed the gate: recorded as unknown
```

and `population_qa` reports `"age_structure_source": "none_passed_licence_gate"`.
`pipeline/bkkflow/city_runner.py:361` similarly hardcodes
`sex_shares={"male": 0.49, "female": 0.51}`.

Meanwhile `data/source-registry.json` contains **two approved, licence-cleared
sources that are never wired in**:

| source_id | Dataset | Licence | Status |
|---|---|---|---|
| `worldpop-tha-age-sex-2026-r2025a` | Thailand age and sex structures 2026 R2025A | CC BY 4.0 | `approved` |
| `nso-dopa-population-district-sex-2564-2568` | Registered population by area, sex, district, 2021–2025 | CC Attribution | `approved` |

And the capability is **already implemented**:
`population.assign_demographics(cells, *, sex_shares, age_bands)` normalises
and applies band weights at `pipeline/bkkflow/population.py:247-253`. The
parameter exists; nothing passes it.

**So the plumbing is done and the input is approved. The gap is one wiring
step away.**

### What this would and would not fix

Would fix:
- `age_band` becomes sourced instead of `unknown` for every person.
- `sex_split` stops being a hardcoded 0.49/0.51 literal.
- Removes a HIGH-severity differentiator against Pseudo-PFLOW.

Would **not** fix:
- Household composition. WorldPop age/sex is *modelled aggregate*; the registry
  note is explicit: "do not treat cells as individual records or exact
  household composition". Pseudo-PFLOW's census household synthesis stays ahead.
- Any behavioural calibration. That is the separate, larger gap below.

---

## 4. Remaining gaps, in priority order

| # | Gap vs Pseudo-PFLOW | Cost | Why it matters |
|---|---|---|---|
| 1 | **Age/sex wiring** | Low | Implemented, source already approved. Closes the largest single attribute gap. |
| 2 | **Behaviour calibration** | High | Pseudo-PFLOW tunes 7 parameters to mode-share targets; BKK/FLOW declares priors. The paper already rejects a calibrated-mobility claim on the 1.97 vs 3.712 trips/person/day mismatch. Adopting a similar LHS framework against BMA Household Travel Survey targets is the honest path. |
| 3 | **Output cadence** | Medium | 500 m / 10 min mesh vs 1 km public grid. Not a correctness gap, but it limits comparability. |
| 4 | **Directionality** | Low | City routing is undirected; vehicle one-way restrictions unenforced. Already tracked as BKK-017. |
| 5 | **Transit** | High | No transit mode at all. Bangkok without transit is a structural difference, not a bug. |

Gaps 1 and 4 are tractable now. Gaps 2 and 5 are research projects.

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

1. Should the age/sex wiring ship as a scoped PR alongside #55/#56, or wait
   until the eight-run release is complete? Wiring it first changes the
   `population_version` and therefore invalidates any run produced before it.
2. Is the BMA Household Travel Survey obtainable with reuse terms? It is the
   only credible route to closing the calibration gap, and without it gap 2 is
   permanent.
3. Does the withdrawn Pseudo-PFLOW GitHub repository need requesting from the
   Sekimoto lab for comparison, or is the specification v2.0 plus the local
   Java workspace sufficient?

DONE_WITH_CONCERNS