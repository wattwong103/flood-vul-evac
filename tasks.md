# BKK/FLOW — unfinished work

**Live list:** 11 October 2026; updated 20 October 2026 (paper scope,
BKK-016a, BKK-052, BKK-053, BKK-054) and 21 October 2026 (BKK-055)

**Baseline:** `main` at merge commit `959d6f9` (PR #77)

**Evidence boundary:** the admitted four-area release remains demonstration
evidence; the city layer has no current result.

**Paper scope (North, 20 October 2026):** a bounded methods/demonstration paper
on the four-area release: one-at-a-time sensitivity (BKK-016a), related work
(BKK-052) and the observed-extent check (BKK-053). The citywide P0 gates
(BKK-034 to BKK-040) are stated future work in the manuscript, not submission
blockers. They still gate any citywide claim.

This is the forward-looking task list. Completed release work is intentionally
absent. Historical detail stays in
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md), while exact
release identities stay in
[`docs/RELEASE_EVIDENCE_2026-10-11.md`](docs/RELEASE_EVIDENCE_2026-10-11.md).

## How to use this list

- `READY` means the next owner can write a bounded implementation plan.
- `DECISION` means North or the scientific owner must choose the stated
  interpretation before implementation.
- `EXTERNAL` means the project needs evidence, data, permission or an account
  it does not currently hold.
- `BLOCKED` means another numbered task must pass first.
- `PARKED` means real work, but not part of the next pass.
- `IN PROGRESS` means a named owner has open work or pull requests against the
  task.

Each implementation task gets its own branch, tests and pull request. A task is
closed only when every acceptance criterion is evidenced. New data and run
outputs remain outside Git.

`Data steward` is currently an unassigned project role responsible for source
acquisition, licence review and checksum evidence. North must name or accept a
holder before work assigned to that role starts.

## Priority order

| Priority | Task | State | Next owner | Depends on |
|---|---|---|---|---|
| P0 | BKK-033 — durable release deposit | EXTERNAL | North / archive account owner | — |
| P0 | BKK-034 — population concept and independent controls | DECISION | North + population owner | — |
| P0 | BKK-035 — authoritative Bangkok boundary reconciliation | EXTERNAL | Data steward + North | — |
| P0 | BKK-036A — resolve citywide bare-earth terrain | EXTERNAL | Data steward | BKK-035 |
| P0 | BKK-036B — event forcing and observations | EXTERNAL | Data steward + flood owner | BKK-035 |
| P0 | BKK-036C — hydraulic model and held-out validation | BLOCKED | Flood-model owner | BKK-036A, BKK-036B |
| P0 | BKK-037 — verified evacuation destinations and capacities | EXTERNAL | Data steward + operators | BKK-035 |
| P0 | BKK-038 — Bangkok mobility calibration and joint sensitivity | DECISION | Mobility owner | BKK-034 |
| P1 | BKK-039 — Bangkok building-height validation | EXTERNAL | Data steward + exposure owner | BKK-035 |
| P1 | BKK-040 — admitted citywide run | BLOCKED | Scientific owner + implementer | BKK-034, BKK-035, BKK-036A/B/C, BKK-037, BKK-038, BKK-039, BKK-041 |
| P1 | BKK-041 — directed vehicle routing | READY | Implementer | — |
| P1 | BKK-042 — explicit run-scale identity in the UI | READY | Implementer | — |
| P1 | BKK-043 — comparison-figure presentation repair | READY | Implementer | — |
| P1 | BKK-044 — external release-ledger verifier | DECISION | North, then implementer | — |
| P1 | BKK-045 — machine-readable validation output | READY | Implementer | — |
| P1 | BKK-046 — reconcile stale status documentation | READY | Documentation owner | — |
| P1 | BKK-047 — expose the admitted pilot release in the app | BLOCKED | App owner | BKK-044 |
| P2 | BKK-048 — profile frontend performance concerns | PARKED | Implementer | — |
| P2 | BKK-049 — harden named-pilot identity edge cases | PARKED | Implementer | — |
| P2 | BKK-050 — complete paper metadata and ODbL statement | READY | Paper owner + authors | — |
| P2 | BKK-016a — four-area one-at-a-time sensitivity ensemble | IN PROGRESS | Implementer (sensitivity session; PR #79) | — |
| P2 | BKK-051 — prepare a submission package | BLOCKED | Paper owner | BKK-033, BKK-050, BKK-016a, BKK-052, BKK-053 |
| P2 | BKK-052 — related work and novelty defence | IN PROGRESS | Paper owner (related-work session) | — |
| P2 | BKK-053 — observed-extent plausibility check | IN PROGRESS | Paper owner (design note), then North (metric) | — |
| P1 | BKK-054 — GSW water-share denominator (yearly code 0 is mostly never-water) | IN PROGRESS | Implementer (BKK-054b PR), then paper owner | — |
| P1 | BKK-055 — site flood views: the flood, trips cut off, flood observations | IN PROGRESS | Implementer (BKK-055a design PR), then app owner | BKK-055h waits on PR #94 for 2010/2011 |

## P0 — evidence needed before stronger scientific or citywide claims

### BKK-033 — Deposit the admitted release independently

- Preserve the 239-file candidate and sibling ledger without changing either.
- Deposit the ZIP in durable storage controlled independently of this working
  Dropbox and obtain a stable public identifier or DOI.
- Record the deposit URL, identifier, licence, date, ZIP byte count and SHA-256;
  retrieve it again and verify SHA-256
  `e93fe4cebc965a5bd706908d0504468d1c949149f897a77f9e368c2d6a87403f`.
- Link the stable record from the repository and manuscript. A local copy or a
  repository release alone does not close this task.

### BKK-034 — Choose and ingest independent population controls

Decision required: choose whether the primary target is resident, registered
or de-facto/event-time population, and name its reference date. Keep the other
concepts as separate quantities rather than silently treating them as equal.

- Retrieve the exact approved DOPA/NSO resource with resource-level reuse
  terms, retrieval timestamp and checksum.
- Build and test a 50-district geography/date crosswalk; report every unmatched
  or changed unit.
- Publish raw WorldPop, official-control and reconciled totals side by side,
  with discrepancies and uncertainty by geography.
- Change the population version whenever control choice, crosswalk or weights
  change. Do not modify the admitted release retrospectively.

### BKK-035 — Reconcile the metropolitan and district boundaries

- Obtain an authoritative BMA and 50-district geometry with explicit reuse
  permission, or record a reviewed decision to retain the OSM geometries.
- Compare validity, CRS, topology, area and union coverage against the admitted
  OSM boundaries and publish the spatial differences.
- Recompute rather than repeat the historical `76.1429 km²` discrepancy; it is
  not a current city result until reproduced on the admitted boundary set.
- Version the accepted geometry and add boundary-mismatch regression tests.

### BKK-036A — Resolve a citywide bare-earth terrain source

- Resolve whether the RTARF/RTSD catalogue leads to downloadable elevation
  tiles covering Bangkok; a survey index alone is insufficient.
- Record tile identities, access and redistribution terms, horizontal CRS,
  vertical datum, ground classification, resolution and checksums.
- Validate a representative Bangkok sample against independent checkpoints and
  publish bias/error by terrain setting.
- If RTARF/RTSD tiles are inaccessible or unfit, record the negative finding and
  evidence, keep BKK-036C and BKK-040 blocked, and open an approved alternative-
  source task before closing this investigation.
- Do not substitute SRTM-lineage or Copernicus DSM values for flood depth. See
  [`docs/CITY_SCALE_LIMITATIONS.md`](docs/CITY_SCALE_LIMITATIONS.md).

### BKK-036B — Admit forcing and event observations

- Select a historical event with timestamped rainfall, river level and tide
  boundary series plus time-specific observed flood extent.
- Licence-check, checksum and gap-audit every series; define timezone, datum,
  units and interpolation rules.
- Reserve observations, dates or areas for held-out validation before fitting.
  JRC annual water may be contextual evidence but is not event depth or timing.

### BKK-036C — Build and validate the city flood model

- Before coding, approve a method note choosing a shallow-water or storage-cell
  formulation and documenting drainage, infiltration, roughness, grid and time
  step assumptions.
- Pass mass-conservation, numerical-stability and resolution tests.
- Report calibration and held-out extent/depth metrics separately, including
  uncertainty and failure cases.
- Keep outputs labelled `modelled`; no result becomes operational through this
  task alone.

### BKK-037 — Verify evacuation destinations and integer capacities

- Replace hypothetical pilot destinations and unverified OSM candidates with
  operator-reviewed records carrying operator, status, capacity basis,
  accessible entrance, usable floor, opening conditions and inspection date.
- Record source, reuse terms and evidence for every field; unknown capacity
  remains null, never zero or an inferred default.
- Verify flood-safe access under the selected event before a destination is
  routable. Preserve the model's integerized-capacity conservation contract.

### BKK-038 — Calibrate mobility and run interaction-aware sensitivity

Decision required: define the OTP target population, trip purposes, mode set,
time periods and meaning of weighted agents.

- Calibrate trip rate, timing, purpose, destination and mode jointly against
  reusable Bangkok evidence. The documented OTP control is 1.97 trips/person/day
  versus 3.712 in the legacy pilot audit; do not conceal that mismatch with one
  post-hoc multiplier. See
  [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).
- Compare spatial/temporal volumes at 1 km or coarser on held-out evidence.
- Add a preregistered multi-parameter design covering mobility, warning,
  compliance, preparation, capacity and flood impedance interactions.
- Publish parameter bounds, seeds, convergence, uncertainty intervals and
  sensitivity rankings. Until these pass, retain `demonstration` status.

## P1 — engineering and publication readiness

### BKK-039 — Validate building height locally

- Ingest the approved 2023 Open Buildings 2.5D layer as an estimated exposure
  attribute with immutable source identity.
- Compare it with a representative trusted Bangkok sample and report coverage,
  bias and error by height band and urban form.
- Never infer occupancy, structural safety, refuge eligibility or capacity from
  height alone.

### BKK-040 — Produce a new citywide result

- Start only after BKK-034, BKK-035, BKK-036A, BKK-036B, BKK-036C, BKK-037,
  BKK-038, BKK-039 and BKK-041 pass their gates.
- Stage all of Bangkok from one accepted boundary and source set, then produce
  immutable baseline and event runs with complete manifests.
- Pass saved-run replay, source-drift, denominator, spatial-coverage and paired
  comparison audits before publishing any city number.
- Keep the current state as **no current city result** until all criteria pass;
  never revive the superseded BBBike-era run.

### BKK-041 — Respect vehicle direction and access restrictions

- Preserve OSM `oneway`, directional and access restrictions in vehicle graphs;
  keep pedestrian semantics separate.
- Add regression fixtures for forward/reverse one-way travel, access exclusions,
  contraflow exceptions and parallel edges.
- Block publication of vehicle results when the graph contract is absent or
  inconsistent.

### BKK-042 — Resolve scale before rendering the stage rail

- Publish or derive an explicit `pilot`/`city` scale for every supported run.
- Do not default a scale-unknown run to the canonical pilot rail; show recorded
  stages only, or a clear unavailable state.
- Test pilot, city, missing-scale, stale response and error-state cases.

### BKK-043 — Repair future comparison figures

- Fix report generation so long footers fit, p95 values use the approved display
  precision and network counts are labelled `edges`, not `ways`.
- Add a rendering/content regression test for Sai Mai-sized labels and values.
- Apply the fix only to newly generated reports. Do not rewrite the frozen
  11 October release candidate or its checksums.

### BKK-044 — Implement the external release-ledger verifier

Decision required: approve or amend the version-1 schema and forbidden scratch
name list in
[`docs/EXTERNAL_LEDGER_VERIFIER_DESIGN.md`](docs/EXTERNAL_LEDGER_VERIFIER_DESIGN.md).

- After approval, implement the explicit release-root/ledger CLI tests-first.
- Reject malformed or duplicate-key JSON, unsafe/duplicate paths, symlink or
  junction escape, missing/extra/non-regular files and size/hash mismatch.
- Run manifest, saved-run replay and fixed-cohort pair checks against the
  supplied external root, never an implicit repository `runs/` directory.
- Emit deterministic machine-readable output and remain read-only. Verification
  must not publish, repair or scientifically promote a release.

### BKK-045 — Keep validation output valid for machines

- Remove the `[:4000]` truncation from `pipeline/run.py validate`, or provide a
  separately named human summary while stdout remains complete JSON.
- Add a regression payload longer than 4,000 characters and prove stdout parses
  and contains the final checks.
- Keep the saved `validation.json` authoritative and document the CLI contract.

### BKK-046 — Reconcile status documentation

- Update the remaining-concerns table to close the completed BKK-024 replacement
  release, BKK-018 diagnostics and completed portion of BKK-019.
- Replace stale 10 October test/run directions and obsolete README limitations
  without rewriting dated historical records.
- Retain the real open scale-unknown rail, city-science and calibration concerns;
  link to this live list instead of duplicating a second backlog.

### BKK-047 — Expose the admitted pilot release in the app

- Begin only after the repository verifier passes against the exact admitted
  candidate.
- Register the four pilot pairs without copying generated data into Git and show
  their demonstration status, denominators and limitations in the UI.
- Refuse partial, altered or unverifiable releases and keep superseded city
  results unavailable.

### BKK-055 — Add the flood, trips-cut-off and flood-observation views

Designed with North on 20 October 2026 in
[`docs/SITE_FLOOD_VIEWS_DESIGN.md`](docs/SITE_FLOOD_VIEWS_DESIGN.md). Past and
what-if floods only; no live view. North decided that the site may show the
MitrEarth/GISTDA mapped footprints (BKK-053 D8 still governs journal figures)
and that the views use new demonstration runs, labelled as separate from the
11 October release.

- Eleven ordered tasks, BKK-055a to BKK-055k, one PR each, tests first
  (design note §7). BKK-055a is the design note and this entry.
- The flood: how big, how deep and can people move, for what-if floods in the
  four pilots; past years show depth as Unknown and movement as Not yet.
- Trips cut off: everyday trips inside the district, classed unaffected,
  detour or no route, plus whether people can still reach an open road exit.
  Never called commutes; never drawn as individual trajectories.
- Flood observations: what the project holds, and replay of mapped past floods
  through roads and trips. Replay closes roads directly and never becomes a
  depth surface; 2011 is replayed only inside the pilot AOIs (BKK-053 D1).
- Replay of 2010 and 2011 waits on PR #94. Nothing here edits the admitted
  release or cites a city result before BKK-040.

## P2 — parked maintenance and paper handoff

### BKK-048 — Profile frontend performance before changing it

- Measure viewport count repetition, visibility-toggle refetches and anchor-loop
  cost on representative pilot and city fixtures.
- Open targeted tasks only for reproduced bottlenecks; preserve pagination,
  completeness warnings and scientific semantics.

### BKK-049 — Harden named-pilot identity edge cases

- Add platform-aware absolute, nested, dot-segment and backslash traversal
  rejection cases.
- Add wrong-AOI network, building and population version-label negatives.
- Tighten the parked error-message assertion and rename the misleading test
  helper without changing production behaviour.

### BKK-050 — Complete manuscript metadata and data attribution

- Preserve the confirmed author order: Watcharapong Wongkaew, Pongsun
  Bunditsakulchai, Fuko Nakai and Yoshihide Sekimoto.
- Supply verified affiliations, corresponding-author email and any journal-
  required ORCIDs. Funding and competing interests remain `None` unless an
  author corrects them.
- Retain the agreed privacy/ethics and CRediT declarations; obtain co-author
  approval rather than inferring roles or institutional determinations.
- Add a manuscript-specific ODbL attribution/produced-work statement consistent
  with the actual OSM-derived artefacts and the target journal's data policy.

### BKK-016a — Run the four-area one-at-a-time sensitivity ensemble

In progress since 20 October 2026 as PR #79, kept as one pull request by North's
decision. Size concern: about 1,200 changed lines against the ~300-line
guideline. This is the one-at-a-time part of the MEDIUM BKK-016 item in
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

- Record a case table of approved levels: each case moves one factor (flood
  severity, compliance, warning reach or mean preparation delay) away from the
  baseline.
- Run every case with predrawn departure draws (`predraw-v1`).
- Publish the ensemble report only after the saved-run replay audit passes for
  every case.
- Run the four admitted pilots from merged `main`; outputs stay outside Git.
- This is not calibration and not an interaction study; both remain BKK-038.
  Report the results as scenario sensitivity for the named areas only.

### BKK-051 — Prepare the paper submission package

- Scope decided 20 October 2026 (North): a bounded methods/demonstration paper
  built on BKK-016a, BKK-052 and BKK-053. State in the manuscript that the
  citywide P0 gates (BKK-034 to BKK-040) are future work.
- Rebuild and inspect the final PDF, verify citations and claims, and prepare the
  journal-specific source, figures, supplement, data/code availability statement
  and cover letter.
- Point to the durable release identifier and exact code/release boundary; do
  not imply citywide, calibrated or operational validity.

### BKK-052 — Write the related work and novelty defence

In progress since 20 October 2026. Needs no repository code.

- Drafts go to `Research/flood-landuse/papers/bkkflow/drafts/` under the
  Dropbox root, outside this repository.
- Close it under the workspace documents rule: claims traced, citations
  verified, novelty checked against prior art, fresh-context review.

### BKK-053 — Check modelled flood extent against observed extent

In progress since 20 October 2026. A design note is being drafted at
`Research/flood-landuse/papers/bkkflow/analysis/observed-extent-check-design.md`
under the Dropbox root.

- Decision required: North picks the comparison metric from the design note.
  The implementation task is opened only after that choice.
- Extent-only plausibility check. Observed extent never feeds the depth surface
  and never tunes the flood model.
- It is not held-out hydraulic validation, which remains BKK-036B and BKK-036C.

### BKK-054 — Fix the GSW water-share denominator

Found on 20 October 2026: about 99% of the BMA's yearly GSW code-0 pixels lie
outside the JRC Maximum Water Extent, so they were never detected as water.
Every "share of classified" divided by code ≠ 0 and overstated water 5.7–6.0×;
water km² were unaffected. BKK-054a (PR #85) registered the extent tile. For
BKK-054b, North chose recoding with the extent: share = water ÷ (AOI − unknown).

- A failing regression test lands first: code 0 outside the max extent stays in
  the denominator, and water km² are unchanged.
- One decoder serves `measure_year` and `build_observed_cells`. `aoi_area_km2`
  is renamed `classified_km2` through the city run, report, API and site.
- Without the extent tile the share is null with a reason, never water ÷
  classified.
- README and `docs/IMPLEMENTATION_STATUS.md` figures come from a fresh BMA city
  run, not hand edits. Nothing under `bkkflow-release-archives/` is touched.
- Paper owner, outside this repository: `bkkflow-paper.tex:267,274` and
  `CLAIMS.md:49` need rewording.

## Invariants for every next pass

- Never edit, regenerate or silently replace the admitted 11 October release.
- Never cite a current city result until BKK-040 passes.
- Never convert missing data to zero or a scenario assumption to an observation.
- Never place downloaded data, run outputs, archives or manuscripts in this
  source repository.
- Record exact commands, test results, run identifiers and unresolved concerns
  in each pull request and handoff.

**DONE_WITH_CONCERNS** — the merged release is closed; every known unfinished
item is either actionable, in progress, decision-gated, externally gated or
explicitly parked above.
