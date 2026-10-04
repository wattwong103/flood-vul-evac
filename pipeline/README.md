# Open-data staging

Downloaded and derived geospatial data are ignored by Git. A staged source must retain its catalogue URL, resource URL, licence, retrieval time, request parameters, byte count and SHA-256 hash.

## BMA flood-risk/watch records

The approved BMA CSV is a 49-row list of named roads and districts. The catalogue does not expose coordinates, so it is qualitative review evidence rather than a point layer.

Download and audit it when the BMA host is reachable:

```powershell
python pipeline/stage_bma_flood_risk.py --download
```

If the source host resets an automated connection, download the CSV in a browser and stage the local file:

```powershell
python pipeline/stage_bma_flood_risk.py --input "C:\path\to\downloaded.csv"
```

The script rejects archives, files larger than 5 MB, unexpected encodings, missing expected fields and embedded NUL bytes. It emits a redacted inventory and a local `manifest.json`; it never geocodes road descriptions.

## Spatial gates

Before processing an actual vector or raster layer:

1. confirm country, source, licence and stable feature key;
2. inventory geometry type, null/empty/invalid counts and source CRS;
3. approve the analysis CRS—never infer it from coordinate ranges;
4. state join predicate and expected cardinality;
5. write derived results to a new path and reopen them for validation;
6. aggregate or redact trajectories and exact person locations before publication.
