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

from .clearance import weighted_clearance_minutes

# Terminal states. A person in the cohort must end in exactly one of these.
TERMINAL_STATES = (
    "arrived",
    "shelter_full",
    "stranded",
    "route_failed",
    "did_not_depart",
)

COHORT_RULE_VERSION = "fixed-order-area-v1"
COHORT_SEED = 29092026
COHORT_CAP = 1200
COHORT_IDENTITY_FIELDS = (
    "cohort_rule_version", "aoi_id", "seed", "max_agents", "order_radius_m",
    "scenario_time_s", "order_centre_lon", "order_centre_lat", "order_geometry_rule",
    "presence_rule", "sample_rule", "sample_digest", "sampling_probability", "cohort_digest",
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
    aoi_id: str = "unspecified",
    seed: int = COHORT_SEED,
    max_agents: int = COHORT_CAP,
    sample_persons: pd.DataFrame | None = None,
    sampling_probability: float = 1.0,
    expected_metadata: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Filter one deterministic upstream sample, then attach scenario exposure."""
    if max_agents <= 0:
        raise ValueError("fixed cohort max_agents must be positive")
    if not 0.0 <= sampling_probability <= 1.0:
        raise ValueError("fixed cohort sampling_probability must be between zero and one")
    sample_persons = persons if sample_persons is None else sample_persons
    if len(sample_persons) > max_agents:
        raise ValueError("fixed cohort input exceeds the declared upstream sample cap")
    if persons["person_id"].duplicated().any() or sample_persons["person_id"].duplicated().any():
        raise ValueError("fixed cohort person_id values must be unique")
    sample_rows = sample_persons.sort_values("person_id", kind="stable")
    sample_weights = sample_rows.set_index("person_id")["weight"]
    if not set(persons["person_id"]).issubset(sample_weights.index):
        raise ValueError("present rows must be a subset of the upstream sample")
    for row in persons.itertuples():
        if float(row.weight).hex() != float(sample_weights.loc[row.person_id]).hex():
            raise ValueError("present-row weights must match the upstream sample")
    persons = persons.copy()
    centre_x = float(persons["lon"].mean()) if len(persons) else None
    centre_y = float(persons["lat"].mean()) if len(persons) else None
    if len(persons):
        persons["distance_to_centre_m"] = np.hypot(
            persons["lon"] - centre_x, persons["lat"] - centre_y
        )
        persons["in_order_area"] = (
            persons["distance_to_centre_m"] <= (order_radius_m / 111_320.0)
        )
    else:
        persons["distance_to_centre_m"] = pd.Series(dtype=float)
        persons["in_order_area"] = pd.Series(dtype=bool)
    present_weight = float(persons["weight"].sum())
    eligible = persons.loc[persons["in_order_area"]].sort_values("person_id", kind="stable")
    cohort = eligible.copy()
    cohort["order_id"] = [
        "order_" + hashlib.sha256(f"{aoi_id}|{person_id}".encode()).hexdigest()[:20]
        for person_id in cohort["person_id"]
    ]
    cohort["sampling_probability"] = sampling_probability
    cohort["cohort_reason"] = "scenario_independent_fixed_order_area"

    geometry_rule = "WGS84 degree distance <= order_radius_m / 111320"
    presence_rule = (
        "if activities exist: sampled person IDs with start_time_s <= scenario_time_s < end_time_s; "
        "otherwise full sample; order area uses stored person/home lon-lat"
    )
    sample_rule = (
        "numpy.default_rng(seed).choice over full person row order without replacement; "
        "selected indices sorted; cap=min(full rows, max_agents)"
    )
    sample_digest = hashlib.sha256()
    for row in sample_rows.itertuples():
        sample_digest.update(f"{row.person_id}\0{float(row.weight).hex()}\n".encode())
    digest = hashlib.sha256(
        f"{COHORT_RULE_VERSION}|{aoi_id}|{seed}|{max_agents}|{centre_x}|{centre_y}|".encode()
    )
    for row in cohort.itertuples():
        digest.update(
            f"{row.order_id}\0{row.person_id}\0{float(row.weight).hex()}\n".encode()
        )
    cohort_digest = digest.hexdigest()
    identity = {
        "cohort_rule_version": COHORT_RULE_VERSION,
        "aoi_id": aoi_id,
        "seed": int(seed),
        "max_agents": int(max_agents),
        "order_radius_m": float(order_radius_m),
        "scenario_time_s": int(scenario_time_s),
        "order_centre_lon": centre_x,
        "order_centre_lat": centre_y,
        "order_geometry_rule": geometry_rule,
        "presence_rule": presence_rule,
        "sample_rule": sample_rule,
        "sample_digest": sample_digest.hexdigest(),
        "sampling_probability": float(sampling_probability),
        "cohort_digest": cohort_digest,
    }
    if expected_metadata is not None:
        mismatches = [key for key in COHORT_IDENTITY_FIELDS
                      if expected_metadata.get(key) != identity[key]]
        if mismatches:
            raise ValueError(f"fixed cohort mismatch: {', '.join(mismatches)}")

    if min_depth_m > 0:
        depths = np.array([
            surface_depth_at(lon, lat) for lon, lat in zip(persons["lon"], persons["lat"])
        ])
        persons["scenario_depth_m"] = np.round(depths, 4)
        persons["exposed"] = persons["scenario_depth_m"] >= min_depth_m
    else:
        persons["scenario_depth_m"] = 0.0
        persons["exposed"] = False
    cohort[["scenario_depth_m", "exposed"]] = persons.loc[
        cohort.index, ["scenario_depth_m", "exposed"]
    ]
    exposed_weight = float(persons.loc[persons["exposed"], "weight"].sum())

    reconciliation = {
        **identity,
        "present_weighted": round(present_weight, 2),
        "exposed_weighted": round(exposed_weight, 2),
        "cohort_weighted": round(float(cohort["weight"].sum()), 2),
        "eligible_rows": int(len(eligible)),
        "cohort_rows": int(len(cohort)),
        "min_depth_m": min_depth_m,
        "cohort_rule": "upstream fixed sample; then present AND within order radius; exposure is outcome only",
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
                    "event_time_s": float(arrival),
                    "weight": float(admitted),
                    "dest_id": str(destination["dest_id"]),
                    "clearance_s": float(arrival - scenario.warning_time_s),
                    "distance_m": round(distance_m, 1),
                }
            )
        else:
            records.append(
                {
                    "person_id": person.person_id,
                    "state": "arrived",
                    "reason": "admitted",
                    "event_time_s": float(arrival),
                    "weight": weight,
                    "dest_id": str(destination["dest_id"]),
                    "clearance_s": float(arrival - scenario.warning_time_s),
                    "distance_m": round(distance_m, 1),
                }
            )

        for edge_id in used_edges:
            bottleneck[edge_id] = bottleneck.get(edge_id, 0.0) + weight

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        return frame, _empty_outcome_summary()

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
        "clearance_time_minutes": weighted_clearance_minutes(
            frame, warning_time_s=scenario.warning_time_s
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
