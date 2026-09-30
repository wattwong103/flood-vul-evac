"""Append the closure-sensitivity analysis to observed_evac.

The screening closes every way that touched water, because a yearly Landsat
classification carries no depth. That is an assumption. This function re-runs
each year closing only a share of those ways and reports whether the year
ranking survives, so the reader is not handed a single assumption-dependent
number as if it were a measurement.
"""

from pathlib import Path

ADDITION = '''

CLOSURE_FRACTIONS = (1.0, 0.5, 0.25)


def closure_sensitivity(years: tuple[int, ...] = (2010, 2012)) -> dict[str, Any]:
    """How much of the result is assumption rather than observation.

    "Any water closes the way" is a choice, not a measurement. This re-runs
    each year closing only a share of those ways, which is roughly what the
    answer would look like if shallow water stayed passable, and reports
    whether the year ranking survives every assumption.
    """
    rows: list[dict[str, Any]] = []
    for year in years:
        for fraction in CLOSURE_FRACTIONS:
            result = run_connectivity_screening(year=year, closure_fraction=fraction)
            rows.append(
                {
                    "year": year,
                    "closure_fraction": fraction,
                    "closed_edge_share": round(
                        result.closed_edges / max(result.total_edges, 1), 6
                    ),
                    "reachable_share_of_exposed": round(
                        result.reachable_population / max(result.exposed_population, 1e-9), 6
                    ),
                    "clearance_p50_minutes": result.clearance_minutes.get("p50"),
                }
            )

    spread: dict[str, Any] = {}
    for year in years:
        shares = [row["reachable_share_of_exposed"] for row in rows if row["year"] == year]
        spread[str(year)] = {
            "reachable_share_min": round(min(shares), 4),
            "reachable_share_max": round(max(shares), 4),
            "range_percentage_points": round((max(shares) - min(shares)) * 100, 2),
        }

    # A ranking is only worth reporting if it holds at every assumption level.
    worst_by_year: list[int] = []
    for fraction in CLOSURE_FRACTIONS:
        by_year = {
            row["year"]: row["reachable_share_of_exposed"]
            for row in rows
            if row["closure_fraction"] == fraction
        }
        worst_by_year.append(min(sorted(by_year), key=lambda year: by_year[year]))
    ranking_stable = len(set(worst_by_year)) == 1

    return {
        "measures": "sensitivity of connectivity screening to the water-impassable assumption",
        "is_evacuation_simulation": False,
        "note": (
            "A yearly water classification has no depth, so treating any water as closing "
            "the way is an assumption. The absolute reachable share depends heavily on it "
            "and must be read as assumption-driven, not as a measurement."
        ),
        "rows": rows,
        "spread_by_year": spread,
        "year_ranking_stable_across_assumptions": ranking_stable,
        "worst_year_by_assumption": worst_by_year,
        "written_at": utc_now_iso(),
    }
'''

P = Path("pipeline/bkkflow/observed_evac.py")
src = P.read_text(encoding="utf-8")
assert "def closure_sensitivity" not in src
P.write_text(src.rstrip() + "\n" + ADDITION, encoding="utf-8")
print("closure_sensitivity appended")
