# Historical BKK-009 concern resolution and current handoff

Updated 9 October 2026. This document began as task BKK-009, authorised to
address the 4 October concerns and update the project state. Its historical
baseline was merged PRs #1–#14 at main `9278893`, whose source tree matched the
tested `a5dfc51`. BKK-010–BKK-014 and the evidence update were subsequently
merged. This record is retained for attribution; it is no longer an unmerged
branch plan. No scientific method change is implied.

The current four-area method and release contract is
[MULTI_AREA_PLAN.md](MULTI_AREA_PLAN.md). It supersedes old slice-merge
instructions without rewriting the evidence produced under earlier commits.

## Historical ordered tasks and acceptance criteria

| Task | Change | Acceptance evidence |
|---|---|---|
| BKK-010 | Consolidate city grid, snapping and routing constants | Preserve 1,000 m public cells, 400 m snapping and 180 minute routing; regression tests cover overlap and routing limits. |
| BKK-011 | Share WorldPop resource identity and clarify source failures | Downloader and city manifest derive the same URL; missing/tampered sources fail explicitly; existing provenance tests pass. |
| BKK-012 | Publish spatial indexes atomically | An interrupted build cannot expose a partial final index; retry succeeds; existing final indexes are never replaced; incompatible indexes return unavailable, invalid requests still return 422. |
| BKK-013 | Explain map failures and display actual validation checks | Statistics errors/loading gate city details visibly; obsolete requests cannot replace the selected run; partial pagination cannot look complete; both city and pilot validation formats render. |
| BKK-014 | Record executable source identity | New pilot and city manifests record commit, tree and source digest; changed source blocks publication; missing Git identity is explicit; old manifests remain readable. |
| BKK-009 evidence | Reconcile the shared source and project state | README and implementation status withdraw obsolete numbers, cite the corrected run and independent population/mobility audits, distinguish source coverage from completeness, and identify remaining evidence owners. |

Implement as small, ordered PRs. Each code fix includes a failing regression
test, targeted verification, then the repository-wide checks where contracts
change. Fresh-context and separate cross-harness Claude reviews precede ready
status. The human owns merges.

## Current merged boundary and release status

Current `main` is `d58d08b0430cc47bf10ddb3279ee5b48472ca790`, tree
`07bcb0a988c11edc9ef7f0153f17ec0c7cfe8f11`. Human-merged PR #49 placed the
reviewed four-area stack on main. PR #50 fixed saved-network WKT precision, and
PR #51 fixed independent denominator reconstruction to sum original terminal
outcome records. Exact comparisons and the approved `1e-6` tolerances remain.

There is no accepted BKK-024 comparison. Release v1 stopped at the WKT replay
gate after two Khlong San bundles. Release v2 stopped at the denominator replay
gate after five of eight planned bundles. Both sets remain immutable negative
evidence and cannot be completed, patched or pooled with a later release.

## Next pre-release sequence

These are separate, small PRs targeting `main`; they are not a branch-to-branch
stack. One implementer commits at a time and a human performs every merge.

| Order | Change | Acceptance evidence |
|---:|---|---|
| 1 | Synchronise project status and historical concern labels | Current main/#49–#51, both failed releases, the active four-area contract and the absence of an accepted eight-run result are stated without changing historical run attribution. |
| 2 | BKK-021F named-pilot identity and traversal regression matrix | Direct configured/traversal IDs are bound correctly; unknown, mismatched or missing scoped named-pilot inputs fail without falling back to Khlong San. |
| 3 | Pipeline publication through saved artifacts and both API routes | A pipeline-produced Parquet/manifest bundle with fractional event seconds returns the same warning-relative weighted quantiles and canonical non-null denominator contract from both API routes. |
| 4 | Fresh BKK-024 release | Freeze one merged source/configuration/environment boundary, create eight new IDs, execute one dry/moderate pair per approved AOI and pass all eight run audits plus four pair audits before sharing metrics. |

## Scope and method decisions

- Keep numerical assumptions unchanged rather than recalibrating them during
  the consolidation. Calibration needs separate targets and acceptance tests.
- Compare registered population controls with modelled residents rather than
  treating registration counts as an event-time population estimate.
- Build a new index privately and install it without replacement rather than
  repairing an index already published inside an immutable run.
- Record source identity and reject source drift rather than calling a mixed
  revision run reproducible. Snapshot or isolated-process execution can be a
  later strengthening; before/after identity alone cannot detect a transient
  edit that is restored during execution.

## Evidence gates that code cannot satisfy

The 50 OSM district polygons leave 76.1429 km² of the current BMA geometry
unreconciled. The reason is unverified. Authoritative boundary reconciliation
and concept-matched population controls are required before district calibration.

No destination is an operationally verified refuge. Safe access, usable capacity,
operator, accessibility and inspection records require district/operator evidence.
The terrain catalogue lead is not an admitted elevation surface; datum,
bare-earth classification, hydraulic forcing and independent event validation
remain acquisition gates. Mobility remains uncalibrated against OTP controls.

Merged source closes the earlier open-edge flood-impedance, fixed-cohort,
weighted-quantile and denominator implementation defects. The failed releases
remain invalid evidence. Weighted-agent interpretation and mobility calibration
remain scientific concerns; source correction alone does not support calibrated
evacuation-performance claims.

## Verification and handoff

Run Python pipeline/API tests and the affected frontend tests, build and lint
when their code is in scope. Record exact outputs in PR descriptions and a dated
handoff. Record historical and failed release runs separately from current source
changes and never overwrite their output evidence. A passing source suite is not
permission to reuse a partial run set.

Project-wide status remains **DONE_WITH_CONCERNS** until the external evidence
gates and remaining scientific validation tasks are met; passing internal tests
does not establish empirical validity.
