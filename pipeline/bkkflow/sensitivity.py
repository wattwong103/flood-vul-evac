"""One-at-a-time sensitivity cases for the demonstration evacuation model.

The approved levels are scenario bounds. A case may move one factor away from
the baseline. It is not a calibration, an interaction study, or a city result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import read_json

APPROVED_FLOOD_SEVERITIES = ("low", "moderate", "high")
APPROVED_COMPLIANCE = (0.6, 0.78, 0.9)
APPROVED_WARNING_REACH = (0.7, 0.92, 1.0)
APPROVED_DELAY_MEAN_S = (300.0, 900.0, 1800.0)
APPROVED_DELAY_SD_S = 600.0
APPROVED_THRESHOLD = "bkk-demo-thresholds-v0.1"
COMPARISON_FACTORS = (
    "flood",
    "compliance",
    "warning_reach",
    "preparation_delay_mean_s",
)
LIMITATIONS = (
    "Departure priors are uncalibrated scenario bounds.",
    "The design is one-at-a-time and is not an interaction study.",
    "Clearance percentiles use arrived weight only and sit beside the not-departed shares.",
    "These are scenario results for the named area of interest.",
)
_CITYWIDE_AOI = {"bangkok", "bangkok-bma"}
_LEVEL_TOLERANCE = 1e-9


@dataclass(frozen=True)
class SensitivityCase:
    """One executable case, including the unchanged baseline."""

    case_id: str
    factor: str | None
    level: str
    flood_enabled: bool
    flood_severity: str
    active_state: str
    compliance: float
    warning_reach: float
    preparation_delay_mean_s: float
    preparation_delay_sd_s: float
    threshold_set_version: str


@dataclass(frozen=True)
class SensitivityTable:
    """The frozen level lists and the baseline they move away from."""

    baseline: SensitivityCase
    flood_severity: tuple[str, ...]
    compliance: tuple[float, ...]
    warning_reach: tuple[float, ...]
    preparation_delay_mean_s: tuple[float, ...]
    threshold_set_version: str


def _matches(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=_LEVEL_TOLERANCE)


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"sensitivity {name} must be a finite number")
    return float(value)


def _canonical(value: float, levels: tuple[float, ...], name: str) -> float:
    for level in levels:
        if _matches(value, level):
            return float(level)
    raise ValueError(f"unknown {name} level")


def _level_text(factor: str, level: str) -> str:
    if factor == "flood":
        return f"flood-{level}"
    if factor == "compliance":
        return f"compliance-{float(level):.2f}"
    if factor == "warning_reach":
        return f"warning-reach-{float(level):.2f}"
    if factor == "preparation_delay_mean_s":
        return f"delay-mean-{int(float(level))}"
    raise ValueError(f"unknown sensitivity factor {factor!r}")


def _case_id(factor: str | None, level: str) -> str:
    if factor is None:
        return "baseline"
    return _level_text(factor, level)


def _require_exact_numbers(actual: Any, expected: tuple[float, ...], name: str) -> tuple[float, ...]:
    if not isinstance(actual, list) or len(actual) != len(expected):
        raise ValueError(f"sensitivity {name} levels do not match the approved set")
    values = []
    for item, approved in zip(actual, expected):
        number = _finite_number(item, name)
        if not _matches(number, approved):
            raise ValueError(f"sensitivity {name} levels do not match the approved set")
        values.append(float(approved))
    return tuple(values)


def _make_case(
    *,
    factor: str | None,
    level: str,
    flood_enabled: bool,
    flood_severity: str,
    compliance: float,
    warning_reach: float,
    preparation_delay_mean_s: float,
    preparation_delay_sd_s: float,
    threshold_set_version: str,
) -> SensitivityCase:
    if flood_enabled:
        active_state = flood_severity if factor == "flood" else "moderate"
    else:
        active_state = "dry"
    return SensitivityCase(
        case_id=_case_id(factor, level),
        factor=factor,
        level=level,
        flood_enabled=flood_enabled,
        flood_severity=flood_severity,
        active_state=active_state,
        compliance=compliance,
        warning_reach=warning_reach,
        preparation_delay_mean_s=preparation_delay_mean_s,
        preparation_delay_sd_s=preparation_delay_sd_s,
        threshold_set_version=threshold_set_version,
    )


def load_sensitivity_table(scenario: dict[str, Any]) -> SensitivityTable:
    """Load the approved one-at-a-time table from a scenario document."""
    block = scenario.get("sensitivity") if isinstance(scenario, dict) else None
    if not isinstance(block, dict):
        raise ValueError("scenario sensitivity block is missing")
    if block.get("design") != "one_at_a_time":
        raise ValueError("sensitivity design must be one_at_a_time")
    if block.get("status") != "demonstration":
        raise ValueError("sensitivity status must be demonstration")
    baseline = block.get("baseline")
    if not isinstance(baseline, dict):
        raise ValueError("sensitivity baseline is missing")
    if baseline.get("flood_enabled") is not True:
        raise ValueError("sensitivity baseline flood must be enabled")
    if baseline.get("flood_severity") != "moderate":
        raise ValueError("unknown flood severity")
    if list(block.get("flood_severity") or []) != list(APPROVED_FLOOD_SEVERITIES):
        raise ValueError("unknown flood severity")
    compliance = _require_exact_numbers(block.get("compliance"), APPROVED_COMPLIANCE, "compliance")
    warning = _require_exact_numbers(block.get("warning_reach"), APPROVED_WARNING_REACH, "warning reach")
    delay = _require_exact_numbers(
        block.get("preparation_delay_mean_s"), APPROVED_DELAY_MEAN_S, "preparation delay"
    )
    thresholds = block.get("threshold_set_version")
    if (
        not isinstance(thresholds, list)
        or len(thresholds) != 1
        or thresholds[0] != APPROVED_THRESHOLD
    ):
        raise ValueError("sensitivity allows one threshold set")
    if baseline.get("threshold_set_version") != APPROVED_THRESHOLD:
        raise ValueError("sensitivity allows one threshold set")
    baseline_compliance = _canonical(
        _finite_number(baseline.get("compliance"), "compliance"), compliance, "compliance"
    )
    baseline_warning = _canonical(
        _finite_number(baseline.get("warning_reach"), "warning reach"), warning, "warning reach"
    )
    baseline_delay = _canonical(
        _finite_number(baseline.get("preparation_delay_mean_s"), "preparation delay"),
        delay,
        "preparation delay",
    )
    baseline_sd = _finite_number(baseline.get("preparation_delay_sd_s"), "preparation delay sd")
    if not _matches(baseline_sd, APPROVED_DELAY_SD_S):
        raise ValueError("unknown preparation delay level")
    if not _matches(baseline_compliance, 0.78) or not _matches(baseline_warning, 0.92):
        raise ValueError("sensitivity baseline is not the admitted prior")
    if not _matches(baseline_delay, 900.0):
        raise ValueError("sensitivity baseline is not the admitted prior")
    case = _make_case(
        factor=None,
        level="baseline",
        flood_enabled=True,
        flood_severity="moderate",
        compliance=baseline_compliance,
        warning_reach=baseline_warning,
        preparation_delay_mean_s=baseline_delay,
        preparation_delay_sd_s=float(APPROVED_DELAY_SD_S),
        threshold_set_version=APPROVED_THRESHOLD,
    )
    return SensitivityTable(
        baseline=case,
        flood_severity=APPROVED_FLOOD_SEVERITIES,
        compliance=compliance,
        warning_reach=warning,
        preparation_delay_mean_s=delay,
        threshold_set_version=APPROVED_THRESHOLD,
    )


def resolve_sensitivity_case(
    table: SensitivityTable,
    *,
    flood_enabled: bool | None = None,
    flood_severity: str | None = None,
    compliance: float | None = None,
    warning_reach: float | None = None,
    preparation_delay_mean_s: float | None = None,
    threshold_set_version: str | None = None,
) -> SensitivityCase:
    """Return the one case these overrides select, or reject a mixed case."""
    if threshold_set_version is not None and threshold_set_version != table.threshold_set_version:
        raise ValueError("sensitivity allows one threshold set")
    enabled = table.baseline.flood_enabled if flood_enabled is None else flood_enabled
    if type(enabled) is not bool:
        raise ValueError("flood_enabled must be boolean")
    if not enabled and flood_severity is not None:
        raise ValueError("sensitivity case changes more than one factor")
    if enabled:
        severity = table.baseline.flood_severity if flood_severity is None else flood_severity
        if severity not in table.flood_severity:
            raise ValueError(f"unknown flood severity {severity!r}")
    else:
        severity = "low"
    compliance_value = _canonical(
        table.baseline.compliance if compliance is None else _finite_number(compliance, "compliance"),
        table.compliance,
        "compliance",
    )
    warning_value = _canonical(
        table.baseline.warning_reach if warning_reach is None else _finite_number(warning_reach, "warning reach"),
        table.warning_reach,
        "warning reach",
    )
    delay_value = _canonical(
        table.baseline.preparation_delay_mean_s
        if preparation_delay_mean_s is None
        else _finite_number(preparation_delay_mean_s, "preparation delay"),
        table.preparation_delay_mean_s,
        "preparation delay",
    )
    flood_level = "moderate" if enabled else "dry"
    if enabled and severity != table.baseline.flood_severity:
        flood_level = severity
    changes: list[tuple[str, str]] = []
    if flood_level != "moderate":
        changes.append(("flood", flood_level))
    if not _matches(compliance_value, table.baseline.compliance):
        changes.append(("compliance", f"{compliance_value:.2f}"))
    if not _matches(warning_value, table.baseline.warning_reach):
        changes.append(("warning_reach", f"{warning_value:.2f}"))
    if not _matches(delay_value, table.baseline.preparation_delay_mean_s):
        changes.append(("preparation_delay_mean_s", str(int(delay_value))))
    if len(changes) > 1:
        raise ValueError("sensitivity case changes more than one factor")
    factor, level = (None, "baseline") if not changes else changes[0]
    return _make_case(
        factor=factor,
        level=level,
        flood_enabled=enabled,
        flood_severity=severity if enabled else table.baseline.flood_severity,
        compliance=compliance_value,
        warning_reach=warning_value,
        preparation_delay_mean_s=delay_value,
        preparation_delay_sd_s=table.baseline.preparation_delay_sd_s,
        threshold_set_version=table.threshold_set_version,
    )


def ensemble_cases(table: SensitivityTable) -> tuple[SensitivityCase, ...]:
    """Baseline plus each approved one-factor move, in factor order."""
    cases = [table.baseline, resolve_sensitivity_case(table, flood_enabled=False)]
    for severity in table.flood_severity:
        if severity == table.baseline.flood_severity:
            continue
        cases.append(resolve_sensitivity_case(table, flood_severity=severity))
    for compliance in table.compliance:
        if _matches(compliance, table.baseline.compliance):
            continue
        cases.append(resolve_sensitivity_case(table, compliance=compliance))
    for warning in table.warning_reach:
        if _matches(warning, table.baseline.warning_reach):
            continue
        cases.append(resolve_sensitivity_case(table, warning_reach=warning))
    for delay in table.preparation_delay_mean_s:
        if _matches(delay, table.baseline.preparation_delay_mean_s):
            continue
        cases.append(resolve_sensitivity_case(table, preparation_delay_mean_s=delay))
    return tuple(cases)


def sensitivity_case_by_id(table: SensitivityTable, case_id: str) -> SensitivityCase:
    matches = [case for case in ensemble_cases(table) if case.case_id == case_id]
    if len(matches) != 1:
        raise ValueError(f"unknown sensitivity case {case_id!r}")
    return matches[0]


def select_run_case(
    table: SensitivityTable,
    *,
    case_id: str | None,
    dry_requested: bool,
    flood_severity: str | None,
    compliance: float | None,
    warning_reach: float | None,
    preparation_delay_mean_s: float | None,
    threshold_set_version: str | None,
) -> SensitivityCase | None:
    """Select a sensitivity case, or return None for an ordinary run."""
    explicit = any(
        value is not None
        for value in (
            case_id,
            flood_severity,
            compliance,
            warning_reach,
            preparation_delay_mean_s,
            threshold_set_version,
        )
    )
    if not explicit:
        return None
    if case_id is not None:
        case = sensitivity_case_by_id(table, case_id)
        if dry_requested == case.flood_enabled:
            raise ValueError("sensitivity case does not match the requested flood state")
        if flood_severity is not None and (
            not case.flood_enabled or flood_severity != case.flood_severity
        ):
            raise ValueError("sensitivity case changes more than one factor")
        if compliance is not None and not _matches(float(compliance), case.compliance):
            raise ValueError("sensitivity case changes more than one factor")
        if warning_reach is not None and not _matches(float(warning_reach), case.warning_reach):
            raise ValueError("sensitivity case changes more than one factor")
        if preparation_delay_mean_s is not None and not _matches(
            float(preparation_delay_mean_s), case.preparation_delay_mean_s
        ):
            raise ValueError("sensitivity case changes more than one factor")
        if threshold_set_version is not None and threshold_set_version != case.threshold_set_version:
            raise ValueError("sensitivity allows one threshold set")
        return case
    return resolve_sensitivity_case(
        table,
        flood_enabled=False if dry_requested else None,
        flood_severity=flood_severity,
        compliance=compliance,
        warning_reach=warning_reach,
        preparation_delay_mean_s=preparation_delay_mean_s,
        threshold_set_version=threshold_set_version,
    )


def require_baseline_matches_scenario(scenario: dict[str, Any], table: SensitivityTable) -> None:
    """Reject a scenario whose stored defaults differ from the sensitivity baseline."""
    flood = scenario.get("flood") if isinstance(scenario.get("flood"), dict) else {}
    evacuation = scenario.get("evacuation") if isinstance(scenario.get("evacuation"), dict) else {}
    baseline = table.baseline
    checks = (
        (flood.get("severity") == baseline.flood_severity, "flood severity"),
        (_matches(_finite_number(evacuation.get("compliance"), "compliance"), baseline.compliance), "compliance"),
        (
            _matches(_finite_number(evacuation.get("warning_reach"), "warning reach"), baseline.warning_reach),
            "warning reach",
        ),
        (
            _matches(
                _finite_number(evacuation.get("preparation_delay_mean_s"), "preparation delay"),
                baseline.preparation_delay_mean_s,
            ),
            "preparation delay",
        ),
        (
            _matches(
                _finite_number(evacuation.get("preparation_delay_sd_s"), "preparation delay sd"),
                baseline.preparation_delay_sd_s,
            ),
            "preparation delay sd",
        ),
        (flood.get("threshold_set_version") == baseline.threshold_set_version, "threshold set"),
    )
    mismatched = [name for passed, name in checks if not passed]
    if mismatched:
        raise ValueError(
            "scenario defaults do not match the sensitivity baseline: " + ", ".join(mismatched)
        )


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, str) or isinstance(right, str):
        return left == right
    return _matches(float(left), float(right))


def _flood_level(manifest: dict[str, Any]) -> str:
    active = manifest.get("active_scenario")
    if not isinstance(active, dict):
        raise ValueError("active scenario is missing")
    state = active.get("state")
    severity = (manifest.get("flood_scenario") or {}).get("parameters", {}).get("severity")
    if state == "dry":
        return "dry"
    if state not in APPROVED_FLOOD_SEVERITIES or state != severity:
        raise ValueError("flood severity does not match the active scenario")
    return str(state)


def _case_parameters(manifest: dict[str, Any]) -> dict[str, Any]:
    departure = (manifest.get("evacuation_scenario") or {}).get("departure_model")
    thresholds = (manifest.get("evacuation_scenario") or {}).get("mode_thresholds")
    if not isinstance(departure, dict) or not isinstance(thresholds, dict):
        raise ValueError("departure model is missing")
    if departure.get("rng") != "predraw-v1":
        raise ValueError("sensitivity runs require departure rng predraw-v1")
    return {
        "flood": _flood_level(manifest),
        "compliance": _finite_number(departure.get("compliance"), "compliance"),
        "warning_reach": _finite_number(departure.get("warning_reach"), "warning reach"),
        "preparation_delay_mean_s": _finite_number(
            departure.get("preparation_delay_mean_s"), "preparation delay"
        ),
        "preparation_delay_sd_s": _finite_number(
            departure.get("preparation_delay_sd_s"), "preparation delay sd"
        ),
        "threshold": thresholds.get("version"),
    }


def _share(weight: float, total: float) -> float:
    return weight / total


def build_sensitivity_ensemble(run_dirs: list[Path]) -> dict[str, Any]:
    """Read saved runs and publish one demonstration sensitivity table."""
    if not run_dirs:
        raise ValueError("sensitivity ensemble has no runs")
    loaded = []
    for run_dir in run_dirs:
        manifest = read_json(Path(run_dir) / "manifest.json")
        stats = read_json(Path(run_dir) / "stats.json")
        loaded.append((Path(run_dir), manifest, stats))

    aoi_ids = set()
    cohort_ids = set()
    rows = []
    for run_dir, manifest, stats in loaded:
        geography = manifest.get("geography") if isinstance(manifest.get("geography"), dict) else {}
        stats_geography = stats.get("geography") if isinstance(stats.get("geography"), dict) else {}
        aoi_id = geography.get("aoi_id")
        if not isinstance(aoi_id, str) or not aoi_id or aoi_id != stats_geography.get("aoi_id"):
            raise ValueError("sensitivity ensemble AOI is missing")
        if aoi_id in _CITYWIDE_AOI:
            raise ValueError("sensitivity ensemble is not a Bangkok result")
        aoi_ids.add(aoi_id)
        identity = (
            ((stats.get("denominators") or {}).get("pairing") or {}).get("common_identity") or {}
        )
        cohort_id = identity.get("cohort_digest")
        if not isinstance(cohort_id, str) or len(cohort_id) != 64:
            raise ValueError("sensitivity ensemble cohort id is missing")
        cohort_ids.add(cohort_id)
        active = manifest.get("active_scenario") if isinstance(manifest.get("active_scenario"), dict) else {}
        case_id = active.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("sensitivity case id is missing")
        cohort = ((stats.get("denominators") or {}).get("quantities") or {}).get("cohort") or {}
        cohort_weight = _finite_number(cohort.get("weight"), "cohort weight")
        if cohort_weight <= 0:
            raise ValueError("sensitivity cohort weight must be positive")
        evacuation = stats.get("evacuation") if isinstance(stats.get("evacuation"), dict) else {}
        states = evacuation.get("state_distribution")
        reasons = evacuation.get("reason_weights")
        clearance = evacuation.get("clearance_sensitivity_minutes")
        published = evacuation.get("clearance_time_minutes")
        if not isinstance(states, dict) or not isinstance(reasons, dict) or not isinstance(clearance, dict):
            raise ValueError("sensitivity clearance is missing")
        if not isinstance(published, dict):
            raise ValueError("sensitivity clearance is missing")
        arrived_denominator = (
            (stats.get("denominators") or {}).get("clearance_denominator") or {}
        ).get("weight")
        arrived_weight = _finite_number(clearance.get("arrived_weight"), "arrived weight")
        if arrived_denominator is None or abs(
            arrived_weight - _finite_number(arrived_denominator, "arrived weight")
        ) > 1e-6:
            raise ValueError("arrived clearance denominator does not match")
        p50 = clearance.get("p50")
        p90 = clearance.get("p90")
        median = published.get("median")
        if (p50 is None) != (median is None) or (
            p50 is not None and not _matches(_finite_number(p50, "p50"), _finite_number(median, "median"))
        ):
            raise ValueError("sensitivity p50 does not match the published median")
        state_weights = {
            name: _finite_number(states.get(name, 0.0), name) for name in (
                "did_not_depart", "route_failed", "shelter_full", "stranded"
            )
        }
        reason_weights = {
            name: _finite_number(reasons.get(name, 0.0), name) for name in ("not_warned", "not_compliant")
        }
        if abs(
            reason_weights["not_warned"] + reason_weights["not_compliant"]
            - state_weights["did_not_depart"]
        ) > 1e-6:
            raise ValueError("not-departed reasons do not match did_not_depart")
        rows.append({
            "run_dir": run_dir,
            "run_id": stats.get("run_id"),
            "case_id": case_id,
            "aoi_id": aoi_id,
            "cohort_id": cohort_id,
            "parameters": _case_parameters(manifest),
            "sample_denominator": {
                "rows": cohort.get("rows"),
                "weight": cohort_weight,
            },
            "weights": {**state_weights, **reason_weights},
            "clearance_minutes": {
                "p50": None if p50 is None else _finite_number(p50, "p50"),
                "p90": None if p90 is None else _finite_number(p90, "p90"),
                "arrived_weight": arrived_weight,
            },
        })

    if len(aoi_ids) != 1:
        raise ValueError("sensitivity ensemble mixes areas of interest")
    if len(cohort_ids) != 1:
        raise ValueError("sensitivity ensemble cohort id does not match")
    case_ids = [row["case_id"] for row in rows]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate sensitivity case")
    baseline_rows = [row for row in rows if row["case_id"] == "baseline"]
    if len(baseline_rows) != 1:
        raise ValueError("sensitivity ensemble baseline is missing")
    baseline = baseline_rows[0]
    published_rows = []
    for row in rows:
        changes = [
            factor for factor in COMPARISON_FACTORS
            if not _same(row["parameters"][factor], baseline["parameters"][factor])
        ]
        if (
            not _same(row["parameters"]["preparation_delay_sd_s"], baseline["parameters"]["preparation_delay_sd_s"])
            or row["parameters"]["threshold"] != baseline["parameters"]["threshold"]
        ):
            raise ValueError("sensitivity case changes more than one factor")
        if len(changes) > 1:
            raise ValueError("sensitivity case changes more than one factor")
        if not changes:
            if row["case_id"] != "baseline":
                raise ValueError("sensitivity case id does not match its factor")
            factor, level = None, "baseline"
        else:
            factor = changes[0]
            level = str(row["parameters"][factor])
            if factor in {"compliance", "warning_reach"}:
                level = f"{float(level):.2f}"
            elif factor == "preparation_delay_mean_s":
                level = str(int(float(level)))
            if row["case_id"] != _case_id(factor, level):
                raise ValueError("sensitivity case id does not match its factor")
        total = row["sample_denominator"]["weight"]
        published_rows.append({
            "case_id": row["case_id"],
            "run_id": row["run_id"],
            "factor": factor,
            "level": level if factor != "flood" else row["parameters"]["flood"],
            "cohort_id": row["cohort_id"],
            "sample_denominator": row["sample_denominator"],
            "shares": {
                name: _share(row["weights"][name], total)
                for name in (
                    "did_not_depart",
                    "not_warned",
                    "not_compliant",
                    "route_failed",
                    "shelter_full",
                    "stranded",
                )
            },
            "clearance_minutes": row["clearance_minutes"],
        })
    aoi_id = next(iter(aoi_ids))
    return {
        "status": "demonstration",
        "design": "one_at_a_time",
        "compared_with": "ensemble_baseline",
        "aoi_id": aoi_id,
        "cohort_id": next(iter(cohort_ids)),
        "citywide": False,
        "limitations": list(LIMITATIONS),
        "cases": published_rows,
    }
