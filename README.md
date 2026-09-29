# BKK/FLOW

An open-data flood extent, building height, network disruption, and evacuation simulation concept for Bangkok.

The repository contains:

- `site/` — interactive React prototype
- `PROJECT_PLAN.md` — product, data, modelling, and delivery plan
- `docs/FULL_IMPLEMENTATION_PLAN.md` — complete population + PFLOW + flood-evacuation implementation plan
- `docs/PFLOW_BANGKOK_INTEGRATION.md` — PFLOW-to-Bangkok model contract
- `data/source-registry.json` — machine-readable, licence-aware source registry
- `schemas/pflow-bkk-run.schema.json` — reproducible simulation-run contract
- `config/population.example.json` — open-data weighted-population prototype configuration
- `site/src/data.ts` — source registry used by the prototype UI

## Run the prototype

```powershell
cd site
pnpm install
pnpm dev
```

Build the production site with:

```powershell
pnpm build
```

The current map and result values are illustrative. The UI labels them as modelled demonstration output; it is not an emergency warning service.

The implementation branch is `codex/bkk-pflow-open-data`. Downloaded and derived geospatial data are deliberately ignored by Git; every real input must be recoverable from a source URL, retrieval timestamp, request parameters and checksum.

## Product principles

1. A source must be publicly accessible **and** explicitly reusable.
2. Observations, predictions, and scenario assumptions remain visually distinct.
3. Every model run is reproducible from versioned inputs and code.
4. Building height is an exposure and vertical-refuge input—not proof that a building is a safe shelter.
5. Operational use requires local validation, agency review, and an incident-management owner.
6. Resident population, time-of-day PFLOW presence, exposed people, and the evacuation cohort are separate quantities.
