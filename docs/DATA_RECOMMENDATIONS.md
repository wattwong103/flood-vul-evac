# Data and model recommendations

**Decision date:** 30 September 2026  
**Scope:** open-data Bangkok population, flood exposure, building height and
PFLOW-style evacuation  
**Current release status:** `demonstration`

## Recommendation

Keep the city product as a population, assets and connectivity **screening**
tool until four independent evidence gates pass. Do not promote the pilot's
canal-distance surface to a Bangkok depth model.

| Priority | Gate | Current evidence | Next action | Pass condition |
|---|---|---|---|---|
| P0 | Terrain | SRTM-lineage surfaces fail local checks. Copernicus GLO-30 is a DSM whose published vertical accuracy is too coarse for the 0–2 m signal. | Obtain the RTARF-published index of RTSD Central Basin LiDAR surveys and determine whether referenced ground data cover Bangkok. | Exact tiles, explicit reuse terms, CRS and vertical datum recorded; ground-classified DTM passes held-out checkpoints. |
| P0 | Event forcing | No reusable rainfall and water-level series is in a run. | Clear a specific BMA/TMD rainfall resource and river/tide boundary series through the licence gate. | Timestamped, gap-audited forcing spans the chosen event and is archived with checksums. |
| P0 | Flood validation | JRC annual water is observed extent but cannot resolve a short event or depth. | Add time-specific GISTDA extent or independently classified Sentinel-1 acquisitions for held-out events. | Acquisition time and uncertainty recorded; extent metrics are reported on dates excluded from calibration. |
| P0 | Refuge safety | OSM supplies 1,400 candidates and zero verified refuges. | Build an operator-reviewed inventory with capacity, opening conditions, accessible entrance, usable floor and review date. | A record is routable as a refuge only after every required field is verified. |
| P1 | Population controls | WorldPop is ingested; DOPA/NSO controls and age/sex products are registered but not ingested. | Reconcile the resident surface to all 50 districts and then add age/sex margins. | Coverage, missingness and discrepancies are published by geography; registered residents remain distinct from people present. |
| P1 | Building height | OSM heights exist sparsely; Open Buildings 2.5D covers Thailand but its reported height error was not evaluated there. | Ingest 2023 height as an estimated exposure attribute and validate a Bangkok sample against trusted buildings. | Coverage and error by height band are published; height never implies refuge eligibility. |
| P1 | Mobility | PFLOW stages run, but Bangkok activity, destination and mode parameters remain scenario priors. | Seek an openly reusable household travel survey or publish structured sensitivity ensembles. | Held-out spatial/temporal volumes are compared at 1 km or coarser; otherwise status remains `demonstration`. |

## Build order

1. **Close the population evidence loop now.** Ingest the already approved
   DOPA/NSO controls, build an explicit geography crosswalk, and publish raw
   WorldPop totals, official registered totals and reconciled totals side by
   side. Never call any of these a daytime population.
2. **Resolve LiDAR access before writing a city depth solver.** The official
   RTARF-published catalogue describes 1 m RTSD Central Basin surveys with better than 15 cm
   vertical accuracy, but the public resource found here is a coverage index.
   Treat the underlying tiles as unavailable until download, licence and
   Bangkok coverage are proven.
3. **Choose one historical event with complete inputs.** Require rainfall,
   river/tide boundary conditions and time-specific observed extent. Split the
   observation into calibration and held-out validation dates or areas.
4. **Add a shallow-water or storage-cell flood engine only after steps 2–3.**
   Record grid, time step, roughness, infiltration, drainage and boundary
   assumptions. Mass conservation and sensitivity checks are release gates.
5. **Run PFLOW evacuation on flood-impeded walking links.** Keep weighted
   synthetic agents, people present, exposed people and the evacuation cohort
   as separate quantities. Report route failures and destination overflow.
6. **Promote nothing automatically.** Independent scientific, licensing and
   emergency-management review is required to move above `demonstration`.

## Data acceptance rules

- Citywide claims must be clipped to the full Bangkok Metropolitan
  Administration boundary (`bangkok-bma`, OSM relation R92277). A district
  pilot may be shown inside that frame, but its outputs must not be styled or
  described as citywide coverage.
- A catalogue page is not the data. Record the exact resource URL, retrieval
  time, request parameters and SHA-256 for every input file.
- Licence approval and fitness approval are separate. An openly licensed DSM
  can still be rejected for depth modelling.
- Missing values remain null. No unavailable age, capacity, depth or travel
  observation becomes zero or a default fact.
- Population reconciliation must publish the denominator and geography. Do
  not silently scale a raster to an administrative total.
- Flood outputs must name `observed`, `modelled` or `scenario`; an annual water
  classification must never be labelled as event depth.
- Public people-flow output starts at 1 km. Any finer release needs empirical
  validation and a disclosure review.

## Primary source record

- RTARF-published RTSD LiDAR coverage index: <https://data.go.th/en/dataset/lidar-1>
- Copernicus DEM specification and access: <https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM>
- DOPA/NSO district population controls: <https://data.go.th/en/dataset/0405_01_0005>
- Google Open Buildings 2.5D: <https://sites.research.google/gr/open-buildings/temporal/>
- Project source decisions: [`../data/source-registry.json`](../data/source-registry.json)

