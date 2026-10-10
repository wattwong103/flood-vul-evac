# External release-ledger verifier — design proposal

**Status:** design only; implementation is not approved by this document.

**Decision date:** 11 October 2026.

**Purpose:** verify a supplied release directory against a supplied checksum
ledger without generating, repairing, publishing or scientifically promoting
any release artefact.

## Decision and alternatives

Recommended option: a small pipeline CLI that accepts two explicit paths and
returns a machine-readable report outside the release root.

```text
python pipeline/verify_release.py \
  --release-root <existing-directory> \
  --ledger <existing-ledger.json> \
  [--report <path-outside-release-root>]
```

Alternatives considered:

1. **Recommended: repository CLI.** Reuses the current manifest, integrity,
   replay and pair checks and can be tested with temporary fixtures. It keeps
   verification beside the contracts it applies.
2. **One-off archival script.** Smaller initially, but it would duplicate
   containment and integrity logic and leave no reviewed regression contract.
3. **API or website endpoint.** Rejected for the first implementation because
   it expands the attack surface, encourages operators to point a service at
   arbitrary local paths and can blur integrity verification with publication.

Implementation requires a separate human-approved task and tests-first PR.

## Inputs and ledger contract

Both paths are mandatory. The verifier must never search for a likely release,
fall back to the repository `runs/` directory or infer a ledger from filenames.

The first supported ledger version should retain the existing JSON concepts:

- `release`: non-empty release identifier;
- `ledger_version`: an explicit supported version;
- `boundary`: Git commit, tree, status and source verification;
- `runs`: exactly eight declared run entries for the approved four-area
  contract, each with AOI, scenario, run ID, file count and a map of relative
  file paths to SHA-256 and byte size;
- `pairs`: four dry/moderate declarations with explicit run IDs and report
  directory entries;
- `files`: any release-root files outside run/pair subtrees, including the
  archive note and saved audit reports;
- `excluded`: a closed list of operational scratch names that are forbidden
  from the canonical inventory, such as `.pair-report-*`, `.probe.txt`, lock
  files and temporary files.

Every path uses normalized POSIX-style relative syntax. Absolute paths,
drive-qualified paths, empty segments, `.`/`..`, alternate separators and NUL
characters are invalid. The schema must reject unknown top-level keys rather
than silently accepting a future meaning.

## Read-only verification sequence

The verifier performs these checks in order and reports all safe independent
findings in one pass:

1. Resolve the release root and ledger separately. Require both to exist, the
   root to be a directory and the ledger to be a regular UTF-8 JSON file.
2. Validate ledger schema, supported version, expected AOI/scenario matrix,
   unique run IDs, unique pair declarations and boundary field shapes.
3. Normalize every declared relative path. Reject exact duplicates,
   case-folded duplicates and file/directory prefix collisions.
4. Resolve each target and require its final real path to remain under the
   real release root. Reject symlink/junction escapes and non-regular files.
5. Stream every file once, comparing exact byte size and lowercase SHA-256.
   Use `pipeline.bkkflow.util.sha256_file`; never load large Parquet files into
   memory merely to hash them.
6. Enumerate regular files under the release root using the same containment
   rules. Fail on missing declarations, undeclared extras and any excluded
   scratch name. The ledger file itself is included only when the schema says
   it is part of the canonical package.
7. For each run, load `manifest.json`, call
   `pipeline.bkkflow.manifest.validate_manifest`, then
   `manifest.verify_output_integrity`. Require published run state, declared
   code/source identity and exact run-directory identity.
8. Call `pipeline.bkkflow.replay_audit.audit_saved_run` for all eight runs and
   require `PASS`. This independently reconstructs denominators, routing and
   saved outputs; a checksum match alone is insufficient.
9. For each pair, reuse `pipeline.report.load_checked_pair` and require the dry
   and moderate declarations to share the fixed cohort and common boundary.
   Verify the declared report files by size/hash; do not regenerate reports.
10. Emit a deterministic summary containing release identity, ledger hash,
    verified file/byte counts, eight run results, four pair results and ordered
    findings. Exit zero only when every required check passes.

The command must not write into the release root, update access-controlled
metadata, repair hashes, rename files, create reports or change run state.
When `--report` is omitted it writes JSON to standard output. When supplied,
the report path must resolve outside the release root and is installed
atomically only after verification finishes.

## Required failure cases

Tests must prove rejection of:

- malformed JSON, wrong ledger version, missing keys and unknown schema keys;
- absolute/traversal paths, symlink or junction escape, duplicate normalized or
  case-folded paths and file/directory prefix collision;
- missing file, non-regular file, byte-size mismatch and SHA-256 mismatch;
- undeclared extra file and any operational scratch file in the package;
- wrong run count, duplicate run ID, missing AOI/scenario and pair mismatch;
- invalid manifest schema, manifest-output mismatch, unpublished run state,
  source/code identity contradiction and failed replay audit;
- cohort or boundary mismatch in a dry/moderate pair;
- an output report path inside the release root.

Positive tests use a minimal temporary fixture plus a small published-run test
bundle. A separate integration test may verify the current external candidate
when it exists, but generated release data never enters Git.

## Acceptance boundary

The verifier can establish that a directory matches its ledger and that the
saved run/pair contracts replay. It cannot establish terrain accuracy,
behavioural calibration, refuge safety, causal validity, operational fitness,
independent preservation or a DOI. Passing verification must not change a
manifest's validation status or make the app expose the release automatically.

Before implementation, North must approve the ledger version, whether the
ledger is inside or beside the release root, the exact extra-file policy and
the location/format of the optional report. Until then this document remains a
proposal and no source module, app route or registry entry should be added.
