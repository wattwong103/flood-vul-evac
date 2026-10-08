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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

REQUIRED_ROLES = (
    "persons", "activities", "network_edges", "flood_slices", "edge_states",
    "cohort", "cohort_metadata", "refuges", "denominators", "evacuation_states",
)
TABLE_ROLES = tuple(role for role in REQUIRED_ROLES
                    if role not in {"cohort_metadata", "denominators"})
DENOMINATOR_CONTRACT_VERSION = "sample-denominators-v1"
PFLOW_CONTRACT_VERSION = "pflow-bkk-v0.1"


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
