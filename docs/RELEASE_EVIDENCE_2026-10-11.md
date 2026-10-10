# Four-area replacement release evidence — 11 October 2026

This record admits the replacement four-area demonstration release produced
after PRs #73--#75 merged. It supersedes the 10 October set for current paper
and application use without modifying or deleting that older evidence.

The replacement contains four freshly staged named pilots and eight published
runs: one dry run and one fixed-cohort moderate run for Khlong San, Sai Mai,
Din Daeng and Min Buri. All runs remain demonstration evidence. They are not a
calibrated flood forecast, a validated evacuation model or an operational
planning product.

## Source and execution boundary

| Item | Identity |
|---|---|
| Git commit | `db0a96be7c61458f98fa8a7b53cae5fea711aec3` |
| Git tree | `d076c7a49a886bfd7a10b3e634c27ac7be57fdab` |
| Scoped source digest | `7428f5723a34213362347ef0a8022314fe5b15fe80cdab6c86a75f12f712a5bd` over 88 files |
| Source verification | clean and `matched_before_publication` |
| Runtime | Windows 10.0.26100; Python 3.11.9 |
| Geospatial stack | GeoPandas 1.1.3; PyArrow 24.0.0; PyProj 3.7.2; Rasterio 1.4.4; Shapely 2.0.2 |
| Numerical stack | NumPy 1.26.4; pandas 2.2.2; SciPy 1.13.0; NetworkX 3.6.1 |

No city-scale run was executed. The later documentation merge at `957f486`
does not reattribute these runs; the release code boundary remains `db0a96b`.

## Fresh staging evidence

All four stages reported `reused: false`, reopened successfully and matched all
36 declared output hashes.

| AOI | Population cells | Population version | Stage-manifest SHA-256 |
|---|---:|---|---|
| Khlong San | 678 | `bkk-pop-v0.3-khlong-san-district-2020-agesex` | `43ceac94265c1f89fe5be0472662eca99e93b87e857708bdd2d08ba89b4af6ac` |
| Sai Mai | 5,205 | `bkk-pop-v0.3-sai-mai-district-2020-agesex` | `2be79ec10de2441f4452e51660b34894bcd13db64f1d2a3ad45c65311a3c9a38` |
| Din Daeng | 1,019 | `bkk-pop-v0.3-din-daeng-district-2020-agesex` | `b22b9b52af78b9f6822732adeddc9504eab6a430a88c72f8f26840b10953a300` |
| Min Buri | 7,206 | `bkk-pop-v0.3-min-buri-district-2020-agesex` | `1e023fc2c2a15456e18ce024f5132e39d8374d0ade193713c5fdce1270d9c381` |

## Run and pair identities

Every run is published and its saved validation record passes 17 of 17 checks.
All eight stored replay reports pass and bind exactly 19 current hashes per
run. All four checked-pair publications pass and contain three figures plus one
denominator-explicit evidence note.

| AOI | Dry run | Moderate run referencing dry |
|---|---|---|
| Khlong San | `d1346d50-79c1-46e8-9720-8ae1f2cc7ead` | `3f8b7636-cfcc-4732-bc00-bae10aea59bd` |
| Sai Mai | `db06f4c2-c2a3-44fd-9f61-ba67bb4a0fb3` | `89058155-4df8-4496-ad10-06587b07cb7d` |
| Din Daeng | `a7a78901-0753-4fd2-8ea0-67d05ebf1732` | `b9b8c560-2f6e-4b77-88ef-b6bb0c3627ff` |
| Min Buri | `f0e9f7da-1ed5-453c-b0e8-78d5f68a0cfa` | `c45e3cbb-3686-4c69-ad9d-8e5b2b2c965a` |

The admitted one-decimal, sample-scoped values are:

| AOI | Moderate exposed / present | Arrived / cohort, dry | Arrived / cohort, moderate | Median clearance, dry | Median clearance, moderate |
|---|---:|---:|---:|---:|---:|
| Khlong San | 84.2% | 70.8% | 56.9% | 30.9 min | 106.4 min |
| Sai Mai | 41.6% | 72.0% | 34.1% | 63.4 min | 58.2 min |
| Din Daeng | 53.9% | 65.0% | 63.7% | 41.3 min | 86.5 min |
| Min Buri | 47.4% | 69.8% | 46.7% | 50.5 min | 111.7 min |

Dry exposure is zero by scenario definition. Across areas, dry arrived shares
range from 65.0% to 72.0%, moderate arrived shares from 34.1% to 63.7%, dry
medians from 30.9 to 63.4 minutes and moderate medians from 58.2 to 111.7
minutes. Sai Mai's lower moderate arrivals-only median accompanies a much lower
arrived share and a different arrival subset. It is not evidence of improved
evacuation or a causal benefit from flooding.

## Population and denominator boundary

| AOI | Weighted residents | Present weight | Fixed cohort weight | Age-covered population share | Unknown age weight |
|---|---:|---:|---:|---:|---:|
| Khlong San | 115,958.656 | 5,310.943 | 5,310.943 | 96.3342% | 4,250.836 |
| Sai Mai | 281,949.076 | 1,610.035 | 1,392.489 | 99.7167% | 798.865 |
| Din Daeng | 207,118.448 | 6,201.575 | 6,201.575 | 100.0000% | 0 |
| Min Buri | 273,891.448 | 1,198.589 | 809.951 | 98.2259% | 4,859.244 |

Age structure is a per-cell WorldPop 2026 model applied to the WorldPop 2020
resident baseline. Known-band shares are conditional on covered population.
No independent administrative control total was ingested. The capacity method
is `integerized`; evacuation destinations and capacities remain hypothetical
and unverified.

## External candidate and independent admission

The human-managed Dropbox archive folder contains the release root, its sibling
ledger and ZIP:

- root `bkkflow-four-area-2026-10-11`: 239 regular files and 215,769,231 bytes;
- ledger `bkkflow-four-area-2026-10-11.checksums.v1.json`, SHA-256
  `d1caea98cdf232c625502d8c53c1709558db66e33f6ce2677fbae1b85824e374`;
- ZIP `bkkflow-four-area-2026-10-11.zip`: 166,078,554 bytes, SHA-256
  `e93fe4cebc965a5bd706908d0504468d1c949149f897a77f9e368c2d6a87403f`.

The sibling ledger declares every regular file under the root. A separate
strict verifier found zero missing, extra, size, hash, duplicate, case-fold,
path-traversal, scratch or symlink/reparse mismatches. The ZIP has 240 members:
the exact 239 declared files plus the ledger. All 85 JSON files and the ledger
also parsed with duplicate-key rejection.

The independent admission review additionally checked all 36 stage hashes,
the eight manifest/output contracts, 152 saved-audit hash bindings, every
denominator and weighted clearance statistic, the four exact cohort row sets
and all 16 pair artifacts. It personally reran the full Khlong San dry and
moderate route/evacuation replay; it did not newly rerun all eight full route
replays. One reconstructed p95 differed from its saved value by
`2.56e-13` minutes, within the established `0.01` minute audit tolerance, so
route-replay floating-point values must not be described as bit-identical.

The older `bkkflow-four-area-2026-10-10.zip` remains unchanged at 163,343,745
bytes and SHA-256
`81236b5d0f483ab205ae66c153f57dcd111bee7b5ba7ac1c74a7d33725d3b05b`.

## Remaining concerns

- This is a local Dropbox candidate, not an independent durable deposit with a
  stable identifier or DOI.
- The flat version-1 checksum inventory is not the structured verifier schema
  proposed in PR #76; no repository verifier was implemented.
- The synthetic distance-to-water flood is not event-calibrated hydraulics.
- Mobility, warning, compliance, vehicle access and assistance fields remain
  uncalibrated scenario assumptions.
- No current city result, accepted citywide terrain/depth model or verified
  refuge-capacity inventory exists.
- The frozen Sai Mai comparison figure clips its long footer, prints excessive
  p95 precision and labels network edges as "ways". Its numbers remain valid,
  but the image is a review figure; source-label/layout cleanup is a future LOW
  follow-up and must not rewrite this release.

**DONE_WITH_CONCERNS**
