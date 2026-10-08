# Remaining concern resolution

Task BKK-009, authorised by the request to address the concerns and update the
project state. Baseline: merged PRs #1–#14, main `9278893`, whose source tree
matches the tested `a5dfc51`. No scientific method change is implied.

## Ordered tasks and acceptance criteria

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

The paper audit also identifies pilot replay, open-edge flood impedance and
weighted-agent interpretation concerns. These must remain explicit in the shared
status; a source-pinned pilot rerun and a separately scoped behavioural change
are required before the paper claims calibrated evacuation performance.

## Verification and handoff

Run Python pipeline/API tests, frontend tests, production build and lint. Record
exact outputs in PR descriptions and a dated handoff. Show the application on
the corrected immutable city run. Record historical runs separately from current
source changes and never overwrite their output evidence.

Project-wide status remains **DONE_WITH_CONCERNS** until the external evidence
gates and remaining scientific validation tasks are met; passing internal tests
does not establish empirical validity.
