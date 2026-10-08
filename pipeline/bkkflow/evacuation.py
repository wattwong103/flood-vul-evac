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
import math
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
DENOMINATOR_CONTRACT_VERSION = "sample-denominators-v1"
COHORT_SEED = 29092026
COHORT_CAP = 1200
COHORT_IDENTITY_FIELDS = (
    "cohort_rule_version", "aoi_id", "seed", "max_agents", "order_radius_m",
    "scenario_time_s", "order_centre_lon", "order_centre_lat", "order_geometry_rule",
    "presence_rule", "sample_rule", "sample_digest", "sampling_probability", "cohort_digest",
)
DENOMINATOR_SCOPE = {
    "population_basis": "deterministic_sample_only",
    "representative_of_full_district_or_bangkok": False,
    "reweighting_to_full_population": False,
}
CAPACITY_METHOD = {
    "method": "integerized",
    "integerization_rule": "max(round(source_weight), 1)",
    "fractional_weight_partition": "proportional_to_admitted_integer_units",
}
DENOMINATOR_ASSIGNMENT = {
    "exposure": "exposed present / present",
    "terminal_states": "terminal state weight / fixed cohort",
    "clearance": "arrived records only",
}
SANCTIONED_NUMERIC_VARIATION = (
    "exposed_present", "terminal_states", "clearance_denominator",
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
                "outcome_id",
                "source_person_id",
                "source_weight",
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
        delay = float(
            np.clip(rng.normal(scenario.preparation_delay_mean_s, scenario.preparation_delay_sd_s), 0, 4 * 3600)
        )
        depart_time = scenario.warning_time_s + delay
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
            admitted_weight = weight * admitted / people_represented
            overflow_weight = weight - admitted_weight
            records.append(
                {
                    "person_id": person.person_id,
                    "state": "shelter_full",
                    "reason": "partial_admission_capacity",
                    "event_time_s": int(arrival),
                    "weight": overflow_weight,
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
                    "weight": admitted_weight,
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
    source_weights = cohort.set_index("person_id")["weight"]
    frame["source_person_id"] = frame["person_id"]
    frame["source_weight"] = frame["source_person_id"].map(source_weights).astype(float)
    fragment = frame.groupby("source_person_id", sort=False).cumcount().astype(str)
    frame["outcome_id"] = (
        frame["source_person_id"].astype(str) + ":" + frame["state"].astype(str) + ":" + fragment
    )

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


def build_denominator_contract(
    full_population: pd.DataFrame,
    sample: pd.DataFrame,
    present: pd.DataFrame,
    cohort: pd.DataFrame,
    states: pd.DataFrame,
    *,
    cohort_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and describe every population denominator used by a run."""

    def population_weights(frame: pd.DataFrame, name: str) -> pd.Series:
        required = {"person_id", "weight"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{name} is missing columns: {', '.join(sorted(missing))}")
        if frame["person_id"].isna().any() or frame["person_id"].duplicated().any():
            raise ValueError(f"{name} person_id values must be non-null and unique")
        weights = pd.to_numeric(frame["weight"], errors="coerce")
        if not np.isfinite(weights).all() or (weights <= 0).any():
            raise ValueError(f"{name} weights must be finite and positive")
        return pd.Series(weights.to_numpy(dtype=float), index=frame["person_id"])

    def require_subset(
        child_weights: pd.Series, parent_weights: pd.Series, child: str, parent: str
    ) -> None:
        if not set(child_weights.index).issubset(parent_weights.index):
            raise ValueError(f"{child} person IDs must be a subset of {parent}")
        for person_id, weight in child_weights.items():
            if float(weight).hex() != float(parent_weights.loc[person_id]).hex():
                raise ValueError(f"{child} weights must exactly match {parent}")

    full_weights = population_weights(full_population, "full_population")
    sample_weights = population_weights(sample, "sample")
    present_weights = population_weights(present, "present")
    cohort_weights = population_weights(cohort, "cohort")
    require_subset(sample_weights, full_weights, "sample", "full_population")
    require_subset(present_weights, sample_weights, "present", "sample")
    require_subset(cohort_weights, present_weights, "cohort", "present")

    if "exposed" not in present.columns or present["exposed"].isna().any():
        raise ValueError("present must contain non-null exposed flags")
    if not present["exposed"].isin([True, False]).all():
        raise ValueError("present exposed flags must be boolean")

    required_states = {
        "outcome_id", "source_person_id", "source_weight", "state", "weight",
    }
    missing_states = required_states - set(states.columns)
    if missing_states:
        raise ValueError(
            "terminal states are missing columns: " + ", ".join(sorted(missing_states))
        )
    if states["outcome_id"].isna().any() or states["outcome_id"].duplicated().any():
        raise ValueError("terminal outcome_id values must be non-null and unique")
    unknown = set(states["state"].dropna()) - set(TERMINAL_STATES)
    if states["state"].isna().any() or unknown:
        raise ValueError(f"terminal states contain unexpected values: {sorted(unknown)}")
    terminal_weights = pd.to_numeric(states["weight"], errors="coerce")
    source_weights = pd.to_numeric(states["source_weight"], errors="coerce")
    if (
        not np.isfinite(terminal_weights).all()
        or not np.isfinite(source_weights).all()
        or (terminal_weights <= 0).any()
        or (source_weights <= 0).any()
    ):
        raise ValueError("terminal and source weights must be finite and positive")
    source_ids = set(states["source_person_id"])
    if source_ids != set(cohort_weights.index):
        raise ValueError("terminal source rows must cover the cohort exactly")

    checked_states = states.copy()
    checked_states["weight"] = terminal_weights.to_numpy(dtype=float)
    checked_states["source_weight"] = source_weights.to_numpy(dtype=float)
    for source_id, group in checked_states.groupby("source_person_id", sort=False):
        expected = float(cohort_weights.loc[source_id])
        if any(float(value).hex() != expected.hex() for value in group["source_weight"]):
            raise ValueError("terminal source_weight must exactly match the cohort")
        if abs(math.fsum(float(value) for value in group["weight"]) - expected) > 1e-6:
            raise ValueError("terminal fragments must conserve each cohort source weight")
        if len(group) > 1 and (
            len(group) != 2 or set(group["state"]) != {"arrived", "shelter_full"}
        ):
            raise ValueError("only arrived/shelter_full capacity partitions may split a source row")

    cohort_weight = math.fsum(float(value) for value in cohort_weights)
    terminal_weight = math.fsum(float(value) for value in checked_states["weight"])
    residual = abs(cohort_weight - terminal_weight)
    if residual > 1e-6:
        raise ValueError("terminal-state weights do not conserve the cohort")

    def quantity(frame: pd.DataFrame, weights: pd.Series) -> dict[str, int | float]:
        return {"rows": int(len(frame)), "weight": math.fsum(float(value) for value in weights)}

    exposed = present["exposed"].astype(bool).to_numpy()
    exposed_weight = math.fsum(float(value) for value in present_weights.to_numpy()[exposed])
    present_weight = math.fsum(float(value) for value in present_weights)
    terminal_quantities: dict[str, dict[str, int | float]] = {}
    terminal_shares: dict[str, float | None] = {}
    for state in TERMINAL_STATES:
        group = checked_states.loc[checked_states["state"] == state]
        weight = math.fsum(float(value) for value in group["weight"])
        terminal_quantities[state] = {
            "outcome_records": int(len(group)),
            "source_rows": int(group["source_person_id"].nunique()),
            "weight": weight,
        }
        terminal_shares[state] = weight / cohort_weight if cohort_weight else None
    arrived = terminal_quantities["arrived"]
    unserved_weight = math.fsum(
        float(values["weight"])
        for state, values in terminal_quantities.items()
        if state != "arrived"
    )
    identity = cohort_identity or {}
    if identity and set(COHORT_IDENTITY_FIELDS) - set(identity):
        raise ValueError("cohort identity is incomplete")
    contract = {
        "contract_version": DENOMINATOR_CONTRACT_VERSION,
        "scope": dict(DENOMINATOR_SCOPE),
        "capacity": dict(CAPACITY_METHOD),
        "quantities": {
            "full_population": quantity(full_population, full_weights),
            "sample": quantity(sample, sample_weights),
            "present": quantity(present, present_weights),
            "exposed_present": {
                "rows": int(exposed.sum()), "weight": exposed_weight,
                "denominator": "present",
            },
            "cohort": quantity(cohort, cohort_weights),
            "terminal_states": terminal_quantities,
        },
        "shares": {
            "exposed_of_present": exposed_weight / present_weight if present_weight else None,
            "terminal_of_cohort": terminal_shares,
        },
        "clearance_denominator": {
            "outcome_records": arrived["outcome_records"],
            "source_rows": arrived["source_rows"],
            "weight": arrived["weight"],
            "population": "arrivals_only",
        },
        "unserved_derived": {
            "weight": unserved_weight,
            "formula": "cohort.weight - terminal_states.arrived.weight",
            "is_conservation_term": False,
        },
        "conservation": {
            "cohort_weight": cohort_weight,
            "terminal_weight": terminal_weight,
            "residual_abs": residual,
            "absolute_tolerance": 1e-6,
            "passed": True,
        },
        "pairing": {
            "denominator_assignment": dict(DENOMINATOR_ASSIGNMENT),
            "common_identity": {
                key: identity[key] for key in COHORT_IDENTITY_FIELDS if key in identity
            },
            "sanctioned_numeric_variation": list(SANCTIONED_NUMERIC_VARIATION),
        },
    }
    return contract


def validate_denominator_contract(contract: Any) -> dict[str, Any]:
    """Reject malformed or internally inconsistent published denominator data."""
    try:
        if (
            not isinstance(contract, dict)
            or contract.get("contract_version") != DENOMINATOR_CONTRACT_VERSION
            or contract["scope"] != DENOMINATOR_SCOPE
            or contract["capacity"] != CAPACITY_METHOD
        ):
            raise ValueError

        def count(value: Any) -> int:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError
            return value

        def weight(value: Any) -> float:
            result = float(value)
            if not math.isfinite(result) or result < 0:
                raise ValueError
            return result

        quantities = contract["quantities"]
        population: dict[str, tuple[int, float]] = {}
        for name in ("full_population", "sample", "present", "cohort"):
            item = quantities[name]
            population[name] = (count(item["rows"]), weight(item["weight"]))
            if bool(population[name][0]) != bool(population[name][1]):
                raise ValueError
        for parent, child in (
            ("full_population", "sample"), ("sample", "present"), ("present", "cohort")
        ):
            if (
                population[child][0] > population[parent][0]
                or population[child][1] - population[parent][1] > 1e-6
            ):
                raise ValueError

        present_rows, present_weight = population["present"]
        exposed = quantities["exposed_present"]
        exposed_rows, exposed_weight = count(exposed["rows"]), weight(exposed["weight"])
        exposed_share = contract["shares"]["exposed_of_present"]
        exposed_share = None if exposed_share is None else float(exposed_share)
        expected_exposed_share = exposed_weight / present_weight if present_weight else None
        if (
            exposed.get("denominator") != "present"
            or exposed_rows > present_rows
            or exposed_weight - present_weight > 1e-6
            or bool(exposed_rows) != bool(exposed_weight)
            or not _same_optional_share(exposed_share, expected_exposed_share)
        ):
            raise ValueError

        cohort_rows, cohort_weight = population["cohort"]
        terms = quantities["terminal_states"]
        shares = contract["shares"]["terminal_of_cohort"]
        if set(terms) != set(TERMINAL_STATES) or set(shares) != set(TERMINAL_STATES):
            raise ValueError
        terminal_weights: dict[str, float] = {}
        terminal_records = 0
        for state in TERMINAL_STATES:
            state_weight = weight(terms[state]["weight"])
            records = count(terms[state]["outcome_records"])
            sources = count(terms[state]["source_rows"])
            share = shares[state]
            share = None if share is None else float(share)
            if (
                records != sources
                or sources > cohort_rows
                or bool(records) != bool(state_weight)
                or not _same_optional_share(
                    share, state_weight / cohort_weight if cohort_weight else None
                )
            ):
                raise ValueError
            terminal_records += records
            terminal_weights[state] = state_weight
        terminal_weight = math.fsum(terminal_weights.values())
        if not cohort_rows <= terminal_records <= 2 * cohort_rows:
            raise ValueError

        arrived = terms["arrived"]
        clearance = contract["clearance_denominator"]
        if (
            clearance.get("population") != "arrivals_only"
            or count(clearance["outcome_records"]) != count(arrived["outcome_records"])
            or count(clearance["source_rows"]) != count(arrived["source_rows"])
            or abs(weight(clearance["weight"]) - terminal_weights["arrived"]) > 1e-6
        ):
            raise ValueError

        unserved_block = contract["unserved_derived"]
        unserved = weight(unserved_block["weight"])
        expected_unserved = math.fsum(
            terminal_weights[state] for state in TERMINAL_STATES if state != "arrived"
        )
        conservation = contract["conservation"]
        residual = abs(cohort_weight - terminal_weight)
        if (
            unserved_block.get("formula") != "cohort.weight - terminal_states.arrived.weight"
            or unserved_block.get("is_conservation_term") is not False
            or abs(unserved - expected_unserved) > 1e-6
            or residual > 1e-6
            or abs(weight(conservation["cohort_weight"]) - cohort_weight) > 1e-6
            or abs(weight(conservation["terminal_weight"]) - terminal_weight) > 1e-6
            or abs(weight(conservation["residual_abs"]) - residual) > 1e-6
            or conservation.get("absolute_tolerance") != 1e-6
            or conservation.get("passed") is not True
        ):
            raise ValueError

        pairing = contract["pairing"]
        common_identity = pairing["common_identity"]
        if (
            pairing.get("denominator_assignment") != DENOMINATOR_ASSIGNMENT
            or pairing.get("sanctioned_numeric_variation")
            != list(SANCTIONED_NUMERIC_VARIATION)
            or not isinstance(common_identity, dict)
            or (common_identity and set(common_identity) != set(COHORT_IDENTITY_FIELDS))
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid denominator contract") from exc
    return contract


def _same_optional_share(actual: float | None, expected: float | None) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return math.isfinite(actual) and 0 <= actual <= 1 and abs(actual - expected) <= 1e-6


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
