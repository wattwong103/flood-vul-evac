"""Run manifest construction and schema validation.

The manifest is the reproducibility contract. If a field is unknown it is
written as an explicit null or an explicit warning, never a plausible default,
because a manifest that guesses cannot be used to audit anything.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .util import REPO_ROOT, read_json, sha256_file, utc_now_iso, write_json

SCHEMA_PATH = REPO_ROOT / "schemas" / "pflow-bkk-run.schema.json"
CONTRACT_VERSION = "pflow-bkk-v0.1"


def new_run_id() -> str:
    return str(uuid.uuid4())


def load_schema() -> dict[str, Any]:
    return read_json(SCHEMA_PATH)


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return a list of schema violations; empty means the manifest conforms."""
    validator = Draft202012Validator(load_schema())
    problems = []
    for error in sorted(validator.iter_errors(manifest), key=lambda e: list(e.path)):
        location = "/".join(str(part) for part in error.path) or "<root>"
        problems.append(f"{location}: {error.message}")
    return problems


def component(name: str, version: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "version": version, "parameters": parameters or {}}


def build_manifest(
    *,
    run_id: str,
    geography: dict[str, Any],
    source_versions: list[dict[str, Any]],
    population_model: dict[str, Any],
    pflow_components: dict[str, Any],
    flood_scenario_entry: dict[str, Any],
    evacuation_scenario_entry: dict[str, Any],
    outputs: list[dict[str, Any]],
    warnings: list[str],
    validation_status: str = "demonstration",
    created_at: str | None = None,
    code_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        **({"code_identity": code_identity} if code_identity is not None else {}),
        "run_id": run_id,
        "created_at": created_at or utc_now_iso(),
        "validation_status": validation_status,
        "geography": geography,
        "source_versions": source_versions,
        "population_model": population_model,
        "pflow_contract": {
            "contract_version": CONTRACT_VERSION,
            "person_generator": pflow_components["person_generator"],
            "activity_generator": pflow_components["activity_generator"],
            "trip_generator": pflow_components["trip_generator"],
            "trajectory_generator": pflow_components["trajectory_generator"],
            "aggregation": pflow_components["aggregation"],
        },
        "flood_scenario": flood_scenario_entry,
        "evacuation_scenario": evacuation_scenario_entry,
        "outputs": outputs,
        "warnings": warnings,
    }


def output_entry(role: str, path: str | Path, *, row_count: int | None = None, crs: str | None = None) -> dict[str, Any]:
    """Describe one artefact, with a checksum so tampering is detectable."""
    target = Path(path)
    entry: dict[str, Any] = {
        "role": role,
        "uri": target.name,
        "content_sha256": sha256_file(target) if target.is_file() else "",
    }
    if row_count is not None:
        entry["row_count"] = int(row_count)
    if crs:
        entry["crs"] = crs
    return entry


def verify_output_integrity(run_dir: str | Path, outputs: list[dict[str, Any]]) -> None:
    """Require unique in-run URIs whose declared hashes match final file bytes."""
    root = Path(run_dir).resolve()
    seen: set[str] = set()
    for entry in outputs:
        uri = entry.get("uri")
        if not isinstance(uri, str) or not uri:
            raise ValueError("Output URI is missing")
        if uri in seen:
            raise ValueError(f"Duplicate output URI: {uri}")
        seen.add(uri)

        relative = Path(uri)
        target = (root / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(root):
            raise ValueError(f"Output URI escapes run directory: {uri}")
        if not target.is_file():
            raise ValueError(f"Output file is missing: {uri}")
        if entry.get("content_sha256") != sha256_file(target):
            raise ValueError(f"Output hash mismatch: {uri}")
