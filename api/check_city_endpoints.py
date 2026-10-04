"""Smoke-check the city-layer endpoints against the newest city run."""

from __future__ import annotations

import glob
import json
import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api.app import app  # noqa: E402


def newest_city_run() -> str:
    candidates = [
        path
        for path in glob.glob("runs/*/observed_water.json")
    ]
    if not candidates:
        raise SystemExit("no run with an observed hazard layer was found")
    return os.path.basename(os.path.dirname(max(candidates, key=os.path.getmtime)))


def main() -> int:
    run_id = newest_city_run()
    client = TestClient(app)
    print(f"city run: {run_id}\n")

    checks = [
        ("/population-grid", {}),
        ("/observed-water", {}),
        ("/observed-water/cells", {"year": 2012, "limit": 800}),
        ("/destinations", {"limit": 5}),
        ("/network", {"limit": 50}),
    ]
    failures = 0
    for path, params in checks:
        response = client.get(f"/v1/runs/{run_id}{path}", params=params)
        body = response.json()
        if response.status_code != 200:
            print(f"FAIL {path} -> HTTP {response.status_code}")
            failures += 1
            continue
        if "features" in body:
            summary = f"features={body.get('returned')} of {body.get('matched_rows')}"
            if "available_years" in body:
                summary += f" years={body.get('available_years')} year={body.get('year')}"
        elif "years" in body:
            summary = (
                f"years={[entry['year'] for entry in body.get('years', [])]} "
                f"observation={body.get('is_observation')}"
            )
        else:
            summary = f"matched={body.get('matched_rows')} returned={body.get('returned')}"
        print(f"ok   {path:32s} {summary}")

    # Honesty invariants the client depends on.
    observed = client.get(f"/v1/runs/{run_id}/observed-water").json()
    if observed.get("is_observation") is not True:
        print("FAIL observed layer is not flagged as an observation")
        failures += 1
    if "NOT depth" not in str(observed.get("measures", "")):
        print("FAIL observed layer does not state it is not depth")
        failures += 1

    destinations = client.get(f"/v1/runs/{run_id}/destinations", params={"limit": 1}).json()
    if destinations.get("verified_count") != 0:
        print("FAIL destinations report a non-zero verified count")
        failures += 1

    grid = client.get(f"/v1/runs/{run_id}/population-grid").json()
    if grid.get("quantity") != "resident_baseline":
        print("FAIL population grid is not labelled as a resident baseline")
        failures += 1

    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
