# City-scale limitations: why Bangkok flood depth is not derived in this build

**Date:** 30 September 2026
**Status:** a blocking technical finding, with the evidence that produced it
**Scope:** the expansion from the Khlong San pilot (5.96 km²) to the whole
Bangkok Metropolitan Administration (1,643.5 km²)

## Summary

The city baseline contains mapped network, buildings and modelled population.
The former BBBike extract did not cover the full BMA. New runs require a
Geofabrik Thailand source polygon that covers the AOI; this verifies source
coverage, not completeness of OSM mapping. **Flood depth is not**, and this
document records why, so that the absence is a decision on the record rather
than a gap nobody noticed.

The plan approved a DEM-based water-surface screening approach. That approach
was attempted and then abandoned on evidence: the only terrain source reachable
from this environment has a vertical error several times larger than the
entire elevation range that matters for flooding in Bangkok.

## The measurement

A terrain surface was acquired from the AWS Open Data terrarium tile service
(SRTM and upstream compilation, zoom 13, about 19 m per pixel) and decoded.

**Central Bangkok, tile covering roughly 100.49–100.53°E, 13.71–13.76°N
(which includes the whole of Khlong San):**

- Minimum −5.0 m, maximum 41.0 m, **mean 7.76 m**
- Centre of the tile: **+5.0 m**

Ground truth for that location is 1–2 m above mean sea level. The Chao Phraya
there is at roughly 0–1 m.

**Transect west to east across the river at Khlong San, sampled every ~150 m:**

```
9  8  9  4  4  10  7  9  9  7  5  5  10  9  7  10  9  3  10  11  10  8  13  15  9  12  7  10  3  10  4  7
```

There is no river channel in the data. The lowest reading on the transect is
about 3 m, where the river bed should be below sea level. SRTM-family
elevation has known vertical noise and bias of this magnitude in flat delta
cities, and the river is a wide, smooth, low-relief feature that such data
resolves badly.

## Why this is fatal rather than inconvenient

Bangkok's flood-relevant topography is the range **0–2 m**. The available DEM
carries **±5–10 m** of error across that same range.

A stage-based screening model computes depth as `water_surface − terrain`. If
the terrain input is wrong by more than the full range of depths being
reported, then:

- every reported depth is dominated by DEM noise rather than by flooding;
- the mapped flooded area becomes a function of the DEM's error pattern, not
  of hydrology;
- small changes in the assumed stage would appear to produce plausible but
  entirely spurious changes in extent.

A map that looks like a flood map and is actually a noise field is worse than
no map, because it will be read as one. This is precisely the failure the
project's own design rules exist to prevent, and the plan's §9 "risks to manage
early" item on drainage blindness becomes, at city scale, an inability to say
anything quantitative at all.

## Why the canal-proximity model is also not acceptable at city scale

The pilot's flood surface was a distance-to-water decay. That was defensible
for one 5.96 km² district, where "near the canal" and "flooded" are roughly the
same statement.

It is not defensible across Bangkok, which has **6,373 mapped waterways**. A
150 m decay from that network covers essentially the entire metropolitan area,
so the model would report near-total exposure and answer no question. Shipping
it as a city flood map would convert a limitation into a false headline.

## What was checked, and ruled out

| Candidate | Result |
|---|---|
| AWS terrarium tiles (SRTM/NED/ETOPO compilation) | Reachable, decoded, **insufficient vertical accuracy** |
| Copernicus DEM GLO-30 | Official access route now documented, but it is a DSM with <4 m absolute vertical accuracy at 90%; insufficient for Bangkok depth |
| Copernicus DEM GLO-90 | Coarser than GLO-30 and therefore not a depth solution |
| RTARF-published index of RTSD Central Basin LiDAR surveys | Official open index claims 1 m surveys and <15 cm vertical accuracy; the index is not the underlying elevation tiles |
| GISTDA open data | Host does not resolve from this environment |
| BMA open data (`data.bangkok.go.th`) | TLS connection closed |
| `data.go.th` national portal | HTTP 403 |
| Open Buildings 2.5D height | Requires an authenticated bucket; height is not elevation in any case |

A smoothing pass was considered and rejected: smoothing reduces visual noise
but cannot remove a systematic bias of the same magnitude as the signal.

## What changed after this finding: observed extent is now available

The search for a better elevation source turned up something more useful than a
DEM. **JRC Global Surface Water v1.4** (European Commission Joint Research
Centre, CC BY 4.0) is reachable on the public JEODPP mirror and provides a
Landsat-derived yearly water classification for 1984-2021 at about 30 m.

It is now ingested for 2010, 2011, 2012 and 2020, and it changes the
project's evidentiary position: for the first time there is a hazard layer in
this project that is **observed rather than asserted**.

| year | observed water | share of classified area | excess vs 2010 |
|---|---:|---:|---:|
| 2010 | 114.2 km² | 7.63% | baseline |
| 2011 | 114.0 km² | 7.68% | −0.15 km² |
| 2012 | 137.8 km² | 9.12% | +23.7 km² |
| 2020 | 114.3 km² | 7.72% | +0.12 km² |

What it does and does not fix:

- It **validates spatial extent**. A modelled or scenario surface can now be
  scored against a real observed layer, which is what the plan's Phase 2 exit
  criterion asks for.
- It does **not** provide depth. The depth blocker above is unchanged.
- It does **not** provide timing. A yearly classification cannot validate a
  four-hour evacuation scenario, and 2011's absence from the record is direct
  evidence of that limit rather than a data gap.
- Every year is a **lower bound**: annual composites under-detect short-lived
  inundation.

Elevation remains unavailable. Open-Meteo's elevation API was tested as an
alternative and is *worse* (8 m at Khlong San, against terrarium's 5 m), because
it derives from the same SRTM source.

## What the city build does deliver

Everything that does not depend on a defensible depth surface:

- **Area of interest:** Bangkok, admin level 4, OSM relation `R92277`,
  1,643.5 km²
- **Network:** 395,502 OSM highway ways, noded into a routable city graph
- **Buildings:** 424,420 OSM footprints with recoverable height and address tags
- **Population:** WorldPop 2020, 100 m, clipped to the BMA
- **Routing:** a compressed routing index with destination-centric Dijkstra,
  which is the only tractable approach at this scale and also the correct one
  for evacuation

## Options for a city hazard layer

1. **Resolve the RTARF-published RTSD LiDAR data path.** Prove Bangkok coverage from the open
   survey index, obtain the underlying ground-classified elevation tiles with
   explicit reuse permission, identify the vertical datum and validate local
   checkpoints. Copernicus GLO-30 and uncorrected TanDEM-X are surface models,
   not substitutes for this evidence.
2. **Restrict flood and evacuation to declared sub-areas** and keep the city
   layer as baseline only. Matches the plan's own phasing, and avoids any
   city-wide hazard claim.
3. **Publish a relative canal-exposure index city-wide**, explicitly not depth,
   with no metres anywhere. Defensible as a screening indicator, but it is
   still a proximity measure and cannot answer "how deep" or "how long".

Even an accepted DTM is only the first gate. A depth simulation also needs
event rainfall, river/tide boundary conditions, drainage assumptions and
held-out extent/depth observations for calibration and validation.

The Khlong San pilot retains flood depth and evacuation. City and pilot results
are separate runs, and a city run never silently substitutes for a pilot
result.

## What this costs the project

Nothing that was already delivered, and one thing that was never delivered:
city-scale flood depth. The plan's Phase 1 exit criterion — "reproducible city
baseline, map tiles, source attribution, and a coverage dashboard" — is met.
The plan's Phase 2 exit criterion, which requires flood runs reproducing known
extents, is not met at city scale and is not met beyond the pilot.
