"""Exercise the complete pilot path through its separate publication helper."""
import shutil
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bkkflow import runner
from bkkflow.sources import pilot_stage
from bkkflow.util import read_json, write_json
from test_pipeline import _roads


@pytest.fixture
def pilot_inputs(tmp_path, monkeypatch):
    source_config = Path(__file__).resolve().parents[2] / "config"
    config = tmp_path / "config"
    (config / "pilots").mkdir(parents=True)
    shutil.copyfile(source_config / "population.json", config / "population.json")
    shutil.copyfile(source_config / "scenario.json", config / "scenario.json")
    curated = tmp_path / "curated"
    scoped = curated / "pilots" / "khlong-san-district"
    for directory in ("population", "osm"):
        (scoped / directory).mkdir(parents=True)
    (curated / "aoi").mkdir(parents=True)
    area = gpd.GeoDataFrame(
        {"osm_id": [3147280]},
        geometry=[box(100.4995, 13.7195, 100.5025, 13.7215)],
        crs=4326,
    )
    geometry_hash = pilot_stage.geometry_sha256(area.geometry.iloc[0])
    pilot = read_json(source_config / "pilots/khlong-san-district.json")
    pilot["aoi"]["area_km2"] = round(
        float(area.to_crs(pilot["analysis_crs"]).geometry.area.iloc[0]) / 1e6, 4
    )
    pilot["source_sha256"] = {
        "osm": "1" * 64, "population": "1" * 64, "geometry": geometry_hash,
    }
    write_json(config / "pilots/khlong-san-district.json", pilot)
    area.to_parquet(scoped / "aoi.parquet", index=False)
    cells = gpd.GeoDataFrame({
        "cell_id": ["one", "two"], "population_version": ["test"] * 2,
        "pop_count": [100.0, 200.0], "area_m2": [10000.0] * 2,
        "pop_density_per_m2": [0.01, 0.02],
        "lon": [100.500, 100.501], "lat": [13.720, 13.721],
    }, geometry=[box(100.4999, 13.7199, 100.5001, 13.7201),
                 box(100.5009, 13.7209, 100.5011, 13.7211)], crs=4326)
    cells["population_version"] = "bkk-pop-v0.2-khlong-san-district-2020"
    cells.to_parquet(scoped / "population/population_cells.parquet")
    _roads().to_parquet(scoped / "osm/roads.parquet")
    buildings = gpd.GeoDataFrame({
        "osm_id": [101, 102, 103], "building": ["house"] * 3,
        "height": [10.0] * 3, "building:levels": [None] * 3,
    }, geometry=[box(x, 13.7201, x + .0001, 13.7202)
                 for x in (100.500, 100.501, 100.502)], crs=4326)
    buildings.to_parquet(scoped / "osm/buildings.parquet")
    water = gpd.GeoDataFrame({"water_kind": ["canal"]},
        geometry=[LineString([(100.4996, 13.7195), (100.4996, 13.7215)])], crs=4326)
    water.to_parquet(scoped / "osm/water.parquet")
    fetch = {"retrieved_at": "2026-10-04T00:00:00+00:00",
             "content_sha256": "1" * 64, "query_sha256": "2" * 64}
    write_json(scoped / "osm/provenance.json", {
        "aoi_id": "khlong-san-district",
        "source_id": "geofabrik-thailand-osm-20260929",
        "retrieved_at": fetch["retrieved_at"],
        "content_sha256": fetch["content_sha256"],
        "layers": {"roads": {}, "buildings": {}, "water": {}},
        "fetches": [fetch] * 3,
    })
    write_json(scoped / "population/provenance.json", {
        **fetch,
        "aoi_id": "khlong-san-district",
        "source_id": "worldpop-global-2000-2020-tha-100m",
        "population_version": "bkk-pop-v0.2-khlong-san-district-2020",
        "resource_url": "https://data.worldpop.org/example.tif",
    })
    write_json(scoped / "aoi.provenance.json", {
        **fetch, "aoi_id": "khlong-san-district", "osm_id": 3147280,
        "source_id": "geofabrik-thailand-osm-20260929", "geometry_sha256": geometry_hash,
    })
    clip = scoped / "population/source_clip.tif"
    with rasterio.open(clip, "w", driver="GTiff", width=1, height=1, count=1,
                       dtype="float32", crs="EPSG:4326",
                       transform=from_origin(100.5, 13.72, .001, .001)) as dst:
        dst.write(np.array([[1]], dtype="float32"), 1)
    outputs = {
        "aoi": pilot_stage._output(scoped, scoped / "aoi.parquet", rows=1,
                                   crs=area.crs.to_string(), kind="geoparquet"),
        "aoi_provenance": pilot_stage._output(scoped, scoped / "aoi.provenance.json",
                                              rows=None, crs=None, kind="json"),
        "roads": pilot_stage._output(scoped, scoped / "osm/roads.parquet", rows=4,
                                     crs="OGC:CRS84", kind="geoparquet"),
        "buildings": pilot_stage._output(scoped, scoped / "osm/buildings.parquet", rows=3,
                                         crs="EPSG:4326", kind="geoparquet"),
        "water": pilot_stage._output(scoped, scoped / "osm/water.parquet", rows=1,
                                     crs="EPSG:4326", kind="geoparquet"),
        "osm_provenance": pilot_stage._output(scoped, scoped / "osm/provenance.json",
                                              rows=None, crs=None, kind="json"),
        "population_clip": pilot_stage._output(scoped, clip, rows=None, crs=None, kind="raster"),
        "population_cells": pilot_stage._output(
            scoped, scoped / "population/population_cells.parquet", rows=2,
            crs="EPSG:4326", kind="geoparquet"),
        "population_provenance": pilot_stage._output(
            scoped, scoped / "population/provenance.json", rows=None, crs=None, kind="json"),
    }
    write_json(scoped / "stage_manifest.json", {
        "state": "complete", "aoi_id": "khlong-san-district",
        "sources": {"osm": "geofabrik-thailand-osm-20260929",
                    "population": "worldpop-global-2000-2020-tha-100m"},
        "source_sha256": pilot["source_sha256"],
        "analysis_crs": "EPSG:32647",
        "inputs": {
            "osm": {"source_id": "geofabrik-thailand-osm-20260929",
                    "content_sha256": "1" * 64, "retrieved_at": fetch["retrieved_at"],
                    "resource_url": "https://example.test/osm",
                    "coverage_sha256": "4" * 64,
                    "cached_layer_sha256": {"roads": "5" * 64,
                                             "buildings": "6" * 64,
                                             "water_lines": "7" * 64}},
            "population": {"source_id": "worldpop-global-2000-2020-tha-100m",
                           "content_sha256": "1" * 64, "retrieved_at": fetch["retrieved_at"],
                           "resource_url": "https://data.worldpop.org/example.tif"},
        },
        "geometry": {"osm_relation_id": 3147280, "content_sha256": geometry_hash,
                     "source_crs": "EPSG:4326", "analysis_crs": "EPSG:32647",
                     "area_km2": pilot["aoi"]["area_km2"]},
        "outputs": outputs,
    })
    monkeypatch.setattr(runner, "CONFIG_DIR", config)
    monkeypatch.setattr(runner, "CURATED_DIR", curated)
    monkeypatch.setattr(runner, "RUNS_DIR", tmp_path / "runs")
    return tmp_path / "runs"


@pytest.mark.parametrize("flood_enabled", [False, True])
def test_pilot_publishes_verified_source_identity(pilot_inputs, flood_enabled):
    result = runner.execute_run(
        pilot_id="khlong-san-district", flood_enabled=flood_enabled, max_agents=10
    )
    run = Path(result["run_dir"])
    assert result["validation_passed"]
    assert read_json(run / "run_state.json")["state"] == "published"
    manifest = read_json(run / "manifest.json")
    assert manifest["code_identity"]["verification"] == "matched_before_publication"
    assert len(manifest["code_identity"]["source_sha256"]) == 64
    assert {source["source_id"] for source in manifest["source_versions"]} == {
        "geofabrik-thailand-osm-20260929",
        "worldpop-global-2000-2020-tha-100m",
    }
    assert manifest["geography"]["aoi_id"] == "khlong-san-district"
    assert manifest["population_model"]["population_version"] == (
        "bkk-pop-v0.2-khlong-san-district-2020"
    )
    assert manifest["population_model"]["seed"] == 29092026
    activity_parameters = manifest["pflow_contract"]["activity_generator"]["parameters"]
    assert activity_parameters["sample_cap"] == 10
    assert 0 < activity_parameters["sampled_agents"] <= activity_parameters["sample_cap"]
    assert manifest["flood_scenario"]["parameters"]["scenario_id"] == (
        "bangkok-moderate-distance-to-water"
    )
    assert manifest["evacuation_scenario"]["seed"] == 29092026
    active_scenario = {
        "state": "moderate" if flood_enabled else "dry",
        "configured_scenario_id": "bangkok-moderate-distance-to-water",
    }
    assert manifest["active_scenario"] == active_scenario
    assert read_json(run / "run_state.json")["active_scenario"] == active_scenario
    assert all(len(source["content_sha256"]) == 64 for source in manifest["source_versions"])
    assert runner.manifest_module.validate_manifest(manifest) == []


@pytest.mark.parametrize("flood_enabled", [None, 0, 1, "moderate"])
def test_pilot_requires_explicit_boolean_flood_state(flood_enabled):
    with pytest.raises(ValueError, match="explicitly select dry or moderate"):
        runner.execute_run(
            pilot_id="khlong-san-district",
            flood_enabled=flood_enabled,
            max_agents=1,
        )


def test_pilot_pair_reuses_saved_fixed_cohort_and_rejects_mismatch(pilot_inputs):
    dry = runner.execute_run(
        run_id="pair-dry", pilot_id="khlong-san-district",
        flood_enabled=False, max_agents=10)
    wet = runner.execute_run(
        run_id="pair-wet", pilot_id="khlong-san-district",
        flood_enabled=True, max_agents=10, cohort_from_run="pair-dry")
    dry_dir, wet_dir = Path(dry["run_dir"]), Path(wet["run_dir"])
    dry_cohort = pd.read_parquet(dry_dir / "cohort.parquet")
    wet_cohort = pd.read_parquet(wet_dir / "cohort.parquet")
    identity = ["person_id", "order_id", "weight", "sampling_probability"]
    pd.testing.assert_frame_equal(dry_cohort[identity], wet_cohort[identity])
    dry_meta = read_json(dry_dir / "cohort_metadata.json")
    wet_meta = read_json(wet_dir / "cohort_metadata.json")
    dry_den = read_json(dry_dir / "denominators.json")
    wet_den = read_json(wet_dir / "denominators.json")
    assert dry_meta["cohort_digest"] == wet_meta["cohort_digest"]
    assert (dry_meta["seed"], dry_meta["max_agents"]) == (29092026, 10)
    assert dry_meta["order_geometry_rule"] and dry_meta["presence_rule"]
    assert "start_time_s <=" in dry_meta["presence_rule"]
    assert "stored person/home" in dry_meta["presence_rule"]
    assert dry_meta["sample_rule"] and dry_meta["sample_digest"]
    assert wet_meta["reference_run_id"] == "pair-dry"
    assert dry_meta["exposed_weighted"] == 0.0 and not dry_cohort["exposed"].any()
    assert dry_den["pairing"]["denominator_assignment"] == wet_den["pairing"]["denominator_assignment"]
    assert dry_den["quantities"]["exposed_present"]["weight"] == 0.0
    assert dry_den == read_json(dry_dir / "stats.json")["denominators"]
    reference_bytes = (dry_dir / "cohort_metadata.json").read_bytes()
    with pytest.raises(ValueError, match="cohort mismatch"):
        runner.execute_run(
            run_id="pair-bad", pilot_id="khlong-san-district",
            flood_enabled=True, max_agents=1, cohort_from_run="pair-dry")
    assert (dry_dir / "cohort_metadata.json").read_bytes() == reference_bytes


def test_pilot_persists_full_and_sample_without_reweighting(pilot_inputs):
    result = runner.execute_run(
        run_id="sample-one", pilot_id="khlong-san-district",
        flood_enabled=False, max_agents=1)
    run_dir = Path(result["run_dir"])
    contract = read_json(run_dir / "denominators.json")
    full = contract["quantities"]["full_population"]
    sample = contract["quantities"]["sample"]
    assert full["rows"] == 4 and sample["rows"] == 1
    assert full["weight"] != sample["weight"]
    assert contract["scope"]["reweighting_to_full_population"] is False
    manifest = read_json(run_dir / "manifest.json")
    assert any(output["role"] == "denominators" for output in manifest["outputs"])


@pytest.mark.parametrize(("reference_id", "payload"), [
    ("null-reference", None),
    ("array-reference", []),
    ("incomplete-reference", {"run_id": "incomplete-reference"}),
])
def test_pilot_pair_rejects_invalid_reference_before_run_creation(
    pilot_inputs, reference_id, payload
):
    reference_dir = pilot_inputs / reference_id
    reference_dir.mkdir(parents=True)
    write_json(reference_dir / "cohort_metadata.json", payload)
    rejected_dir = pilot_inputs / f"rejected-{reference_id}"
    with pytest.raises(ValueError, match="cohort reference metadata"):
        runner.execute_run(
            run_id=rejected_dir.name, pilot_id="khlong-san-district",
            flood_enabled=True, max_agents=10, cohort_from_run=reference_id)
    assert not rejected_dir.exists()


def test_flooded_pilot_routes_with_peak_speed_multipliers(pilot_inputs, monkeypatch):
    captured = []
    build_graph = runner.mobility_module.build_routing_graph

    def capture_graph(edges, mode, **kwargs):
        multipliers = kwargs.get("speed_multipliers")
        if multipliers is not None:
            captured.append(dict(multipliers))
        return build_graph(edges, mode, **kwargs)

    monkeypatch.setattr(runner.mobility_module, "build_routing_graph", capture_graph)

    result = runner.execute_run(
        pilot_id="khlong-san-district", flood_enabled=True, max_agents=10
    )

    run = Path(result["run_dir"])
    states = pd.read_parquet(run / "edge_states.parquet")
    manifest = read_json(run / "manifest.json")
    peak_time = manifest["flood_scenario"]["parameters"]["peak_time_s"]
    peak_walk = states[(states["time_s"] == peak_time) & (states["mode"] == 0)]
    expected = dict(zip(peak_walk["edge_id"], peak_walk["speed_multiplier"]))

    assert captured == [expected]
    assert all(0.0 <= value <= 1.0 for value in captured[0].values())


def test_named_pilot_rejects_mismatched_scoped_provenance(pilot_inputs):
    provenance = pilot_inputs.parent / "curated/pilots/khlong-san-district/osm/provenance.json"
    payload = read_json(provenance)
    payload["aoi_id"] = "sai-mai-district"
    write_json(provenance, payload)

    with pytest.raises(ValueError, match="staged provenance AOI mismatch"):
        runner.execute_run(pilot_id="khlong-san-district", max_agents=10)


def test_named_pilot_rejects_tampered_stage_before_run(pilot_inputs):
    roads = pilot_inputs.parent / "curated/pilots/khlong-san-district/osm/roads.parquet"
    roads.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Staged output changed"):
        runner.execute_run(pilot_id="khlong-san-district", max_agents=10)
    assert not pilot_inputs.exists()


def test_output_integrity_failure_blocks_manifest_publication(pilot_inputs, monkeypatch):
    def fail_publication(*_args, **_kwargs):
        raise ValueError("final output integrity failed")

    monkeypatch.setattr(runner.manifest_module, "verify_output_integrity", fail_publication)
    with pytest.raises(ValueError, match="final output integrity failed"):
        runner.execute_run(pilot_id="khlong-san-district", max_agents=10)

    run_dirs = list(pilot_inputs.iterdir())
    assert len(run_dirs) == 1
    assert not (run_dirs[0] / "manifest.json").exists()
    assert read_json(run_dirs[0] / "run_state.json")["state"] != "published"


def test_schema_failure_blocks_manifest_publication(pilot_inputs, monkeypatch):
    monkeypatch.setattr(
        runner.manifest_module,
        "validate_manifest",
        lambda _manifest: ["outputs/0: broken schema"],
    )
    with pytest.raises(ValueError, match="Manifest schema validation failed"):
        runner.execute_run(pilot_id="khlong-san-district", max_agents=10)

    run_dirs = list(pilot_inputs.iterdir())
    assert len(run_dirs) == 1
    assert not (run_dirs[0] / "manifest.json").exists()
    assert read_json(run_dirs[0] / "run_state.json")["state"] != "published"


@pytest.mark.parametrize("check_number", [1, 2])
def test_pilot_drift_at_either_publication_check_stays_failed(pilot_inputs, monkeypatch, check_number):
    verify = runner.verify_code_identity
    checks = 0

    def drift(before, run_dir):
        nonlocal checks
        checks += 1
        if checks == check_number:
            before = {**before, "source_sha256": "0" * 64}
        return verify(before, run_dir)

    monkeypatch.setattr(runner, "verify_code_identity", drift)
    with pytest.raises(RuntimeError, match="Source changed"):
        runner.execute_run(pilot_id="khlong-san-district", max_agents=10)
    run = next(pilot_inputs.iterdir())
    assert read_json(run / "run_state.json")["state"] == "failed_source_changed"
    assert (run / "manifest.json").exists() == (check_number == 2)
