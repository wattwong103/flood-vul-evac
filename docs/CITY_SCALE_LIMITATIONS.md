# City-scale limitations: why Bangkok flood depth is not derived in this build

**Date:** 30 September 2026
**Status:** a blocking technical finding, with the evidence that produced it
**Scope:** the expansion from the Khlong San pilot (5.96 km²) to the whole
Bangkok Metropolitan Administration (1,643.5 km²)

## Summary

The city baseline is real and complete: the network, the buildings and the
population are all available and were built. **Flood depth is not**, and this
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
| Copernicus DEM GLO-30 (AWS open bucket) | Host does not resolve from this environment |
| Copernicus DEM GLO-90 (AWS open bucket) | Host does not resolve from this environment |
| GISTDA open data | Host does not resolve from this environment |
| BMA open data (`data.bangkok.go.th`) | TLS connection closed |
| `data.go.th` national portal | HTTP 403 |
| Open Buildings 2.5D height | Requires an authenticated bucket; height is not elevation in any case |

A smoothing pass was considered and rejected: smoothing reduces visual noise
but cannot remove a systematic bias of the same magnitude as the signal.

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

1. **Obtain a vertical-accurate DEM.** Copernicus DEM GLO-30 or TanDEM-X,
   through a route this environment can reach. Then the approved
   water-surface screening approach becomes viable as designed. This is the
   only option that produces real depth.
2. **Restrict flood and evacuation to declared sub-areas** and keep the city
   layer as baseline only. Matches the plan's own phasing, and avoids any
   city-wide hazard claim.
3. **Publish a relative canal-exposure index city-wide**, explicitly not depth,
   with no metres anywhere. Defensible as a screening indicator, but it is
   still a proximity measure and cannot answer "how deep" or "how long".

The Khlong San pilot retains flood depth and evacuation. City and pilot results
are separate runs, and a city run never silently substitutes for a pilot
result.

## What this costs the project

Nothing that was already delivered, and one thing that was never delivered:
city-scale flood depth. The plan's Phase 1 exit criterion — "reproducible city
baseline, map tiles, source attribution, and a coverage dashboard" — is met.
The plan's Phase 2 exit criterion, which requires flood runs reproducing known
extents, is not met at city scale and is not met beyond the pilot.
