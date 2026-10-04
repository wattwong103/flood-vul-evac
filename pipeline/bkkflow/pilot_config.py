"""Resolve legacy and named pilot configurations without cross-area fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import read_json


@dataclass(frozen=True)
class PilotBundle:
    pilot: dict[str, Any]
    population: dict[str, Any]
    scenario: dict[str, Any]
    input_root: Path
    versions: dict[str, str]
    sources: dict[str, str]
    named: bool

    @property
    def aoi_id(self) -> str:
        return str(self.pilot["aoi"]["aoi_id"])


def _named_pilot_path(config_dir: Path, pilot_id: str) -> Path:
    if not pilot_id or Path(pilot_id).name != pilot_id:
        raise ValueError(f"Unknown pilot {pilot_id!r}")
    path = config_dir / "pilots" / f"{pilot_id}.json"
    if not path.is_file():
        raise ValueError(f"Unknown pilot {pilot_id!r}")
    return path


def load_pilot_bundle(
    pilot_id: str | None,
    *,
    config_dir: str | Path,
    curated_dir: str | Path,
) -> PilotBundle:
    """Load one effective pilot bundle.

    An omitted identifier preserves the original Khlong San configuration and
    unscoped input layout. Named pilots are isolated under ``pilots/<aoi_id>``
    and may never fall back to those legacy inputs.
    """
    config_dir = Path(config_dir)
    curated_dir = Path(curated_dir)
    named_path = _named_pilot_path(config_dir, pilot_id) if pilot_id is not None else None
    population = read_json(config_dir / "population.json")
    scenario = read_json(config_dir / "scenario.json")

    if pilot_id is None:
        pilot = read_json(config_dir / "pilot.json")
        return PilotBundle(
            pilot=pilot,
            population=population,
            scenario=scenario,
            input_root=curated_dir,
            versions={
                "population": str(population["population_version"]),
                "network": "osm-khlong-san",
                "buildings": "osm-buildings",
            },
            sources={
                "osm": "osm-thailand-geofabrik",
                "population": "worldpop-global2-tha-100m-r2025a",
            },
            named=False,
        )

    pilot = read_json(named_path)
    configured_id = str((pilot.get("aoi") or {}).get("aoi_id", ""))
    input_scope = str(pilot.get("input_scope", ""))
    if configured_id != pilot_id or input_scope != pilot_id:
        raise ValueError(
            f"Pilot configuration {pilot_id!r} does not match "
            f"aoi_id={configured_id!r}, input_scope={input_scope!r}"
        )

    versions = {key: str(value) for key, value in (pilot.get("versions") or {}).items()}
    sources = {key: str(value) for key, value in (pilot.get("sources") or {}).items()}
    for key in ("population", "network", "buildings"):
        if pilot_id not in versions.get(key, ""):
            raise ValueError(f"Pilot {pilot_id!r} has mismatched {key} version")
    for key in ("osm", "population"):
        if not sources.get(key):
            raise ValueError(f"Pilot {pilot_id!r} has no {key} source identity")

    population["population_version"] = versions["population"]
    population["resident_baseline"] = {
        **population.get("resident_baseline", {}),
        "source_id": sources["population"],
        "aoi_id": pilot_id,
    }
    scenario["flood"] = {
        **scenario["flood"],
        "scenario_id": str(pilot["flood_scenario_id"]),
    }
    return PilotBundle(
        pilot=pilot,
        population=population,
        scenario=scenario,
        input_root=curated_dir / "pilots" / pilot_id,
        versions=versions,
        sources=sources,
        named=True,
    )
