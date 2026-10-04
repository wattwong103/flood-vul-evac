"""Stage one named pilot from the verified regional OSM and WorldPop sources."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import shapely

from .. import population as population_module
from ..pilot_config import PilotBundle, load_pilot_bundle
from ..provenance import verify_source
from ..util import (
    CURATED_DIR,
    REPO_ROOT,
    STAGED_DIR,
    read_json,
    sha256_file,
    stable_hash,
    write_json,
)
from . import city_osm, population_source
from .registry import load_registry

CONFIG_DIR = REPO_ROOT / "config"
CITY_DIR = CURATED_DIR / "city"
PBF_PATH = STAGED_DIR / "osm" / "thailand-260929.osm.pbf"
COVERAGE_PATH = STAGED_DIR / "osm" / "thailand.poly"
POPULATION_PATH = STAGED_DIR / "population" / "tha_ppp_2020.tif"


def geometry_sha256(geometry) -> str:
    """Hash normalized two-dimensional little-endian WKB."""
    payload = shapely.to_wkb(
        shapely.normalize(geometry), byte_order=1, output_dimension=2
    )
    return hashlib.sha256(payload).hexdigest()


def _read_boundary(source: Path, bundle: PilotBundle) -> gpd.GeoDataFrame:
    import pyogrio

    relation_id = int(bundle.pilot["aoi"]["osm_relation_id"])
    frame = pyogrio.read_dataframe(
        source,
        layer="multipolygons",
        use_arrow=True,
        columns=["osm_id", "name", "admin_level", "boundary", "other_tags"],
        where=(
            f"osm_id = '{relation_id}' AND boundary = 'administrative' "
            "AND admin_level = '6'"
        ),
    )
    matches = frame[
        (frame["osm_id"].astype(str).str.lstrip("-") == str(relation_id))
        & (frame["boundary"].astype(str) == "administrative")
        & (frame["admin_level"].astype(str) == "6")
    ].copy()
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one boundary for OSM relation R{relation_id}")
    if matches.crs is None or matches.crs.to_epsg() != 4326:
        raise ValueError("Pilot boundary must declare EPSG:4326")
    geometry = matches.geometry.iloc[0]
    parts = len(geometry.geoms) if geometry.geom_type == "MultiPolygon" else 1
    if geometry.geom_type not in {"Polygon", "MultiPolygon"} or parts != 1:
        raise ValueError("Pilot boundary must be one polygon part")
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError("Pilot boundary must be nonempty and valid")

    measured = float(matches.to_crs(bundle.pilot["analysis_crs"]).geometry.area.iloc[0]) / 1e6
    expected = float(bundle.pilot["aoi"]["area_km2"])
    if round(measured, 4) != round(expected, 4):
        raise ValueError(f"Pilot boundary area mismatch: {measured:.4f} != {expected:.4f} km2")
    digest = geometry_sha256(geometry)
    if digest != bundle.pilot["source_sha256"]["geometry"]:
        raise ValueError("Pilot boundary geometry hash mismatch")

    return gpd.GeoDataFrame(
        [{
            "aoi_id": bundle.aoi_id,
            "name": bundle.pilot["aoi"]["name"],
            "name_en": bundle.pilot["aoi"]["name_en"],
            "admin_level": "6",
            "osm_type": "relation",
            "osm_id": relation_id,
        }],
        geometry=[geometry],
        crs="EPSG:4326",
    )


def _output(root: Path, path: Path, *, rows: int | None, crs: str | None, kind: str) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "rows": rows,
        "crs": crs,
        "kind": kind,
    }


def _scope_layer(source: gpd.GeoDataFrame, geometry) -> tuple[gpd.GeoDataFrame, dict[str, int]]:
    """Select intersecting source features, repairing only the predicate copy."""
    null = source.geometry.isna()
    empty = source.geometry.is_empty.fillna(False)
    invalid = (~source.geometry.is_valid).fillna(False) & ~null & ~empty
    predicate_geometry = source.geometry.copy()
    if invalid.any():
        predicate_geometry.loc[invalid] = predicate_geometry.loc[invalid].make_valid()
    selected = predicate_geometry.intersects(geometry).fillna(False)
    return source.loc[selected].copy(), {
        "source_rows": int(len(source)),
        "null_geometry": int(null.sum()),
        "empty_geometry": int(empty.sum()),
        "invalid_geometry": int(invalid.sum()),
        "predicate_repairs": int(invalid.sum()),
        "selected_rows": int(selected.sum()),
    }


def _require_provenance(path: Path, fields: tuple[str, ...]) -> dict[str, Any]:
    try:
        payload = read_json(path)
    except (OSError, ValueError) as error:
        raise ValueError(f"Incomplete staged provenance: {path.name}") from error
    missing = [field for field in fields if payload.get(field) in (None, "")]
    if missing:
        raise ValueError(f"Incomplete staged provenance: {path.name} lacks {', '.join(missing)}")
    return payload


def validate_staged_pilot(
    root: str | Path,
    *,
    expected_aoi_id: str | None = None,
    expected_bundle: PilotBundle | None = None,
) -> dict[str, Any]:
    """Reopen and hash-check the complete-stage sentinel before any named run."""
    root = Path(root)
    manifest_path = root / "stage_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"Named pilot stage is incomplete: {manifest_path}")
    manifest = read_json(manifest_path)
    if manifest.get("state") != "complete":
        raise ValueError("Named pilot stage is not complete")
    expected_aoi_id = expected_bundle.aoi_id if expected_bundle else expected_aoi_id
    if expected_aoi_id and manifest.get("aoi_id") != expected_aoi_id:
        raise ValueError("Named pilot stage AOI identity mismatch")
    if expected_bundle:
        if manifest.get("sources") != expected_bundle.sources:
            raise ValueError("Named pilot stage source identity mismatch")
        if manifest.get("source_sha256") != expected_bundle.pilot.get("source_sha256"):
            raise ValueError("Named pilot stage source hash mismatch")
        if manifest.get("analysis_crs") != expected_bundle.pilot.get("analysis_crs"):
            raise ValueError("Named pilot stage analysis CRS mismatch")

    aoi_provenance = _require_provenance(
        root / "aoi.provenance.json",
        ("aoi_id", "source_id", "retrieved_at", "content_sha256", "osm_id", "geometry_sha256"),
    )
    osm_provenance = _require_provenance(
        root / "osm/provenance.json",
        ("aoi_id", "source_id", "retrieved_at", "content_sha256", "fetches", "layers"),
    )
    population_provenance = _require_provenance(
        root / "population/provenance.json",
        ("aoi_id", "source_id", "retrieved_at", "content_sha256", "population_version", "resource_url"),
    )
    if any(payload.get("aoi_id") != manifest.get("aoi_id")
           for payload in (aoi_provenance, osm_provenance, population_provenance)):
        raise ValueError("Named pilot staged provenance AOI mismatch")
    inputs = manifest.get("inputs") or {}
    if set(inputs) != {"osm", "population"}:
        raise ValueError("Named pilot stage input inventory is incomplete")
    for source in inputs.values():
        missing = [key for key in ("source_id", "content_sha256", "retrieved_at", "resource_url")
                   if source.get(key) in (None, "")]
        if missing:
            raise ValueError("Named pilot stage input provenance is incomplete")
    sources = manifest.get("sources") or {}
    source_sha256 = manifest.get("source_sha256") or {}
    if sources != {key: inputs[key]["source_id"] for key in inputs}:
        raise ValueError("Named pilot stage source identity is inconsistent")
    if source_sha256.get("osm") != inputs["osm"]["content_sha256"] or source_sha256.get(
        "population"
    ) != inputs["population"]["content_sha256"]:
        raise ValueError("Named pilot stage source hashes are inconsistent")
    cached_layers = inputs["osm"].get("cached_layer_sha256") or {}
    if set(cached_layers) != {"roads", "buildings", "water_lines"} or not all(
        isinstance(value, str) and len(value) == 64 for value in cached_layers.values()
    ):
        raise ValueError("Named pilot stage cached-layer inventory is incomplete")
    if not isinstance(inputs["osm"].get("coverage_sha256"), str) or len(
        inputs["osm"]["coverage_sha256"]
    ) != 64:
        raise ValueError("Named pilot stage coverage identity is incomplete")
    if any(
        payload.get("source_id") != inputs[key]["source_id"]
        or payload.get("content_sha256") != inputs[key]["content_sha256"]
        or payload.get("retrieved_at") != inputs[key]["retrieved_at"]
        for key, payload in (
            ("osm", aoi_provenance),
            ("osm", osm_provenance),
            ("population", population_provenance),
        )
    ):
        raise ValueError("Named pilot staged provenance source mismatch")

    geometry = manifest.get("geometry") or {}
    required_geometry = {
        "osm_relation_id", "content_sha256", "source_crs", "analysis_crs", "area_km2"
    }
    if set(geometry) != required_geometry:
        raise ValueError("Named pilot stage geometry identity is incomplete")
    if (
        geometry["content_sha256"] != source_sha256.get("geometry")
        or geometry["content_sha256"] != aoi_provenance["geometry_sha256"]
        or int(geometry["osm_relation_id"]) != int(aoi_provenance["osm_id"])
        or geometry["analysis_crs"] != manifest.get("analysis_crs")
        or geometry["source_crs"] != "EPSG:4326"
    ):
        raise ValueError("Named pilot stage geometry identity is inconsistent")
    if expected_bundle:
        expected_geometry = expected_bundle.pilot["aoi"]
        if (
            int(geometry["osm_relation_id"]) != int(expected_geometry["osm_relation_id"])
            or round(float(geometry["area_km2"]), 4)
            != round(float(expected_geometry["area_km2"]), 4)
        ):
            raise ValueError("Named pilot stage geometry does not match configuration")

    outputs = manifest.get("outputs") or {}
    required = {
        "aoi", "aoi_provenance", "roads", "buildings", "water", "osm_provenance",
        "population_clip", "population_cells", "population_provenance",
    }
    if set(outputs) != required:
        raise ValueError("Named pilot stage output inventory is incomplete")
    for role, record in outputs.items():
        relative_path = Path(record["path"])
        path = (root / relative_path).resolve()
        if relative_path.is_absolute() or not path.is_relative_to(root.resolve()):
            raise ValueError(f"Staged output path escapes pilot root: {role}")
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            raise ValueError(f"Staged output changed: {role}")
        if record["kind"] == "geoparquet":
            frame = gpd.read_parquet(path)
            if len(frame) != record["rows"] or frame.crs is None:
                raise ValueError(f"Staged output failed reopen check: {role}")
            if record.get("crs") and frame.crs.to_string() != record["crs"]:
                raise ValueError(f"Staged output CRS changed: {role}")
        elif record["kind"] == "raster":
            import rasterio

            with rasterio.open(path) as dataset:
                if dataset.width <= 0 or dataset.height <= 0 or dataset.crs is None:
                    raise ValueError(f"Staged output failed reopen check: {role}")
    aoi = gpd.read_parquet(root / outputs["aoi"]["path"])
    if (
        len(aoi) != 1
        or aoi.crs is None
        or aoi.crs.to_epsg() != 4326
        or int(aoi.iloc[0]["osm_id"]) != int(geometry["osm_relation_id"])
        or geometry_sha256(aoi.geometry.iloc[0]) != geometry["content_sha256"]
    ):
        raise ValueError("Named pilot staged AOI geometry mismatch")
    return manifest


def _verify_inputs(
    bundle: PilotBundle,
    *,
    city_dir: Path,
    pbf_path: Path,
    coverage_path: Path,
    population_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], gpd.GeoDataFrame, dict[str, Any]]:
    registry = load_registry()
    sources = {
        source.source_id: source
        for source in registry.require_approved([bundle.sources["osm"], bundle.sources["population"]])
    }
    city_record = read_json(city_dir / "provenance.json")
    if city_record.get("source_id") != bundle.sources["osm"]:
        raise ValueError("City cache OSM source identity mismatch")
    osm_meta = city_osm.source_provenance(pbf_path, sources[bundle.sources["osm"]].resource_url)
    expected = bundle.pilot.get("source_sha256") or {}
    if osm_meta["content_sha256"] != expected.get("osm"):
        raise ValueError("Configured OSM source hash mismatch")
    if city_record.get("content_sha256") != osm_meta["content_sha256"]:
        raise ValueError("City cache OSM source hash mismatch")
    for name, record in (city_record.get("layers") or {}).items():
        path = city_dir / f"{name}.parquet"
        if not path.is_file() or sha256_file(path) != record.get("sha256"):
            raise ValueError(f"City cached {name} changed")

    population_meta = verify_source(
        population_path, sources[bundle.sources["population"]].resource_url
    )
    if population_meta["content_sha256"] != expected.get("population"):
        raise ValueError("Configured population source hash mismatch")

    aoi = _read_boundary(pbf_path, bundle)
    coverage = city_osm.source_coverage(coverage_path, aoi)
    if coverage["sha256"] != (city_record.get("coverage") or {}).get("sha256"):
        raise ValueError("OSM coverage polygon hash mismatch")
    return city_record, osm_meta, aoi, population_meta

