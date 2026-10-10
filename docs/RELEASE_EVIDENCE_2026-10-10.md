# Four-area release evidence — 10 October 2026

The four-area demonstration release contains eight immutable runs: one dry and
one moderate run for each of Khlong San, Sai Mai, Din Daeng and Min Buri. The
runs were produced at commit
`f4662880523c71a8439750a7fca282c5d488d97e`, source tree
`1fe700d33c2ed6c18aa1adc23caa09c9cf39d773`, with a clean working tree and
`matched_before_publication` source verification.

All eight independent run audits and all four dry/moderate pair audits pass.
The pair reports contain three figures and one evidence Markdown file per AOI.
This establishes an internally consistent demonstration set; it does not
establish empirical validity, calibrated behaviour or operational suitability.

## Verified local evidence copy

The generated runs and reports remain outside Git. A verified local evidence
copy is held in the human-managed Dropbox item:

- filename: `bkkflow-four-area-2026-10-10.zip`
- byte size: `163343745`
- SHA-256: `81236b5d0f483ab205ae66c153f57dcd111bee7b5ba7ac1c74a7d33725d3b05b`
- contents: eight run directories, four pair-report directories, the original
  checksum ledger and an archive note (`187` file entries in total)

This is a local evidence copy, not a durable or independent off-machine
archive. Dropbox sync can propagate deletion, so the package hash detects a
change but cannot restore a deleted package.

The original ledger is retained inside the package as audit history. It records
`185` declarations and independently re-hashed with zero missing, size or hash
mismatches and no undeclared files at the time of review. One declaration is
`.probe.txt`, a three-byte write probe created after the Khlong San moderate
simulation. The probe is preserved but is operational residue, not a model
output. The canonical evidence set therefore consists of the other `184` run
and pair-report files.

## Boundary and interpretation

Current source is newer than the release boundary. Later fixes do not
retroactively change or reattribute the eight runs:

- PR #61 adds age-structure identity to manifests of new runs; the release
  manifests predate it.
- PR #62 makes pair-report publication robust on synced folders; the four
  reports were subsequently published without changing run data.
- PR #63 repairs an unexercised terrain-ingestion path.
- PR #64 clears repository-wide lint findings.

The release's staged pilot population versions do not identify that per-cell
age/sex data were enabled. Correcting that label requires re-staging all four
pilots and generating a new eight-run release; the existing run files must not
be edited. Age rasters also leave a small, AOI-dependent population weight with
`age_band = "unknown"`; known-band shares are conditional on covered cells.

Dry clearance is not a zero-time or pure-distance baseline. It is an
arrivals-only, warning-relative measure that includes preparation delay and
route travel without flood impedance. Moderate clearance uses the same cohort
and behavioural assumptions with the configured flood impedance.

The older city results remain superseded. Re-staging from the admitted
Geofabrik snapshot increased the mapped inventory by 71% for road ways and 57%
for buildings relative to the old BBBike cache. This is a before/after source
inventory comparison, not a ground-truth completeness estimate. No current city
run exists on the re-frozen source.

## Use in the paper and app

Paper and demonstration views may use the eight pilot runs only when they name
the `f466288` release boundary, retain the demonstration label, state the
population-version and age-coverage limitations, use sample denominators, and
avoid causal, calibrated or operational claims. They must not mix in failed
release attempts or present superseded city values as current.

DONE_WITH_CONCERNS
