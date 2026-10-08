"""Independent reader for a saved BKK/FLOW replay bundle.

This module deliberately has no imports from the runner, evacuation, routing,
clearance, or summary code.  Manifest-listed files are matched to their saved
hashes; hashes for auxiliary JSON are audit-time observations, not proof that
the original external sources were authentic.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely import wkt

REQUIRED_ROLES = (
    "persons", "activities", "network_edges", "flood_slices", "edge_states",
    "cohort", "cohort_metadata", "refuges", "denominators", "evacuation_states",
)
TABLE_ROLES = tuple(role for role in REQUIRED_ROLES
                    if role not in {"cohort_metadata", "denominators"})
DENOMINATOR_CONTRACT_VERSION = "sample-denominators-v1"
PFLOW_CONTRACT_VERSION = "pflow-bkk-v0.1"
TERMINAL_STATES = ("arrived", "shelter_full", "stranded", "route_failed", "did_not_depart")
COHORT_IDENTITY_FIELDS = (
    "cohort_rule_version", "aoi_id", "seed", "max_agents", "order_radius_m",
    "scenario_time_s", "order_centre_lon", "order_centre_lat", "order_geometry_rule",
    "presence_rule", "sample_rule", "sample_digest", "sampling_probability", "cohort_digest",
)


@dataclass(frozen=True)
class AuditBundle:
    run_dir: Path
    run_id: str
    aoi_id: str
    manifest: dict[str, Any]
    run_state: dict[str, Any]
    stats: dict[str, Any]
    outputs: dict[str, dict[str, Any]]
    tables: dict[str, pd.DataFrame]
    cohort_metadata: dict[str, Any]
    denominators: dict[str, Any]
    file_hashes: dict[str, str]


@dataclass(frozen=True)
class CohortMetricAudit:
    sample_person_ids: tuple[str, ...]
    present_person_ids: tuple[str, ...]
    cohort_person_ids: tuple[str, ...]
    denominators: dict[str, Any]
    clearance_time_minutes: dict[str, float | None]


@dataclass(frozen=True)
class RouteAudit:
    status: str
    destination_id: str | None
    origin_node: Any | None
    destination_node: Any | None
    edge_ids: tuple[str, ...]
    cost_s: float | None
    distance_m: float | None


@dataclass(frozen=True)
class PeakRoutingAudit:
    routes: dict[str, RouteAudit]
    peak_open_edge_ids: tuple[str, ...]
    peak_closed_edge_ids: tuple[str, ...]
    top_bottleneck_edges: list[dict[str, str | float]]


@dataclass(frozen=True)
class EvacuationReplayAudit:
    states: pd.DataFrame
    remaining_capacity: dict[str, int]
    denominators: dict[str, Any]
    clearance_time_minutes: dict[str, float | None]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact is not an object: {path.name}")
    return value


def _field(value: dict[str, Any], *path: str) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"bundle field is missing: {'.'.join(path)}")
        current = current[key]
    return current


def _is_digest(value: Any, length: int = 64) -> bool:
    return (isinstance(value, str) and len(value) == length
            and all(character in "0123456789abcdef" for character in value))


def _read_outputs(
    root: Path, manifest: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, Path], dict[str, str]]:
    raw_outputs = manifest.get("outputs")
    if not isinstance(raw_outputs, list):
        raise ValueError("manifest outputs must be a list")
    outputs: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    seen_uris: set[str] = set()
    for entry in raw_outputs:
        if not isinstance(entry, dict):
            raise ValueError("manifest output entry must be an object")
        role, uri = entry.get("role"), entry.get("uri")
        if not isinstance(role, str) or not role:
            raise ValueError("manifest output role is invalid")
        if role in outputs:
            raise ValueError(f"duplicate output role: {role}")
        if not isinstance(uri, str) or not uri:
            raise ValueError(f"manifest output URI is invalid: {role}")
        if uri in seen_uris:
            raise ValueError(f"duplicate output URI: {uri}")
        relative = Path(uri)
        target = (root / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(root):
            raise ValueError(f"output path escapes run directory: {uri}")
        if not target.is_file():
            raise ValueError(f"registered output is missing: {role}")
        actual_hash = _sha256(target)
        if not _is_digest(entry.get("content_sha256")) or actual_hash != entry["content_sha256"]:
            raise ValueError(f"output hash mismatch: {role}")
        row_count = entry.get("row_count")
        if row_count is not None:
            if type(row_count) is not int or row_count < 0 or target.suffix != ".parquet":
                raise ValueError(f"output row count declaration is invalid: {role}")
            try:
                actual_rows = pq.ParquetFile(target).metadata.num_rows
            except Exception as exc:
                raise ValueError(f"registered Parquet output is invalid: {role}") from exc
            if actual_rows != row_count:
                raise ValueError(f"output row count mismatch: {role}")
        outputs[role], paths[role], hashes[uri] = entry, target, actual_hash
        seen_uris.add(uri)
    missing = sorted(set(REQUIRED_ROLES) - set(outputs))
    if missing:
        raise ValueError("missing required output role: " + ", ".join(missing))
    return outputs, paths, hashes


def _check_identity(
    root: Path,
    manifest: dict[str, Any],
    run_state: dict[str, Any],
    stats: dict[str, Any],
    cohort: dict[str, Any],
    denominators: dict[str, Any],
    refuges: pd.DataFrame,
) -> tuple[str, str]:
    common = _field(denominators, "pairing", "common_identity")
    run_ids = (root.name, _field(manifest, "run_id"), _field(run_state, "run_id"),
               _field(stats, "run_id"), _field(cohort, "run_id"))
    if any(value != run_ids[0] for value in run_ids):
        raise ValueError("run identity mismatch")
    aoi_ids = (_field(manifest, "geography", "aoi_id"), _field(cohort, "aoi_id"),
               _field(common, "aoi_id"))
    if any(value != aoi_ids[0] for value in aoi_ids):
        raise ValueError("AOI identity mismatch")
    seeds = (_field(manifest, "population_model", "seed"),
             _field(manifest, "evacuation_scenario", "seed"), _field(cohort, "seed"),
             _field(common, "seed"))
    if any(type(value) is not int for value in seeds) or len(set(seeds)) != 1:
        raise ValueError("seed identity mismatch")
    sample_caps = (
        _field(manifest, "pflow_contract", "activity_generator", "parameters", "sample_cap"),
        _field(cohort, "max_agents"), _field(common, "max_agents"),
    )
    if any(type(value) is not int for value in sample_caps) or len(set(sample_caps)) != 1:
        raise ValueError("sample-cap identity mismatch")
    if _field(manifest, "pflow_contract", "person_generator", "parameters", "seed") != seeds[0]:
        raise ValueError("seed identity mismatch")
    if _field(manifest, "pflow_contract", "contract_version") != PFLOW_CONTRACT_VERSION:
        raise ValueError("PFLOW contract mismatch")
    if denominators.get("contract_version") != DENOMINATOR_CONTRACT_VERSION:
        raise ValueError("denominator contract mismatch")
    if stats.get("denominators") != denominators:
        raise ValueError("denominator contract mismatch")
    if run_state.get("state") != "published":
        raise ValueError("run state is not published")
    active_scenario = manifest.get("active_scenario")
    if (
        not isinstance(active_scenario, dict)
        or set(active_scenario) != {"state", "configured_scenario_id"}
        or active_scenario.get("state") not in {"dry", "moderate"}
        or not isinstance(active_scenario.get("configured_scenario_id"), str)
        or not active_scenario["configured_scenario_id"]
        or run_state.get("active_scenario") != active_scenario
        or _field(manifest, "flood_scenario", "parameters", "scenario_id")
        != active_scenario["configured_scenario_id"]
    ):
        raise ValueError("active-scenario identity mismatch")
    if manifest.get("validation_status") != stats.get("validation_status"):
        raise ValueError("validation-status identity mismatch")

    numeric_config = (
        ("flood_scenario", "time_step_seconds"), ("flood_scenario", "parameters", "start_time_s"),
        ("flood_scenario", "parameters", "peak_time_s"), ("flood_scenario", "parameters", "end_time_s"),
        ("evacuation_scenario", "departure_model", "warning_time_s"),
        ("evacuation_scenario", "departure_model", "warning_reach"),
        ("evacuation_scenario", "departure_model", "compliance"),
        ("evacuation_scenario", "departure_model", "preparation_delay_mean_s"),
        ("evacuation_scenario", "departure_model", "preparation_delay_sd_s"),
    )
    if any(isinstance(value := _field(manifest, *path), bool)
           or not isinstance(value, (int, float)) or not math.isfinite(value)
           for path in numeric_config):
        raise ValueError("saved scenario configuration is invalid")

    code = _field(manifest, "code_identity")
    for key, length in (("git_commit", 40), ("git_tree", 40), ("source_sha256", 64)):
        value = code.get(key)
        if not (_is_digest(value, length) or (length == 40 and _is_digest(value))):
            raise ValueError("source identity is invalid")
    if code.get("verification") != "matched_before_publication":
        raise ValueError("source identity is invalid")
    if (code.get("git_status") not in {"clean", "dirty", "unavailable"}
            or type(code.get("source_files")) is not int or code["source_files"] <= 0
            or not isinstance(code.get("scope"), list) or "config" not in code["scope"]):
        raise ValueError("source identity is invalid")
    sources = manifest.get("source_versions")
    if not isinstance(sources, list) or not sources:
        raise ValueError("source identity is invalid")
    for source in sources:
        if (not isinstance(source, dict) or not source.get("source_id")
                or not _is_digest(source.get("content_sha256"))):
            raise ValueError("source identity is invalid")

    destination_rows = _field(manifest, "evacuation_scenario", "destinations")
    if not isinstance(destination_rows, list) or not all(
        isinstance(item, dict) and isinstance(item.get("dest_id"), str)
        and type(item.get("capacity")) is int for item in destination_rows
    ):
        raise ValueError("destination identity mismatch")
    declared = {(item["dest_id"], item["capacity"]) for item in destination_rows}
    saved = {(row.dest_id, int(row.capacity)) for row in refuges.itertuples()}
    if declared != saved:
        raise ValueError("destination identity mismatch")
    return str(run_ids[0]), str(aoi_ids[0])


def load_audit_bundle(run_dir: str | Path) -> AuditBundle:
    """Fail closed while loading the saved inputs required by later replay stages."""
    root = Path(run_dir).resolve()
    if not root.is_dir():
        raise ValueError("audit run directory does not exist")
    manifest_path = root / "manifest.json"
    stats_path, state_path = root / "stats.json", root / "run_state.json"
    manifest = _json_object(manifest_path)
    outputs, paths, file_hashes = _read_outputs(root, manifest)
    stats, run_state = _json_object(stats_path), _json_object(state_path)
    file_hashes.update({
        "manifest.json": _sha256(manifest_path),
        "stats.json": _sha256(stats_path),
        "run_state.json": _sha256(state_path),
    })
    tables = {role: pd.read_parquet(paths[role]) for role in TABLE_ROLES}
    cohort_metadata = _json_object(paths["cohort_metadata"])
    denominators = _json_object(paths["denominators"])
    run_id, aoi_id = _check_identity(
        root, manifest, run_state, stats, cohort_metadata, denominators, tables["refuges"]
    )
    return AuditBundle(root, run_id, aoi_id, manifest, run_state, stats, outputs, tables,
                       cohort_metadata, denominators, file_hashes)


def inverse_weighted_clearance(
    states: pd.DataFrame, *, warning_time_s: Any
) -> dict[str, float | None]:
    """Independently calculate the declared inverse weighted ECDF in minutes."""
    warning = float(warning_time_s)
    if not math.isfinite(warning) or warning < 0 or "state" not in states:
        raise ValueError("invalid warning time or terminal states")
    arrived = states.loc[states["state"] == "arrived"]
    if arrived.empty:
        return {"p5": None, "median": None, "p95": None}
    if not {"event_time_s", "weight"} <= set(arrived):
        raise ValueError("arrived records are incomplete")
    weights = pd.to_numeric(arrived["weight"], errors="coerce").to_numpy(float)
    clearances = pd.to_numeric(arrived["event_time_s"], errors="coerce").to_numpy(float) - warning
    if (~np.isfinite(weights)).any() or (weights <= 0).any() or (~np.isfinite(clearances)).any() or (clearances < 0).any():
        raise ValueError("arrived weights and clearance must be finite and non-negative")
    order = np.argsort(clearances, kind="stable")
    cumulative, total = [], Decimal(0)
    for value in weights[order]:
        total += Decimal(str(value))
        cumulative.append(total)
    quantiles = (("p5", Decimal("0.05")), ("median", Decimal("0.50")), ("p95", Decimal("0.95")))
    return {label: float(clearances[order[next(i for i, value in enumerate(cumulative)
                                               if value >= q * total)]]) / 60.0
            for label, q in quantiles}


def _person_weights(frame: pd.DataFrame, label: str) -> pd.Series:
    if not {"person_id", "weight"} <= set(frame) or frame["person_id"].isna().any() or frame["person_id"].duplicated().any():
        raise ValueError(f"{label} person identity mismatch")
    values = pd.to_numeric(frame["weight"], errors="coerce").to_numpy(float)
    if (~np.isfinite(values)).any() or (values <= 0).any():
        raise ValueError(f"{label} person weight mismatch")
    return pd.Series(values, index=frame["person_id"].astype(str))


def _same_people(actual: pd.DataFrame, expected: pd.DataFrame, label: str) -> None:
    actual_weights, expected_weights = _person_weights(actual, label), _person_weights(expected, label)
    if tuple(actual_weights.index) != tuple(expected_weights.index) or any(
        float(actual_weights.loc[key]).hex() != float(expected_weights.loc[key]).hex()
        for key in actual_weights.index
    ):
        raise ValueError(f"{label} identity mismatch")


def _derive_populations(bundle: AuditBundle) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    persons, activities = bundle.tables["persons"], bundle.tables["activities"]
    meta, seed, cap = bundle.cohort_metadata, bundle.cohort_metadata["seed"], bundle.cohort_metadata["max_agents"]
    if cap <= 0:
        raise ValueError("sample cap must be positive")
    _person_weights(persons, "full population")
    if len(persons) <= cap:
        sample = persons.copy()
    else:
        take = np.random.default_rng(seed).choice(len(persons), size=cap, replace=False)
        sample = persons.iloc[np.sort(take)].copy()
    at_time = meta["scenario_time_s"]
    if activities.empty:
        present = sample.copy()
    else:
        active = activities[(activities["start_time_s"] <= at_time) & (activities["end_time_s"] > at_time)]
        present = sample[sample["person_id"].isin(set(active["person_id"]))].copy()
    centre_lon = float(present["lon"].mean()) if len(present) else None
    centre_lat = float(present["lat"].mean()) if len(present) else None
    if len(present):
        distance = np.hypot(present["lon"] - centre_lon, present["lat"] - centre_lat)
        cohort = present.loc[distance <= meta["order_radius_m"] / 111_320.0].sort_values("person_id", kind="stable").copy()
    else:
        cohort = present.copy()
    cohort["order_id"] = ["order_" + hashlib.sha256(f"{bundle.aoi_id}|{person_id}".encode()).hexdigest()[:20]
                          for person_id in cohort["person_id"]]
    sampling_probability = min(1.0, cap / len(persons)) if len(persons) else 0.0
    cohort["sampling_probability"] = sampling_probability

    peak_time = _field(bundle.manifest, "flood_scenario", "parameters", "peak_time_s")
    surface = bundle.tables["flood_slices"]
    surface = surface.loc[surface["time_s"] == peak_time] if len(surface) else surface
    depths = np.zeros(len(present), dtype=float)
    if len(surface) and len(present):
        transformer = Transformer.from_crs("OGC:CRS84", _field(bundle.manifest, "geography", "analysis_crs"), always_xy=True)
        x, y = transformer.transform(present["lon"].to_numpy(), present["lat"].to_numpy())
        _, indices = cKDTree(surface[["x", "y"]].to_numpy(float)).query(np.column_stack([x, y]))
        depths = surface["peak_depth_m"].to_numpy(float)[indices]
    present["scenario_depth_m"] = np.round(depths, 4)
    threshold = float(meta["min_depth_m"])
    present["exposed"] = present["scenario_depth_m"] >= threshold if threshold > 0 else False
    cohort[["scenario_depth_m", "exposed"]] = present.loc[cohort.index, ["scenario_depth_m", "exposed"]]

    sample_rows = sample.sort_values("person_id", kind="stable")
    sample_digest = hashlib.sha256()
    for row in sample_rows.itertuples():
        sample_digest.update(f"{row.person_id}\0{float(row.weight).hex()}\n".encode())
    cohort_digest = hashlib.sha256(
        f"fixed-order-area-v1|{bundle.aoi_id}|{seed}|{cap}|{centre_lon}|{centre_lat}|".encode()
    )
    for row in cohort.itertuples():
        cohort_digest.update(f"{row.order_id}\0{row.person_id}\0{float(row.weight).hex()}\n".encode())
    identity = {
        "cohort_rule_version": "fixed-order-area-v1", "aoi_id": bundle.aoi_id,
        "seed": seed, "max_agents": cap, "order_radius_m": float(meta["order_radius_m"]),
        "scenario_time_s": int(at_time), "order_centre_lon": centre_lon,
        "order_centre_lat": centre_lat,
        "order_geometry_rule": "WGS84 degree distance <= order_radius_m / 111320",
        "presence_rule": "if activities exist: sampled person IDs with start_time_s <= scenario_time_s < end_time_s; otherwise full sample; order area uses stored person/home lon-lat",
        "sample_rule": "numpy.default_rng(seed).choice over full person row order without replacement; selected indices sorted; cap=min(full rows, max_agents)",
        "sample_digest": sample_digest.hexdigest(), "sampling_probability": sampling_probability,
        "cohort_digest": cohort_digest.hexdigest(),
    }
    if any(meta.get(key) != identity[key] for key in COHORT_IDENTITY_FIELDS):
        raise ValueError("cohort identity mismatch")
    _same_people(cohort, bundle.tables["cohort"], "cohort")
    saved = bundle.tables["cohort"].set_index("person_id")
    for row in cohort.itertuples():
        if (saved.loc[row.person_id, "order_id"] != row.order_id
                or float(saved.loc[row.person_id, "sampling_probability"]).hex() != sampling_probability.hex()
                or bool(saved.loc[row.person_id, "exposed"]) != bool(row.exposed)
                or abs(float(saved.loc[row.person_id, "scenario_depth_m"]) - row.scenario_depth_m) > 1e-6):
            raise ValueError("cohort identity mismatch")
    return sample, present, cohort


def _reconstruct_denominators(
    bundle: AuditBundle, sample: pd.DataFrame, present: pd.DataFrame, cohort: pd.DataFrame
) -> dict[str, Any]:
    full_weights = _person_weights(bundle.tables["persons"], "full population")
    sample_weights, present_weights = _person_weights(sample, "sample"), _person_weights(present, "present")
    cohort_weights = _person_weights(cohort, "cohort")
    states = bundle.tables["evacuation_states"].copy()
    required = {"outcome_id", "source_person_id", "source_weight", "state", "weight"}
    if not required <= set(states) or states["outcome_id"].isna().any() or states["outcome_id"].duplicated().any():
        raise ValueError("terminal record identity mismatch")
    if states["state"].isna().any() or set(states["state"]) - set(TERMINAL_STATES):
        raise ValueError("terminal state mismatch")
    weights = pd.to_numeric(states["weight"], errors="coerce").to_numpy(float)
    source_weights = pd.to_numeric(states["source_weight"], errors="coerce").to_numpy(float)
    if (~np.isfinite(weights)).any() or (weights <= 0).any() or (~np.isfinite(source_weights)).any() or (source_weights <= 0).any():
        raise ValueError("terminal weight mismatch")
    states["weight"], states["source_weight"] = weights, source_weights
    if set(states["source_person_id"].astype(str)) != set(cohort_weights.index):
        raise ValueError("terminal source identity mismatch")
    for source_id, group in states.groupby("source_person_id", sort=False):
        expected = float(cohort_weights.loc[str(source_id)])
        if any(float(value).hex() != expected.hex() for value in group["source_weight"]):
            raise ValueError("terminal source-weight mismatch")
        if abs(math.fsum(float(value) for value in group["weight"]) - expected) > 1e-6:
            raise ValueError("terminal source conservation mismatch")
        if len(group) > 1 and (len(group) != 2 or set(group["state"]) != {"arrived", "shelter_full"}):
            raise ValueError("terminal split mismatch")
        if group["state"].duplicated().any():
            raise ValueError("terminal fragment mismatch")

    def quantity(frame: pd.DataFrame, values: pd.Series) -> dict[str, int | float]:
        return {"rows": len(frame), "weight": math.fsum(float(value) for value in values)}

    cohort_weight = math.fsum(float(value) for value in cohort_weights)
    terminal_quantities, terminal_shares = {}, {}
    for state in TERMINAL_STATES:
        group = states.loc[states["state"] == state]
        weight = math.fsum(float(value) for value in group["weight"])
        terminal_quantities[state] = {
            "outcome_records": len(group), "source_rows": group["source_person_id"].nunique(),
            "weight": weight,
        }
        terminal_shares[state] = weight / cohort_weight if cohort_weight else None
    terminal_weight = math.fsum(item["weight"] for item in terminal_quantities.values())
    if abs(terminal_weight - cohort_weight) > 1e-6:
        raise ValueError("terminal conservation mismatch")
    exposed = present["exposed"].astype(bool).to_numpy()
    exposed_weight = math.fsum(float(value) for value in present_weights.to_numpy()[exposed])
    present_weight = math.fsum(float(value) for value in present_weights)
    arrived = terminal_quantities["arrived"]
    unserved = math.fsum(terminal_quantities[state]["weight"] for state in TERMINAL_STATES if state != "arrived")
    meta = bundle.cohort_metadata
    contract = {
        "contract_version": DENOMINATOR_CONTRACT_VERSION,
        "scope": {"population_basis": "deterministic_sample_only",
                  "representative_of_full_district_or_bangkok": False,
                  "reweighting_to_full_population": False},
        "capacity": {"method": "integerized", "integerization_rule": "max(round(source_weight), 1)",
                     "fractional_weight_partition": "proportional_to_admitted_integer_units"},
        "quantities": {
            "full_population": quantity(bundle.tables["persons"], full_weights),
            "sample": quantity(sample, sample_weights), "present": quantity(present, present_weights),
            "exposed_present": {"rows": int(exposed.sum()), "weight": exposed_weight,
                                "denominator": "present"},
            "cohort": quantity(cohort, cohort_weights), "terminal_states": terminal_quantities,
        },
        "shares": {"exposed_of_present": exposed_weight / present_weight if present_weight else None,
                   "terminal_of_cohort": terminal_shares},
        "clearance_denominator": {"outcome_records": arrived["outcome_records"],
                                  "source_rows": arrived["source_rows"], "weight": arrived["weight"],
                                  "population": "arrivals_only"},
        "unserved_derived": {"weight": unserved,
                             "formula": "cohort.weight - terminal_states.arrived.weight",
                             "is_conservation_term": False},
        "conservation": {"cohort_weight": cohort_weight, "terminal_weight": terminal_weight,
                         "residual_abs": abs(cohort_weight - terminal_weight),
                         "absolute_tolerance": 1e-6, "passed": True},
        "pairing": {
            "denominator_assignment": {"exposure": "exposed present / present",
                                       "terminal_states": "terminal state weight / fixed cohort",
                                       "clearance": "arrived records only"},
            "common_identity": {key: meta[key] for key in COHORT_IDENTITY_FIELDS},
            "sanctioned_numeric_variation": ["exposed_present", "terminal_states", "clearance_denominator"],
        },
    }
    if contract != bundle.denominators:
        raise ValueError("denominator reconstruction mismatch")
    return contract


def reconstruct_cohort_metrics(bundle: AuditBundle) -> CohortMetricAudit:
    """Rebuild F/S/P/C/E/A denominators and clearance without pipeline helpers."""
    sample, present, cohort = _derive_populations(bundle)
    denominators = _reconstruct_denominators(bundle, sample, present, cohort)
    warning = _field(bundle.manifest, "evacuation_scenario", "departure_model", "warning_time_s")
    clearance = inverse_weighted_clearance(bundle.tables["evacuation_states"], warning_time_s=warning)
    published = _field(bundle.stats, "evacuation", "clearance_time_minutes")
    for label, actual in clearance.items():
        expected = published.get(label) if isinstance(published, dict) else None
        if (actual is None) != (expected is None) or (
            actual is not None and abs(actual - float(expected)) > 0.01
        ):
            raise ValueError("published clearance mismatch")
    return CohortMetricAudit(
        tuple(sample["person_id"].astype(str)), tuple(present["person_id"].astype(str)),
        tuple(cohort["person_id"].astype(str)), denominators, clearance,
    )


def unique_shortest_route(
    graph: nx.Graph, origin: Any, destination: Any
) -> tuple[list[Any], float] | None:
    """Return one shortest route, rejecting an equally cheap alternative."""
    if origin == destination:
        return [origin], 0.0
    try:
        candidates = nx.shortest_simple_paths(graph, origin, destination, weight="cost")
        path = next(candidates)
        cost = math.fsum(graph[path[i]][path[i + 1]]["cost"] for i in range(len(path) - 1))
        alternative = next(candidates, None)
    except (nx.NetworkXNoPath, nx.NodeNotFound, StopIteration):
        return None
    if alternative is not None:
        alternative_cost = math.fsum(
            graph[alternative[i]][alternative[i + 1]]["cost"]
            for i in range(len(alternative) - 1)
        )
        if abs(alternative_cost - cost) <= 1e-6:
            raise ValueError("unexplained equal-cost path tie")
    return path, cost


def _peak_walk_graph(bundle: AuditBundle) -> tuple[nx.Graph, tuple[str, ...], tuple[str, ...]]:
    edges, states = bundle.tables["network_edges"], bundle.tables["edge_states"]
    edge_columns = {
        "edge_id", "u", "v", "length_m", "walk_allowed", "speed_walk_mps",
        "geometry_wkt",
    }
    state_columns = {"edge_id", "time_s", "mode", "speed_multiplier", "closed"}
    if not edge_columns <= set(edges) or not state_columns <= set(states):
        raise ValueError("routing inputs are incomplete")
    if edges["edge_id"].isna().any() or edges["edge_id"].duplicated().any():
        raise ValueError("network edge identity mismatch")
    if not edges["walk_allowed"].map(lambda value: isinstance(value, (bool, np.bool_))).all():
        raise ValueError("network walking eligibility mismatch")
    route_choice = _field(bundle.manifest, "evacuation_scenario", "route_choice")
    declared = {
        "algorithm": "astar_static_under_scenario_closure",
        "cost": "length / (dry_speed * depth_speed_multiplier)",
        "replanning": "none_single_pass",
    }
    if not isinstance(route_choice, dict) or any(route_choice.get(key) != value for key, value in declared.items()):
        raise ValueError("route-choice contract mismatch")

    peak_time = _field(bundle.manifest, "flood_scenario", "parameters", "peak_time_s")
    peak = states.loc[(states["time_s"] == peak_time) & (states["mode"] == 0)].copy()
    if peak["edge_id"].isna().any() or peak["edge_id"].duplicated().any():
        raise ValueError("peak walking edge-state identity mismatch")
    routable = edges.loc[edges["walk_allowed"].astype(bool) & edges["speed_walk_mps"].notna()]
    if set(routable["edge_id"].astype(str)) - set(peak["edge_id"].astype(str)):
        raise ValueError("peak walking edge state is missing")
    peak_by_id = peak.set_index(peak["edge_id"].astype(str))

    graph = nx.Graph()
    open_ids: list[str] = []
    closed_ids: list[str] = []
    for row in routable.itertuples():
        edge_id = str(row.edge_id)
        state = peak_by_id.loc[edge_id]
        multiplier = float(state["speed_multiplier"])
        if not math.isfinite(multiplier) or not 0.0 <= multiplier <= 1.0:
            raise ValueError("invalid peak walking speed multiplier")
        if not isinstance(state["closed"], (bool, np.bool_)):
            raise ValueError("peak walking closure flag is invalid")
        closed = bool(state["closed"])
        if closed != (multiplier == 0.0):
            raise ValueError("peak walking closure contradiction")
        if closed:
            closed_ids.append(edge_id)
            continue
        length, dry_speed = float(row.length_m), float(row.speed_walk_mps)
        if not math.isfinite(length) or length <= 0 or not math.isfinite(dry_speed) or dry_speed <= 0:
            raise ValueError("invalid routable edge length or speed")
        try:
            geometry = wkt.loads(row.geometry_wkt)
        except Exception as exc:
            raise ValueError("invalid network edge WKT") from exc
        if geometry.geom_type != "LineString" or geometry.is_empty or len(geometry.coords) < 2:
            raise ValueError("invalid network edge geometry")
        if abs(float(geometry.length) - length) > 1e-6:
            raise ValueError("network edge geometry-length mismatch")
        start, end = geometry.coords[0], geometry.coords[-1]
        for node, xy in ((row.u, start), (row.v, end)):
            if node in graph:
                saved = graph.nodes[node]
                if math.hypot(saved["x"] - xy[0], saved["y"] - xy[1]) > 1e-6:
                    raise ValueError("network node geometry mismatch")
            else:
                graph.add_node(node, x=float(xy[0]), y=float(xy[1]))
        cost = length / (dry_speed * multiplier)
        attributes = {
            "cost": cost, "length_m": length, "edge_id": edge_id,
            "dry_speed_mps": dry_speed, "speed_multiplier": multiplier,
        }
        if graph.has_edge(row.u, row.v):
            existing = graph[row.u][row.v]["cost"]
            if abs(existing - cost) <= 1e-6:
                raise ValueError("unexplained equal-cost parallel-edge tie")
            if cost < existing:
                graph[row.u][row.v].update(attributes)
        else:
            graph.add_edge(row.u, row.v, **attributes)
        open_ids.append(edge_id)
    return graph, tuple(open_ids), tuple(closed_ids)


def _nearest_destination(refuges: pd.DataFrame, x: float, y: float) -> pd.Series | None:
    if refuges.empty:
        return None
    if not {"dest_id", "x", "y"} <= set(refuges) or refuges["dest_id"].duplicated().any():
        raise ValueError("destination identity mismatch")
    coordinates = refuges[["x", "y"]].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    if (~np.isfinite(coordinates)).any():
        raise ValueError("destination coordinates are invalid")
    distances = np.hypot(coordinates[:, 0] - x, coordinates[:, 1] - y)
    minimum = float(distances.min())
    if int(np.count_nonzero(np.abs(distances - minimum) <= 1e-6)) != 1:
        raise ValueError("unexplained equal-cost destination tie")
    return refuges.iloc[int(np.argmin(distances))]


def _snap(graph: nx.Graph, x: float, y: float) -> Any | None:
    nodes = list(graph.nodes(data=True))
    if not nodes:
        return None
    coordinates = np.array([[item[1]["x"], item[1]["y"]] for item in nodes], dtype=float)
    distance, index = cKDTree(coordinates).query([x, y])
    return nodes[int(index)][0] if distance <= 250.0 else None


def reconstruct_peak_routes(bundle: AuditBundle) -> PeakRoutingAudit:
    """Independently rebuild peak walking routes from the immutable bundle."""
    sample, present, cohort = _derive_populations(bundle)
    _reconstruct_denominators(bundle, sample, present, cohort)
    graph, open_ids, closed_ids = _peak_walk_graph(bundle)
    transformer = Transformer.from_crs(
        "OGC:CRS84", _field(bundle.manifest, "geography", "analysis_crs"), always_xy=True
    )
    refuges = bundle.tables["refuges"]
    routes: dict[str, RouteAudit] = {}
    for person in cohort.itertuples():
        person_id = str(person.person_id)
        x, y = transformer.transform(float(person.lon), float(person.lat))
        destination = _nearest_destination(refuges, x, y)
        if destination is None:
            routes[person_id] = RouteAudit("no_destination", None, None, None, (), None, None)
            continue
        destination_id = str(destination["dest_id"])
        origin_node = _snap(graph, x, y)
        destination_node = _snap(graph, float(destination["x"]), float(destination["y"]))
        if origin_node is None or destination_node is None:
            routes[person_id] = RouteAudit(
                "no_path", destination_id, origin_node, destination_node, (), None, None
            )
            continue
        result = unique_shortest_route(graph, origin_node, destination_node)
        if result is None:
            routes[person_id] = RouteAudit(
                "no_path", destination_id, origin_node, destination_node, (), None, None
            )
            continue
        path, cost = result
        edge_ids = tuple(graph[path[i]][path[i + 1]]["edge_id"] for i in range(len(path) - 1))
        distance = math.fsum(graph[path[i]][path[i + 1]]["length_m"] for i in range(len(path) - 1))
        formula_cost = math.fsum(
            graph[path[i]][path[i + 1]]["length_m"]
            / (graph[path[i]][path[i + 1]]["dry_speed_mps"]
               * graph[path[i]][path[i + 1]]["speed_multiplier"])
            for i in range(len(path) - 1)
        )
        if abs(formula_cost - cost) > 1e-6:
            raise ValueError("unrounded route-cost mismatch")
        routes[person_id] = RouteAudit(
            "routed", destination_id, origin_node, destination_node, edge_ids, cost, distance
        )

    states = bundle.tables["evacuation_states"]
    weights = cohort.set_index(cohort["person_id"].astype(str))["weight"]
    bottleneck: dict[str, float] = {}
    for person_id, route in routes.items():
        saved = states.loc[states["source_person_id"].astype(str) == person_id]
        saved_states = set(saved["state"])
        if saved_states <= {"did_not_depart", "stranded"}:
            continue
        expected_failure = {
            "no_destination": ("no_destination", None),
            "no_path": ("no_path_under_closure", route.destination_id),
        }
        if route.status in expected_failure:
            reason, destination_id = expected_failure[route.status]
            if saved_states != {"route_failed"} or set(saved["reason"]) != {reason}:
                raise ValueError("saved route category mismatch")
            saved_destinations = set(saved["dest_id"].dropna().astype(str))
            if saved_destinations != ({destination_id} if destination_id is not None else set()):
                raise ValueError("saved route destination mismatch")
            continue
        if not saved_states or not saved_states <= {"arrived", "shelter_full"}:
            raise ValueError("saved route category mismatch")
        if set(saved["dest_id"].dropna().astype(str)) != {route.destination_id}:
            raise ValueError("saved route destination mismatch")
        saved_distances = pd.to_numeric(saved["distance_m"], errors="coerce").to_numpy(float)
        if (~np.isfinite(saved_distances)).any() or any(
            abs(value - round(float(route.distance_m), 1)) > 1e-6 for value in saved_distances
        ):
            raise ValueError("saved route distance mismatch")
        if "arrived" in saved_states:
            for edge_id in route.edge_ids:
                bottleneck[edge_id] = bottleneck.get(edge_id, 0.0) + float(weights.loc[person_id])
    top = [
        {"edge_id": edge_id, "traversal_weight": round(weight, 1)}
        for edge_id, weight in sorted(bottleneck.items(), key=lambda item: -item[1])[:10]
    ]
    if top != _field(bundle.stats, "evacuation", "top_bottleneck_edges"):
        raise ValueError("saved route edge identity mismatch")
    return PeakRoutingAudit(routes, open_ids, closed_ids, top)


def integerized_capacity_partition(
    source_weight: float, remaining_capacity: int
) -> tuple[float, float, int]:
    """Apply N=max(round(weight),1) and proportionally split source weight."""
    weight = float(source_weight)
    if (not math.isfinite(weight) or weight <= 0 or type(remaining_capacity) is not int
            or remaining_capacity < 0):
        raise ValueError("invalid source weight or integerized capacity")
    represented = max(int(round(weight)), 1)
    admitted = min(represented, max(remaining_capacity, 0))
    if admitted == 0:
        return 0.0, weight, remaining_capacity
    if admitted == represented:
        return weight, 0.0, remaining_capacity - admitted
    admitted_weight = weight * admitted / represented
    overflow_weight = weight - admitted_weight
    if admitted_weight <= 1e-6:
        return 0.0, weight, remaining_capacity - admitted
    if overflow_weight <= 1e-6:
        return weight, 0.0, remaining_capacity - admitted
    return admitted_weight, overflow_weight, remaining_capacity - admitted


def _compare_terminal_records(actual: pd.DataFrame, saved: pd.DataFrame) -> None:
    required = {
        "person_id", "outcome_id", "source_person_id", "source_weight", "state", "reason",
        "event_time_s", "weight", "dest_id", "clearance_s", "distance_m",
    }
    if not required <= set(saved) or set(saved["state"]) - set(TERMINAL_STATES):
        raise ValueError("saved terminal schema mismatch")
    if actual["outcome_id"].duplicated().any() or saved["outcome_id"].duplicated().any():
        raise ValueError("saved terminal identity mismatch")
    actual_by_id = actual.set_index(actual["outcome_id"].astype(str), drop=False)
    saved_by_id = saved.set_index(saved["outcome_id"].astype(str), drop=False)
    if set(actual_by_id.index) != set(saved_by_id.index):
        raise ValueError("saved terminal identity mismatch")

    def comparable(value: Any) -> Any:
        return None if pd.isna(value) else value

    categorical = ("person_id", "source_person_id", "state", "reason", "dest_id")
    numeric = ("source_weight", "event_time_s", "weight", "clearance_s", "distance_m")
    for outcome_id, expected in actual_by_id.iterrows():
        observed = saved_by_id.loc[outcome_id]
        if any(comparable(expected[key]) != comparable(observed[key]) for key in categorical):
            raise ValueError("saved terminal category mismatch")
        for key in numeric:
            left, right = comparable(expected[key]), comparable(observed[key])
            if (left is None) != (right is None) or (
                left is not None and (
                    not math.isfinite(float(left)) or not math.isfinite(float(right))
                    or abs(float(left) - float(right)) > 1e-6
                )
            ):
                raise ValueError("saved terminal numeric mismatch")


def replay_evacuation(bundle: AuditBundle) -> EvacuationReplayAudit:
    """Replay RNG, integerized capacity and terminal records independently."""
    routing = reconstruct_peak_routes(bundle)
    sample, present, cohort = _derive_populations(bundle)
    departure = _field(bundle.manifest, "evacuation_scenario", "departure_model")
    seed = _field(bundle.manifest, "evacuation_scenario", "seed")
    warning = float(_field(departure, "warning_time_s"))
    warning_reach = float(_field(departure, "warning_reach"))
    compliance = float(_field(departure, "compliance"))
    delay_mean = float(_field(departure, "preparation_delay_mean_s"))
    delay_sd = float(_field(departure, "preparation_delay_sd_s"))
    if warning < 0 or not 0 <= warning_reach <= 1 or not 0 <= compliance <= 1 or delay_sd < 0:
        raise ValueError("invalid departure-model parameter")
    rng = np.random.default_rng(seed)

    refuges = bundle.tables["refuges"]
    capacity: dict[str, int] = {}
    for destination in refuges.itertuples():
        if (not isinstance(destination.capacity, (int, np.integer))
                or isinstance(destination.capacity, bool) or destination.capacity < 0):
            raise ValueError("destination capacity is not an integer")
        capacity[str(destination.dest_id)] = int(destination.capacity)
    remaining = dict(capacity)
    records: list[dict[str, Any]] = []

    def append(person_id: str, state: str, reason: str, event: float, weight: float,
               destination_id: str | None, clearance: float | None,
               distance: float | None) -> None:
        records.append({
            "person_id": person_id, "state": state, "reason": reason,
            "event_time_s": event, "weight": weight, "dest_id": destination_id,
            "clearance_s": clearance, "distance_m": distance,
        })

    for person in cohort.itertuples():
        person_id, weight = str(person.person_id), float(person.weight)
        if rng.random() > warning_reach:
            append(person_id, "did_not_depart", "not_warned", warning, weight, None, None, None)
            continue
        if rng.random() > compliance:
            append(person_id, "did_not_depart", "not_compliant", warning, weight, None, None, None)
            continue
        delay = float(np.clip(rng.normal(delay_mean, delay_sd), 0, 4 * 3600))
        departure_time = warning + delay
        route = routing.routes[person_id]
        if route.status != "routed":
            reason = "no_destination" if route.status == "no_destination" else "no_path_under_closure"
            append(person_id, "route_failed", reason, int(departure_time), weight,
                   route.destination_id, None, None)
            continue
        arrival = departure_time + float(route.cost_s)
        admitted_weight, overflow_weight, remaining_after = integerized_capacity_partition(
            weight, remaining.get(str(route.destination_id), 0)
        )
        remaining[str(route.destination_id)] = remaining_after
        distance = round(float(route.distance_m), 1)
        if admitted_weight == 0:
            append(person_id, "shelter_full", "destination_capacity_exhausted",
                   int(arrival), weight, route.destination_id, None, distance)
            continue
        if overflow_weight > 0:
            append(person_id, "shelter_full", "partial_admission_capacity",
                   int(arrival), overflow_weight, route.destination_id, None, distance)
        append(person_id, "arrived", "admitted", arrival, admitted_weight,
               route.destination_id, arrival - warning, distance)

    columns = [
        "person_id", "state", "reason", "event_time_s", "weight", "dest_id",
        "clearance_s", "distance_m",
    ]
    states = pd.DataFrame.from_records(records, columns=columns)
    source_weights = cohort.set_index(cohort["person_id"].astype(str))["weight"]
    states["source_person_id"] = states["person_id"]
    states["source_weight"] = states["source_person_id"].map(source_weights).astype(float)
    fragment = states.groupby("source_person_id", sort=False).cumcount().astype(str)
    states["outcome_id"] = (
        states["source_person_id"].astype(str) + ":" + states["state"].astype(str) + ":" + fragment
    )
    _compare_terminal_records(states, bundle.tables["evacuation_states"])

    replay_tables = dict(bundle.tables)
    replay_tables["evacuation_states"] = states
    denominators = _reconstruct_denominators(
        replace(bundle, tables=replay_tables), sample, present, cohort
    )
    clearance = inverse_weighted_clearance(states, warning_time_s=warning)
    published = _field(bundle.stats, "evacuation")
    quantities = denominators["quantities"]
    comparisons = {
        "cohort_weighted": quantities["cohort"]["weight"],
        "arrived_weighted": quantities["terminal_states"]["arrived"]["weight"],
        "unserved_weighted": denominators["unserved_derived"]["weight"],
    }
    published_weights = {key: float(published[key]) for key in comparisons}
    if (any(not math.isfinite(value) for value in published_weights.values())
            or any(abs(published_weights[key] - value) > 0.01
                   for key, value in comparisons.items())):
        raise ValueError("published evacuation weight mismatch")
    state_distribution = published.get("state_distribution")
    if not isinstance(state_distribution, dict) or set(state_distribution) != set(TERMINAL_STATES):
        raise ValueError("published terminal distribution mismatch")
    distribution_weights = {key: float(state_distribution[key]) for key in TERMINAL_STATES}
    if (any(not math.isfinite(value) for value in distribution_weights.values())
            or any(abs(distribution_weights[key] - quantities["terminal_states"][key]["weight"]) > 0.01
                   for key in TERMINAL_STATES)):
        raise ValueError("published terminal distribution mismatch")
    for key, value in clearance.items():
        observed = published["clearance_time_minutes"].get(key)
        observed_value = None if observed is None else float(observed)
        if (value is None) != (observed is None) or (
            value is not None and (not math.isfinite(observed_value)
                                   or abs(value - observed_value) > 0.01)
        ):
            raise ValueError("published clearance mismatch")
    destination_summary = published.get("destinations")
    if not isinstance(destination_summary, list):
        raise ValueError("published destination capacity mismatch")
    observed_capacity = {
        str(item["dest_id"]): (item["capacity"], item["remaining"])
        for item in destination_summary if isinstance(item, dict)
    }
    expected_capacity = {key: (capacity[key], remaining[key]) for key in capacity}
    if observed_capacity != expected_capacity:
        raise ValueError("published destination capacity mismatch")
    return EvacuationReplayAudit(states, remaining, denominators, clearance)


def final_audit_report(bundle: AuditBundle) -> dict[str, Any]:
    """Return PASS only after the full independent replay succeeds."""
    base = {
        "run_id": bundle.run_id, "aoi_id": bundle.aoi_id,
        "audited_hashes": dict(sorted(bundle.file_hashes.items())),
    }
    try:
        audit = replay_evacuation(bundle)
    except Exception as exc:
        return {**base, "status": "FAIL", "checks": [
            {"name": "independent_saved_bundle_replay", "status": "FAIL", "detail": str(exc)}
        ]}
    terminal = audit.denominators["quantities"]["terminal_states"]
    return {
        **base, "status": "PASS",
        "checks": [{"name": "independent_saved_bundle_replay", "status": "PASS"}],
        "reconstructed": {
            "terminal_records": len(audit.states),
            "terminal_weights": {key: terminal[key]["weight"] for key in TERMINAL_STATES},
            "remaining_capacity": audit.remaining_capacity,
            "clearance_time_minutes": audit.clearance_time_minutes,
            "conservation": audit.denominators["conservation"],
        },
    }


def audit_saved_run(run_dir: str | Path) -> dict[str, Any]:
    """Load one immutable run and emit a JSON-serializable fail-closed report."""
    try:
        bundle = load_audit_bundle(run_dir)
    except Exception as exc:
        return {"status": "FAIL", "audited_hashes": {}, "checks": [
            {"name": "saved_bundle_integrity", "status": "FAIL", "detail": str(exc)}
        ]}
    return final_audit_report(bundle)
