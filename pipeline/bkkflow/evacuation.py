"""E1/E2 — evacuation cohort selection and outcome simulation.

The cohort is *selected*, not assumed: a person is in the cohort when the
scenario says they are present, in the affected area, and inside the order
rule. "Exposed" and "able or instructed to evacuate" are different facts and
the tables keep them apart.

Destinations in this build are **hypothetical**. The plan requires a verified
refuge inventory before any refuge claim, and no such inventory exists here, so
every destination carries ``verified=False`` and a visible hypothetical label.
Nothing here supports a statement about real shelter availability.

The terminal-state check is strict: every cohort member must land in exactly
one terminal state, and the weighted totals must reconcile.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

# Terminal states. A person in the cohort must end in exactly one of these.
TERMINAL_STATES = (
    "arrived",
    "shelter_full",
    "stranded",
    "route_failed",
    "did_not_depart",
)


@dataclass
class EvacuationScenario:
    """Declared behavioural and destination assumptions for one run."""

    scenario_id: str
    warning_time_s: int
    warning_reach: float = 0.92
    compliance: float = 0.78
    preparation_delay_mean_s: float = 900.0
    preparation_delay_sd_s: float = 600.0
    walk_speed_multiplier: float = 1.0
    reduced_mobility_share: float = 0.09
    refuge_capacity: int = 2000
    destinations: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_manifest_entry(self, seed: int) -> dict[str, Any]:
        return {
            "seed": seed,
            "departure_model": {
                "warning_time_s": self.warning_time_s,
                "warning_reach": self.warning_reach,
                "compliance": self.compliance,
                "preparation_delay_mean_s": self.preparation_delay_mean_s,
                "preparation_delay_sd_s": self.preparation_delay_sd_s,
                "status": "scenario_prior_uncalibrated",
            },
            "route_choice": {
                "algorithm": "astar_static_under_scenario_closure",
                "cost": "length / (dry_speed * depth_speed_multiplier)",
                "replanning": "none_single_pass",
                "status": "scenario_prior_uncalibrated",
            },
            "destinations": self.destinations,
            "mode_thresholds": {
                "version": "bkk-demo-thresholds-v0.1",
                "status": "engineering_prior_requires_validation",
            },
        }


def build_hypothetical_destinations(
    candidates: gpd.GeoDataFrame,
    *,
    analysis_crs: str,
    count: int = 3,
    capacity: int = 2000,
) -> gpd.GeoDataFrame:
    """Create explicitly hypothetical destination records.

    Chosen as the highest-footprint tagged candidates that are plausibly
    reachable and not in the deepest scenario water. Every record is marked
    unverified: this is a destination *for the model to aim at*, not a shelter
    anyone should be directed to.
    """
    pool = candidates.copy()
    if pool.empty:
        return pool
    pool = pool.sort_values("footprint_m2", ascending=False).head(count * 6)
    pool = pool.head(count)
    records = []
    for index, building in enumerate(pool.itertuples()):
        digest = hashlib.sha256(f"{building.building_id}".encode("utf-8")).hexdigest()[:12]
        records.append(
            {
                "dest_id": f"hyp_{digest}",
                "x": float(building.centre_x),
                "y": float(building.centre_y),
                "capacity": int(capacity),
                "verified": False,
                "status": "hypothetical_unverified",
                "operator": None,
                "accessible": False,
                "source_building_id": building.building_id,
            }
        )
    return gpd.GeoDataFrame(records, geometry=gpd.points_from_xy(
        [record["x"] for record in records], [record["y"] for record in records]
    ), crs=analysis_crs)


def select_cohort(
    persons: pd.DataFrame,
    *,
    surface_depth_at: Any,
    scenario_time_s: int,
    min_depth_m: float = 0.15,
    order_radius_m: float = 4000.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Select the evacuation cohort: present, in the affected area, ordered.

    The exposure threshold is the same 0.15 m used for flooded buildings and
    flooded area, so "exposed people", "flooded buildings" and "flooded area"
    all refer to the same water level. A lower threshold would mark nearly
    everyone as exposed, which makes the distinction from "present" vacuous.

    Returns the cohort and an explicit reconciliation so the website can show
    how many people were present, how many were exposed, and how many entered
    the cohort, without conflating them.
    """
    if persons.empty:
        return persons.copy(), {"present": 0.0, "exposed": 0.0, "cohort": 0.0}

    depths = np.array([surface_depth_at(lon, lat) for lon, lat in zip(persons["lon"], persons["lat"])])
    persons = persons.copy()
    persons["scenario_depth_m"] = np.round(depths, 4)
    if min_depth_m > 0:
        persons["exposed"] = persons["scenario_depth_m"] >= min_depth_m
    else:
        # Dry baseline: nobody is exposed to flood water. The cohort still
        # exists, because it is defined by the evacuation order, not by
        # exposure. Reporting everyone as "exposed" to a flood that does not
        # exist would be a false statement.
        persons["exposed"] = False

    centre_x = float(persons["lon"].mean())
    centre_y = float(persons["lat"].mean())
    persons["distance_to_centre_m"] = np.hypot(
        persons["lon"] - centre_x, persons["lat"] - centre_y
    )
    persons["in_order_area"] = persons["distance_to_centre_m"] <= (order_radius_m / 111_320.0)

    present_weight = float(persons["weight"].sum())
    exposed_weight = float(persons.loc[persons["exposed"], "weight"].sum())
    if min_depth_m > 0:
        cohort = persons[persons["exposed"] & persons["in_order_area"]].copy()
        cohort["cohort_reason"] = "in_order_area_and_flooded"
    else:
        cohort = persons[persons["in_order_area"]].copy()
        cohort["cohort_reason"] = "in_order_area_dry_baseline"

    reconciliation = {
        "present_weighted": round(present_weight, 2),
        "exposed_weighted": round(exposed_weight, 2),
        "cohort_weighted": round(float(cohort["weight"].sum()), 2),
        "min_depth_m": min_depth_m,
        "order_radius_m": order_radius_m,
        "scenario_time_s": scenario_time_s,
        "cohort_rule": (
            "present AND depth >= min_depth_m AND within order radius"
            if min_depth_m > 0
            else "present AND within order radius (dry baseline: no water condition)"
        ),
        "note": "present, exposed and cohort are distinct quantities and are reported separately; "
                "exposure uses the 0.15 m depth threshold shared with flooded buildings and area",
    }
    return cohort, reconciliation


def simulate_evacuation(
    cohort: pd.DataFrame,
    *,
    destinations: gpd.GeoDataFrame,
    route_lookup: Any,
    scenario: EvacuationScenario,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run the auditable state machine and return per-agent outcomes."""
    rng = np.random.default_rng(seed)
    records: list[dict[str, Any]] = []
    clearance: list[float] = []
    bottleneck: dict[str, float] = {}
    capacity_remaining = {dest.dest_id: int(dest.capacity) for dest in destinations.itertuples()}

    if cohort.empty:
        return pd.DataFrame(
            columns=[
                "person_id",
                "state",
                "reason",
                "event_time_s",
                "weight",
                "dest_id",
                "clearance_s",
                "distance_m",
            ]
        ), _empty_outcome_summary()

    for person in cohort.itertuples():
        weight = float(person.weight)
        stage = "exposed"

        # Warning reach.
        if rng.random() > scenario.warning_reach:
            records.append(
                {
                    "person_id": person.person_id,
                    "state": "did_not_depart",
                    "reason": "not_warned",
                    "event_time_s": scenario.warning_time_s,
                    "weight": weight,
                    "dest_id": None,
                    "clearance_s": None,
                    "distance_m": None,
                }
            )
            continue
        stage = "warned"

        # Compliance decision.
        if rng.random() > scenario.compliance:
            records.append(
                {
                    "person_id": person.person_id,
                    "state": "did_not_depart",
                    "reason": "not_compliant",
                    "event_time_s": scenario.warning_time_s,
                    "weight": weight,
                    "dest_id": None,
                    "clearance_s": None,
                    "distance_m": None,
                }
            )
            continue
        stage = "deciding"

        delay = float(
            np.clip(rng.normal(scenario.preparation_delay_mean_s, scenario.preparation_delay_sd_s), 0, 4 * 3600)
        )
        depart_time = scenario.warning_time_s + delay
        stage = "departed"

        destination = None
        if not destinations.empty:
            # Both the person and the destinations are in the analysis CRS here;
            # the WGS84 columns are only for publication.
            person_x = getattr(person, "x", None)
            person_y = getattr(person, "y", None)
            if person_x is None or (isinstance(person_x, float) and np.isnan(person_x)):
                person_x, person_y = float(person.lon), float(person.lat)
            candidates = destinations.copy()
            candidates["distance_m"] = [
                float(np.hypot(float(record["x"]) - float(person_x),
                               float(record["y"]) - float(person_y)))
                for _, record in candidates.iterrows()
            ]
            candidates = candidates.sort_values("distance_m")
            destination = candidates.iloc[0] if len(candidates) else None

        if destination is None:
            records.append(
                {
                    "person_id": person.person_id,
                    "state": "route_failed",
                    "reason": "no_destination",
                    "event_time_s": int(depart_time),
                    "weight": weight,
                    "dest_id": None,
                    "clearance_s": None,
                    "distance_m": None,
                }
            )
            continue

        stage = "en_route"
        person_lon = float(getattr(person, "lon", 0.0))
        person_lat = float(getattr(person, "lat", 0.0))
        route = route_lookup(person_lon, person_lat, float(destination["x"]), float(destination["y"]))

        if route is None:
            records.append(
                {
                    "person_id": person.person_id,
                    "state": "route_failed",
                    "reason": "no_path_under_closure",
                    "event_time_s": int(depart_time),
                    "weight": weight,
                    "dest_id": str(destination["dest_id"]),
                    "clearance_s": None,
                    "distance_m": None,
                }
            )
            continue

        travel_s, distance_m, used_edges = route
        arrival = depart_time + travel_s

        # Capacity is enforced on integerised people, not on weighted rows.
        people_represented = max(int(round(weight)), 1)
        remaining = capacity_remaining.get(str(destination["dest_id"]), 0)
        admitted = min(people_represented, max(remaining, 0))
        capacity_remaining[str(destination["dest_id"])] = remaining - admitted

        if admitted <= 0:
            records.append(
                {
                    "person_id": person.person_id,
                    "state": "shelter_full",
                    "reason": "destination_capacity_exhausted",
                    "event_time_s": int(arrival),
                    "weight": weight,
                    "dest_id": str(destination["dest_id"]),
                    "clearance_s": None,
                    "distance_m": round(distance_m, 1),
                }
            )
            continue

        if admitted < people_represented:
            overflow = people_represented - admitted
            records.append(
                {
                    "person_id": person.person_id,
                    "state": "shelter_full",
                    "reason": "partial_admission_capacity",
                    "event_time_s": int(arrival),
                    "weight": float(overflow),
                    "dest_id": str(destination["dest_id"]),
                    "clearance_s": None,
                    "distance_m": round(distance_m, 1),
                }
            )
            records.append(
                {
                    "person_id": person.person_id,
                    "state": "arrived",
                    "reason": "admitted",
                    "event_time_s": int(arrival),
                    "weight": float(admitted),
                    "dest_id": str(destination["dest_id"]),
                    "clearance_s": round(arrival - scenario.warning_time_s, 1),
                    "distance_m": round(distance_m, 1),
                }
            )
        else:
            records.append(
                {
                    "person_id": person.person_id,
                    "state": "arrived",
                    "reason": "admitted",
                    "event_time_s": int(arrival),
                    "weight": weight,
                    "dest_id": str(destination["dest_id"]),
                    "clearance_s": round(arrival - scenario.warning_time_s, 1),
                    "distance_m": round(distance_m, 1),
                }
            )

        for edge_id in used_edges:
            bottleneck[edge_id] = bottleneck.get(edge_id, 0.0) + weight

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        return frame, _empty_outcome_summary()

    arrived = frame[frame["state"] == "arrived"]
    weighted_clearance = []
    for row in arrived.itertuples():
        repetitions = max(int(round(float(row.weight))), 1)
        weighted_clearance.extend([float(row.clearance_s)] * min(repetitions, 50))

    summary = {
        "cohort_weighted": round(float(frame["weight"].sum()), 2),
        "state_distribution": {
            str(state): round(float(group["weight"].sum()), 2)
            for state, group in frame.groupby("state")
        },
        "arrived_weighted": round(
            float(frame.loc[frame["state"] == "arrived", "weight"].sum()), 2
        ),
        "unserved_weighted": round(
            float(frame.loc[frame["state"] != "arrived", "weight"].sum()), 2
        ),
        "clearance_time_minutes": _percentiles(
            [value / 60.0 for value in weighted_clearance]
        ),
        "top_bottleneck_edges": [
            {"edge_id": edge_id, "traversal_weight": round(weight, 1)}
            for edge_id, weight in sorted(bottleneck.items(), key=lambda item: -item[1])[:10]
        ],
        "destinations": [
            {
                "dest_id": dest_id,
                "capacity": int(capacity),
                "remaining": int(capacity_remaining.get(dest_id, 0)),
                "verified": False,
                "status": "hypothetical_unverified",
            }
            for dest_id, capacity in {
                dest.dest_id: int(dest.capacity) for dest in destinations.itertuples()
            }.items()
        ],
    }
    return frame, summary


def _percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p5": None, "median": None, "p95": None}
    array = np.asarray(values, dtype="float64")
    return {
        "p5": round(float(np.percentile(array, 5)), 2),
        "median": round(float(np.percentile(array, 50)), 2),
        "p95": round(float(np.percentile(array, 95)), 2),
    }


def _empty_outcome_summary() -> dict[str, Any]:
    return {
        "cohort_weighted": 0.0,
        "state_distribution": {},
        "arrived_weighted": 0.0,
        "unserved_weighted": 0.0,
        "clearance_time_minutes": {"p5": None, "median": None, "p95": None},
        "top_bottleneck_edges": [],
        "destinations": [],
    }


def check_conservation(states: pd.DataFrame, cohort_weight: float) -> dict[str, Any]:
    """Every cohort member must land in exactly one terminal state."""
    if states.empty:
        return {
            "passed": True,
            "cohort_weight": cohort_weight,
            "terminal_weight": 0.0,
            "residual": 0.0,
            "note": "empty cohort",
        }
    terminal_weight = float(states["weight"].sum())
    residual = abs(cohort_weight - terminal_weight)
    unknown = set(states["state"]) - set(TERMINAL_STATES)
    return {
        "passed": residual <= max(1.0, cohort_weight * 0.001) and not unknown,
        "cohort_weight": round(cohort_weight, 3),
        "terminal_weight": round(terminal_weight, 3),
        "residual": round(residual, 6),
        "unexpected_states": sorted(unknown),
        "tolerance": "max(1.0, 0.1% of cohort)",
    }
