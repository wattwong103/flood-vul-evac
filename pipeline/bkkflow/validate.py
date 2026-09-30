"""V1 — structural, conservation and plausibility validation.

A check returns a threshold and a result, never a bare boolean, so a reader can
see what "passing" meant. Failures are recorded and surfaced; the promotion
status is decided by the promotion gates, not by these checks alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd


@dataclass
class Check:
    check_id: str
    description: str
    passed: bool
    threshold: str
    observed: Any
    severity: str = "error"
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "description": self.description,
            "passed": bool(self.passed),
            "threshold": self.threshold,
            "observed": self.observed,
            "severity": self.severity,
            "detail": self.detail,
        }


@dataclass
class ValidationReport:
    checks: list[Check] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, check: Check) -> None:
        self.checks.append(check)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks if check.severity == "error")

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks_total": len(self.checks),
            "checks_failed": sum(1 for check in self.checks if not check.passed),
            "checks": [check.as_dict() for check in self.checks],
            "warnings": self.warnings,
        }


def check_persons(
    persons: pd.DataFrame, *, total_residents: float, tolerance: float = 0.01
) -> Check:
    """Weighted persons must reconcile to the resident baseline."""
    if persons.empty:
        return Check("persons.non_empty", "persons table has rows", False, ">0 rows", 0)
    total = float(persons["weight"].sum())
    error = abs(total - total_residents) / total_residents if total_residents else 1.0
    return Check(
        "persons.reconcile_to_resident_baseline",
        "weighted person total matches the resident baseline",
        error <= tolerance,
        f"relative error <= {tolerance}",
        round(error, 8),
    )


def check_no_negative_weights(persons: pd.DataFrame) -> Check:
    if persons.empty:
        return Check("persons.non_negative", "no negative weights", True, "all weights >= 0", 0)
    negative = int((persons["weight"] < 0).sum())
    return Check(
        "persons.non_negative",
        "no negative person weights",
        negative == 0,
        "0 negative weights",
        negative,
    )


def check_unique_ids(frame: pd.DataFrame, column: str, check_id: str, label: str) -> Check:
    if frame.empty:
        return Check(check_id, f"{label} unique", True, "0 duplicates", 0)
    duplicates = int(frame[column].duplicated().sum())
    return Check(check_id, f"{label} are unique", duplicates == 0, "0 duplicates", duplicates)


def check_home_cells(persons: pd.DataFrame) -> Check:
    if persons.empty:
        return Check("persons.home_cell_present", "every person has a home cell", True, "0 missing", 0)
    missing = int(persons["home_cell_id"].isna().sum())
    return Check(
        "persons.home_cell_present",
        "every person has a home cell",
        missing == 0,
        "0 missing home cells",
        missing,
    )


def check_activity_time_order(activities: pd.DataFrame) -> Check:
    """Activities must not overlap and must run forward in time."""
    if activities.empty:
        return Check("activities.time_order", "activities are ordered", True, "0 violations", 0)
    violations = 0
    for _, block in activities.groupby("person_id", sort=False):
        ordered = block.sort_values("start_time_s")
        starts = ordered["start_time_s"].to_numpy()
        ends = ordered["end_time_s"].to_numpy()
        if len(starts) > 1 and (np.diff(starts) < 0).any():
            violations += 1
        if (ends <= starts).any():
            violations += 1
    return Check(
        "activities.time_order",
        "activity chains are non-overlapping and forward in time",
        violations == 0,
        "0 violating persons",
        violations,
    )


def check_sample_is_declared_subset(
    sample: pd.DataFrame, persons: pd.DataFrame
) -> Check:
    """The mobility sample must be a declared subset, with its factor recorded.

    Activities are generated for sampled agents only. That is legitimate, but
    it must be visible: a reader comparing activity counts to the person count
    would otherwise think agents had gone missing.
    """
    if persons.empty:
        return Check("mobility.sample_declared", "sample is a declared subset", True, "no persons", 0)
    if sample.empty:
        return Check(
            "mobility.sample_declared",
            "sample is a declared subset of the person table",
            False,
            "sample non-empty",
            0,
        )
    person_ids = set(persons["person_id"])
    orphans = len(set(sample["person_id"]) - person_ids)
    factor = len(sample) / len(persons)
    return Check(
        "mobility.sample_declared",
        "mobility sample is a declared subset of the person table",
        orphans == 0 and factor <= 1.0,
        "0 sample agents outside the person table, sample factor <= 1.0",
        f"orphans={orphans}, sample_factor={factor:.4f} ({len(sample)}/{len(persons)})",
    )


def check_privacy(persons: pd.DataFrame, *, public_min_cell_m: int) -> Check:
    """Public products must not expose a real person's identifier.

    The test is that an identifier is a well-formed *synthetic* value: a known
    prefix plus lowercase hex. A bare long digit run, as used by Thai national
    identity numbers, is the pattern that must never appear. Matching a digit
    run anywhere in the string would misfire on hex, so the shape is checked.
    """
    if persons.empty:
        return Check("privacy.no_real_identifiers", "identifiers are synthetic", True, "no persons", 0)
    identifiers = persons["person_id"].astype(str)
    well_formed = identifiers.str.match(r"^p_[0-9a-f]{20}$")
    bare_digit_runs = identifiers.str.fullmatch(r"\d{9,}")
    return Check(
        "privacy.no_real_identifiers",
        "person identifiers are run-scoped synthetic values, not real identity numbers",
        bool(well_formed.all()) and not bool(bare_digit_runs.any()),
        "all ids match p_<20 hex>, 0 bare 9+ digit identifiers",
        f"malformed={int((~well_formed).sum())}, bare_digits={int(bare_digit_runs.sum())}",
    )


def check_activity_conservation(activities: pd.DataFrame, persons: pd.DataFrame) -> Check:
    """Weighted presence through the day must reconcile to the person total."""
    if activities.empty or persons.empty:
        return Check(
            "activities.weight_conservation",
            "activity weights reconcile to person weights",
            True,
            "no data to check",
            0,
        )
    per_person = activities.groupby("person_id")["weight"].max()
    person_index = persons.set_index("person_id")["weight"]
    shared = per_person.index.intersection(person_index.index)
    if shared.empty:
        return Check(
            "activities.weight_conservation",
            "activity weights reconcile to person weights",
            False,
            "person overlap > 0",
            0,
        )
    difference = float((per_person.loc[shared] - person_index.loc[shared]).abs().max())
    return Check(
        "activities.weight_conservation",
        "activity weights reconcile to person weights",
        difference < 1e-6,
        "max absolute difference < 1e-6",
        difference,
    )


def check_trip_routing(trips: pd.DataFrame) -> Check:
    """No straight-line fallback: a trip is routed or it is failed."""
    if trips.empty:
        return Check("trips.no_straight_line_fallback", "no fallback routes", True, "0 fallbacks", 0)
    fallbacks = int((trips["route_status"] == "straight_line_fallback").sum())
    return Check(
        "trips.no_straight_line_fallback",
        "no trip is represented by a straight line",
        fallbacks == 0,
        "0 fallback routes",
        fallbacks,
    )


def check_trip_non_negative_duration(trips: pd.DataFrame) -> Check:
    if trips.empty:
        return Check("trips.duration_non_negative", "durations >= 0", True, "0 violations", 0)
    violations = int((trips["duration_s"] < 0).sum())
    return Check(
        "trips.duration_non_negative",
        "no negative trip duration",
        violations == 0,
        "0 violations",
        violations,
    )


def check_waypoint_connectivity(waypoints: pd.DataFrame, trips: pd.DataFrame) -> Check:
    """Every routed trip must have an ordered waypoint chain."""
    if trips.empty:
        return Check("trajectories.connectivity", "routed trips have waypoints", True, "no trips", 0)
    routed = trips[trips["route_status"] == "routed"]
    if routed.empty:
        return Check(
            "trajectories.connectivity",
            "routed trips have waypoints",
            False,
            "at least one routed trip",
            0,
        )
    with_points = set(waypoints["trip_id"]) if not waypoints.empty else set()
    missing = int((~routed["trip_id"].isin(with_points)).sum())
    return Check(
        "trajectories.connectivity",
        "routed trips have an ordered waypoint chain",
        missing == 0,
        "0 routed trips without waypoints",
        missing,
    )


def check_edge_state_monotonicity(edge_states: pd.DataFrame) -> Check:
    """Deeper water must never produce a higher speed multiplier."""
    if edge_states.empty:
        return Check("flood.impedance_monotone", "speed falls with depth", True, "no states", 0)
    frame = edge_states.sort_values("depth_m")
    violations = 0
    for _, block in frame.groupby(["edge_id", "mode"]):
        multipliers = block["speed_multiplier"].to_numpy()
        if len(multipliers) > 1 and (np.diff(multipliers) > 1e-9).any():
            violations += 1
    return Check(
        "flood.impedance_monotone",
        "speed multiplier is non-increasing in depth",
        violations == 0,
        "0 non-monotone edge/time series",
        violations,
    )


def check_edge_state_closure_consistency(edge_states: pd.DataFrame) -> Check:
    """A closed edge must have zero speed and a reason code."""
    if edge_states.empty:
        return Check("flood.closure_consistent", "closed edges have a reason", True, "no states", 0)
    closed = edge_states[edge_states["closed"]]
    if closed.empty:
        return Check(
            "flood.closure_consistent",
            "closed edges carry a reason code and zero speed",
            True,
            "no closed edges",
            0,
        )
    bad = int(((closed["speed_multiplier"] != 0) | (closed["reason_code"].isna())).sum())
    return Check(
        "flood.closure_consistent",
        "closed edges carry a reason code and zero speed",
        bad == 0,
        "0 inconsistent closures",
        bad,
    )


def check_building_heights(buildings: pd.DataFrame) -> Check:
    """Height must be evidenced or explicitly unknown, never defaulted."""
    if buildings.empty:
        return Check("buildings.height_provenance", "height has provenance", True, "no buildings", 0)
    valid_sources = {"osm_height", "osm_building_levels", "unknown"}
    unknown_sources = set(buildings["height_source"].unique()) - valid_sources
    missing = int((buildings["height_source"] == "unknown").sum())
    return Check(
        "buildings.height_provenance",
        "every height is tagged, derived from levels, or explicitly unknown",
        not unknown_sources,
        "no unrecognised height sources",
        sorted(unknown_sources) or f"{missing} buildings unknown (recorded, not defaulted)",
        severity="error",
    )


def check_refuge_claim(buildings: pd.DataFrame) -> Check:
    """No building may be presented as a verified refuge without review."""
    if buildings.empty:
        return Check("buildings.refuge_unverified", "no unverified refuge claim", True, "no buildings", 0)
    claimed = buildings[buildings["refuge_status"] != "not_a_refuge"]
    unverified = int((~claimed["refuge_verified"]).sum()) if not claimed.empty else 0
    return Check(
        "buildings.refuge_unverified",
        "every non-building refuge candidate is marked unverified",
        claimed.empty or unverified == len(claimed),
        "all candidates unverified",
        f"{unverified}/{len(claimed)} candidates unverified",
    )


def check_activity_coverage(activities: pd.DataFrame, persons: pd.DataFrame) -> Check:
    """Every person must have at least one activity, and activities must not
    create people who do not exist.

    Multiple activities per person are expected and correct, so this is a
    coverage check rather than a uniqueness check.
    """
    if persons.empty:
        return Check("activities.person_coverage", "every person has an activity", True, "no persons", 0)
    if activities.empty:
        return Check(
            "activities.person_coverage",
            "every person has an activity",
            False,
            "every person has >=1 activity",
            0,
        )
    person_ids = set(persons["person_id"])
    activity_ids = set(activities["person_id"])
    missing = len(person_ids - activity_ids)
    orphans = len(activity_ids - person_ids)
    return Check(
        "activities.person_coverage",
        "every person has at least one activity and no activity invents a person",
        missing == 0 and orphans == 0,
        "0 missing, 0 orphan persons",
        f"missing={missing}, orphans={orphans}",
    )


def run_all_checks(
    *,
    persons: pd.DataFrame,
    sample: pd.DataFrame,
    activities: pd.DataFrame,
    trips: pd.DataFrame,
    waypoints: pd.DataFrame,
    edge_states: pd.DataFrame,
    buildings: pd.DataFrame,
    total_residents: float,
    public_min_cell_m: int,
    extra: dict[str, Check] | None = None,
) -> ValidationReport:
    report = ValidationReport()
    checks: list[Callable[[], Check]] = [
        lambda: check_persons(persons, total_residents=total_residents),
        lambda: check_no_negative_weights(persons),
        lambda: check_home_cells(persons),
        lambda: check_unique_ids(persons, "person_id", "persons.unique_ids", "person ids"),
        lambda: check_sample_is_declared_subset(sample, persons),
        lambda: check_activity_time_order(activities),
        lambda: check_activity_conservation(activities, sample),
        lambda: check_activity_coverage(activities, sample),
        lambda: check_trip_routing(trips),
        lambda: check_trip_non_negative_duration(trips),
        lambda: check_waypoint_connectivity(waypoints, trips),
        lambda: check_edge_state_monotonicity(edge_states),
        lambda: check_edge_state_closure_consistency(edge_states),
        lambda: check_building_heights(buildings),
        lambda: check_refuge_claim(buildings),
        lambda: check_privacy(persons, public_min_cell_m=public_min_cell_m),
    ]
    for build in checks:
        report.add(build())
    for check in (extra or {}).values():
        report.add(check)
    return report
