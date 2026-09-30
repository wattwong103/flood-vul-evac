"""Build the Bangkok drainage-discharge screening index and record its provenance.

Runs ``bkkflow.drainage`` over the staged MitrEarth layers and the published
public 1 km grid, then writes the index table and a provenance record into a
run directory:

    runs/drainage-screening-v0.1-<date>/drainage_index.parquet
    runs/drainage-screening-v0.1-<date>/drainage_index.provenance.json

This is a standalone build on purpose. It does not touch the city pipeline,
because the city runner is owned elsewhere and the index is an independent
screening artefact: it reads the staged MitrEarth layers, it does not
regenerate them.

The output is a **relative screening index**, not a flood depth and not a
simulation. See ``bkkflow/drainage.py`` for what the index does and does not
claim; this script only reports the numbers it produced.

Usage::

    python pipeline/build_drainage_index.py
    python pipeline/build_drainage_index.py --grid runs/<id>/population_grid_1km.parquet
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import drainage as dr  # noqa: E402
from bkkflow.util import RUNS_DIR, ensure_dir, get_logger, sha256_file, utc_now_iso, write_json  # noqa: E402

LOGGER = get_logger("bkkflow.drainage")

TABLE_NAME = "drainage_index.parquet"
PROVENANCE_NAME = "drainage_index.provenance.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--grid", default=None,
        help="published population_grid_1km.parquet to take cell identity from; "
             "defaults to the most recent one in runs/",
    )
    parser.add_argument(
        "--curated-dir", default=str(dr.MITREARTH_DIR),
        help=f"staged MitrEarth layers (default: {dr.MITREARTH_DIR})",
    )
    parser.add_argument(
        "--aoi", default=None,
        help="AOI parquet used only when no published grid is available",
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="output directory (default: a dated run directory under runs/)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.time()

    result = dr.build_drainage_index(
        grid_path=args.grid,
        aoi_path=args.aoi,
        curated_dir=args.curated_dir,
    )

    stamp = utc_now_iso()[:10]
    out_dir = ensure_dir(
        Path(args.out_dir) if args.out_dir else RUNS_DIR / f"drainage-screening-{stamp}"
    )

    for warning in result.warnings:
        LOGGER.warning("%s", warning)

    if result.status != "ok":
        write_json(out_dir / PROVENANCE_NAME, result.as_dict())
        LOGGER.error(
            "drainage index UNAVAILABLE (%s); provenance written to %s",
            result.grid_source, out_dir / PROVENANCE_NAME,
        )
        return 1

    table_path = out_dir / TABLE_NAME
    result.frame.to_parquet(table_path, index=False)

    provenance = result.as_dict()
    provenance["outputs"] = {
        "table": table_path.name,
        "sha256": sha256_file(table_path),
        "provenance": PROVENANCE_NAME,
    }
    provenance["build_seconds"] = round(time.time() - started, 3)
    write_json(out_dir / PROVENANCE_NAME, provenance)

    frame = result.frame
    summary = result.summary
    LOGGER.info("drainage index built in %.1f s", time.time() - started)
    LOGGER.info("output: %s", table_path)
    LOGGER.info(
        "rows %d (scored %d), grid source %s",
        len(frame), summary["rows_scored"], result.grid_source,
    )
    LOGGER.info(
        "risk_index median %.3f, min %.3f, max %.3f",
        summary["risk_index"]["median"], summary["risk_index"]["min"],
        summary["risk_index"]["max"],
    )
    for label, count in summary["bands"].items():
        LOGGER.info("  band %-10s %5d  (%.1f%%)", label, count, 100.0 * count / max(len(frame), 1))
    LOGGER.info(
        "cells with null distance-to-drainage: %d (%.1f%%); null basin: %d; "
        "on overflow path: %d; with susceptible village: %d",
        summary["cells_without_drainage_within_cutoff"],
        100.0 * summary["cells_without_drainage_within_cutoff"] / max(len(frame), 1),
        summary["cells_with_null_basin"],
        summary["cells_in_overflow_path"],
        summary["cells_with_susceptible_village"],
    )
    LOGGER.info("SOURCING NOTE: this is a screening index, not a flood depth.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
