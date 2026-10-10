"""Exercise the complete pilot path through its separate publication helper."""
import math
import re
import shutil
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# The repo root hosts the `api` package and there is no root conftest.py or pytest config,
# so add it explicitly. Without this, collection fails for every test in this file under a
# bare `pytest` invocation (or any cwd other than the repo root).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from api.app import create_app
from bkkflow import runner
from bkkflow.sources import pilot_stage
from bkkflow.util import read_json, write_json
from test_pipeline import _roads


def _write_synthetic_age_rasters(directory: Path, *, size: int = 8) -> Path:
    """Write a stand-in WorldPop age-band raster set covering the pilot AOI.

    Mirrors the real layout (one file per band, 3-arc EPSG:4326, nodata
    -99999) at the real filenames, so the production loader is exercised
    unchanged. Bands vary with position so per-cell shares genuinely differ;
    a flat or multiplicative grid would keep the band ratio constant and make
    every cell look identical.
    """
    from bkkflow.sources import population_age

    directory.mkdir(parents=True, exist_ok=True)
    transform = from_origin(100.4990, 13.7220, 0.0008333, 0.0008333)
    rows, cols = np.mgrid[0:size, 0:size]
    # Two bands carry real structure; the rest are empty but must exist.
    arrays = {
        "05": (40.0 + rows * 2.0).astype("float32"),
        "30": (100.0 + cols * 5.0).astype("float32"),
        "65": (10.0 + rows).astype("float32"),
    }
    for code in population_age.BAND_CODES:
        data = arrays.get(code, np.zeros((size, size), dtype="float32"))
        path = directory / f"tha_t_{code}_2026_CN_100m_R2025A_v1.tif"
        with rasterio.open(
            path, "w", driver="GTiff", height=size, width=size, count=1,
            dtype="float32", crs="EPSG:4326", transform=transform, nodata=-99999.0,
        ) as dst:
            dst.write(data, 1)
    return directory


@pytest.fixture
def pilot_inputs(tmp_path, monkeypatch):
    source_config = Path(__file__).resolve().parents[2] / "config"
    config = tmp_path / "config"
    (config / "pilots").mkdir(parents=True)
    shutil.copyfile(source_config / "population.json", config / "population.json")
    shutil.copyfile(source_config / "scenario.json", config / "scenario.json")
    # The shipped config enables per-cell age structure and points at the real
    # 2.5 GB acquisition under data/staged/, which is deliberately git-ignored.
    # Tests must not depend on that download, so synthesise a stand-in band set
    # and repoint the copied config at it.
    age_dir = _write_synthetic_age_rasters(tmp_path / "agesex")
    population_config = read_json(config / "population.json")
    population_config["age_structure"]["raster_dir"] = str(age_dir)
    write_json(config / "population.json", population_config)
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
        "source_id": "geofabrik-thailand-osm-20261009",
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
        "source_id": "geofabrik-thailand-osm-20261009", "geometry_sha256": geometry_hash,
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
        "sources": {"osm": "geofabrik-thailand-osm-20261009",
                    "population": "worldpop-global-2000-2020-tha-100m"},
        "source_sha256": pilot["source_sha256"],
        "analysis_crs": "EPSG:32647",
        "inputs": {
            "osm": {"source_id": "geofabrik-thailand-osm-20261009",
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
        "geofabrik-thailand-osm-20261009",
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


def _weighted_quantiles_minutes(clearances, weights) -> dict[str, float]:
    """Independent inverse weighted-ECDF, deliberately not the production helper."""
    ordered = sorted(zip(clearances, weights))
    total = math.fsum(float(weight) for _, weight in ordered)
    result = {}
    for label, quantile in (("p5", 0.05), ("median", 0.50), ("p95", 0.95)):
        cumulative = 0.0
        for clearance, weight in ordered:
            cumulative += float(weight)
            if cumulative >= quantile * total:
                result[label] = clearance / 60.0
                break
        assert label in result
    return result


def test_pilot_saved_fractional_clearance_round_trips_through_both_api_routes(
    pilot_inputs, monkeypatch
):
    """Fractional seconds and unequal weights must survive the API readback.

    The clearances are derived from the run's own cohort rather than pinned, so
    the test survives a population change. What it must still guarantee is the
    discriminating property: the weighted median has to differ from the
    unweighted one, otherwise an implementation ignoring weights would pass.
    """
    emitted: dict[str, list[float]] = {}

    def fractional_evacuation(cohort, *, destinations, route_lookup, scenario, seed):
        # Heaviest person gets the shortest clearance. Sorting by weight first
        # guarantees the weighted median lands earlier than the unweighted one
        # while leaving the cohort total untouched -- the total-weight
        # conservation the denominator contract depends on still holds.
        ordered = cohort.sort_values(
            "weight", ascending=False, kind="stable"
        ).reset_index(drop=True)
        clearance_s = [60.25 + index * 17.0 for index in range(len(ordered))]
        emitted["clearance_s"] = list(clearance_s)
        emitted["weights"] = [float(value) for value in ordered["weight"]]
        destination_id = str(destinations.iloc[0]["dest_id"])
        states = pd.DataFrame(
            {
                "person_id": ordered["person_id"],
                "outcome_id": ordered["person_id"].astype(str) + ":arrived:0",
                "source_person_id": ordered["person_id"],
                "source_weight": ordered["weight"],
                "state": "arrived",
                "reason": "admitted",
                "event_time_s": [scenario.warning_time_s + value for value in clearance_s],
                "weight": ordered["weight"],
                "dest_id": destination_id,
                "clearance_s": clearance_s,
                "distance_m": 100.0,
            }
        )
        total_weight = float(states["weight"].sum())
        return states, {
            "cohort_weighted": total_weight,
            "state_distribution": {"arrived": total_weight},
            "arrived_weighted": total_weight,
            "unserved_weighted": 0.0,
            "clearance_time_minutes": _weighted_quantiles_minutes(
                clearance_s, emitted["weights"]
            ),
            "top_bottleneck_edges": [],
            "destinations": [],
        }

    monkeypatch.setattr(
        runner.evacuation_module, "simulate_evacuation", fractional_evacuation
    )
    result = runner.execute_run(
        run_id="fractional-api",
        pilot_id="khlong-san-district",
        flood_enabled=False,
        max_agents=10,
    )
    run_dir = Path(result["run_dir"])
    persisted = pd.read_parquet(run_dir / "evacuation_states.parquet")
    manifest = read_json(run_dir / "manifest.json")
    warning_time_s = manifest["evacuation_scenario"]["departure_model"]["warning_time_s"]

    assert (persisted["event_time_s"] - warning_time_s).tolist() == pytest.approx(
        emitted["clearance_s"]
    )
    expected = _weighted_quantiles_minutes(
        [float(value) for value in persisted["clearance_s"]],
        [float(value) for value in persisted["weight"]],
    )

    # The weights are unequal, so an unweighted ECDF must give a different median.
    ordered_clearances = sorted(float(value) for value in persisted["clearance_s"])
    unweighted_median = ordered_clearances[len(ordered_clearances) // 2] / 60.0
    assert expected["median"] != pytest.approx(unweighted_median), (
        "the cohort must discriminate weighted from unweighted quantiles"
    )

    saved_denominators = read_json(run_dir / "denominators.json")
    saved_stats = read_json(run_dir / "stats.json")
    assert saved_denominators["contract_version"] == "sample-denominators-v1"
    assert saved_stats["denominators"] == saved_denominators
    assert saved_stats["evacuation"]["clearance_time_minutes"] == expected

    monkeypatch.setenv("BKKFLOW_RUNS_DIR", str(pilot_inputs))
    client = TestClient(create_app())
    stats = client.get("/v1/runs/fractional-api/stats")
    evacuation = client.get("/v1/runs/fractional-api/evacuation")
    assert stats.status_code == evacuation.status_code == 200
    stats_body = stats.json()
    evacuation_body = evacuation.json()
    assert stats_body["evacuation"]["clearance_time_minutes"] == expected
    assert evacuation_body["clearance_time_minutes"] == expected
    assert stats_body["denominators"] == saved_denominators
    assert evacuation_body["denominators"] == saved_denominators


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
    # Row counts depend on how many age bands are populated, which is now a
    # configured choice, so assert the contract's meaning rather than a count.
    assert full["rows"] > sample["rows"] >= 1
    assert full["weight"] != sample["weight"]
    assert contract["scope"]["reweighting_to_full_population"] is False
    # The full-population weight must still be the whole cell total, whatever
    # the band count: splitting a cell by age must not create or lose people.
    persons = pd.read_parquet(run_dir / "persons.parquet")
    assert full["weight"] == pytest.approx(float(persons["weight"].sum()), rel=1e-9)
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


@pytest.mark.parametrize(("path", "value", "message"), [
    (("aoi", "aoi_id"), "sai-mai-district", "does not match"),
    (("input_scope",), "sai-mai-district", "does not match"),
    (("aoi", "osm_relation_id"), 3147281, "geometry does not match configuration"),
    (("sources", "osm"), "wrong-osm-source", "stage source identity mismatch"),
    (("sources", "population"), "wrong-population-source", "stage source identity mismatch"),
    (("source_sha256", "osm"), "a" * 64, "stage source hash mismatch"),
    (("source_sha256", "population"), "b" * 64, "stage source hash mismatch"),
    (("source_sha256", "geometry"), "c" * 64, "stage source hash mismatch"),
    (("analysis_crs",), "EPSG:3857", "stage analysis CRS mismatch"),
    (
        ("versions", "population"),
        "bkk-pop-v0.3-khlong-san-district-2020",
        "population version mismatch",
    ),
])
def test_named_pilot_rejects_configured_identity_matrix_before_run(
    pilot_inputs, path, value, message,
):
    config_path = pilot_inputs.parent / "config/pilots/khlong-san-district.json"
    payload = read_json(config_path)
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    write_json(config_path, payload)

    with pytest.raises(ValueError, match=message):
        runner.execute_run(
            run_id="identity-rejected",
            pilot_id="khlong-san-district",
            max_agents=10,
        )
    rejected = pilot_inputs / "identity-rejected"
    assert not (rejected / "manifest.json").exists()
    if (rejected / "run_state.json").exists():
        assert read_json(rejected / "run_state.json")["state"] != "published"


def test_named_pilot_missing_scoped_stage_never_falls_back(
    tmp_path, monkeypatch,
):
    config_dir = Path(__file__).resolve().parents[2] / "config"
    curated = tmp_path / "curated"
    curated.mkdir()
    write_json(curated / "stage_manifest.json", {
        "state": "complete",
        "aoi_id": "khlong-san-district",
    })
    runs = tmp_path / "runs"
    monkeypatch.setattr(runner, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(runner, "CURATED_DIR", curated)
    monkeypatch.setattr(runner, "RUNS_DIR", runs)
    expected = curated / "pilots/sai-mai-district/stage_manifest.json"

    with pytest.raises(
        ValueError,
        match=re.escape(f"Named pilot stage is incomplete: {expected}"),
    ):
        runner.execute_run(
            run_id="no-legacy-fallback",
            pilot_id="sai-mai-district",
            max_agents=1,
        )
    assert not runs.exists()


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


def test_published_population_qa_does_not_claim_a_licence_failure(pilot_inputs):
    """A run must name the age source it actually used, and never blame a gate.

    The registry approves the age/sex source and the build now ingests it per
    cell. The run record must therefore name that source. It must never state
    that a licence gate refused something, which would be false.
    """
    result = runner.execute_run(
        run_id="qa-honest", pilot_id="khlong-san-district", flood_enabled=True, max_agents=5
    )
    demographics = read_json(Path(result["run_dir"]) / "population_qa.json")["demographics"]

    assert demographics["age_structure_source"] == "worldpop-tha-age-sex-2026-r2025a"
    assert "licence" not in demographics["age_structure_source"]
    assert demographics["age_structure_mode"] == "per_cell"
    assert demographics["age_structure_spatial"] is True
    # Age is now sourced, so no person may be left unknown.
    assert "unknown" not in demographics["age_bands"]


def test_missing_age_rasters_abort_the_run_rather_than_dropping_age(pilot_inputs):
    """A half-downloaded source must fail loudly, not silently disable age."""
    config_path = runner.CONFIG_DIR / "population.json"
    original = read_json(config_path)
    config = dict(original)
    config["age_structure"] = dict(original.get("age_structure", {}))
    config["age_structure"]["raster_dir"] = str(Path(original["age_structure"]["raster_dir"]) / "nope")
    write_json(config_path, config)
    try:
        with pytest.raises(FileNotFoundError, match="band rasters are absent"):
            runner.execute_run(
                run_id="qa-missing-age", pilot_id="khlong-san-district", flood_enabled=True, max_agents=5
            )
    finally:
        write_json(config_path, original)


def test_configured_age_structure_flows_through_to_persons(pilot_inputs):
    """When bands are configured, persons carry them and the QA reports the source."""
    config_path = runner.CONFIG_DIR / "population.json"
    original = read_json(config_path)
    config = dict(original)
    config["age_structure"] = dict(original.get("age_structure", {}))
    config["age_structure"]["mode"] = "national"
    config["age_structure"]["bands"] = {"0_17": 0.25, "18_64": 0.60, "65_plus": 0.15}
    write_json(config_path, config)
    try:
        result = runner.execute_run(
            run_id="qa-aged", pilot_id="khlong-san-district", flood_enabled=True, max_agents=5
        )
    finally:
        write_json(config_path, original)

    run_dir = Path(result["run_dir"])
    demographics = read_json(run_dir / "population_qa.json")["demographics"]
    assert demographics["age_structure_source"] == "worldpop-tha-age-sex-2026-r2025a"
    assert demographics["age_bands"] == {"0_17": 0.25, "18_64": 0.60, "65_plus": 0.15}

    persons = pd.read_parquet(run_dir / "persons.parquet")
    assert "unknown" not in set(persons["age_band"])
    assert set(persons["age_band"]) == {"0_17", "18_64", "65_plus"}
    assert not any("no age-structure source passed the licence gate" in w for w in demographics.get("warnings", []))


def test_per_cell_age_structure_uses_the_real_rasters(pilot_inputs, tmp_path, monkeypatch):
    """The per_cell path must reach real persons without inventing anything.

    Uses a tiny synthetic raster set standing in for the WorldPop band files, so
    the test proves the wiring, the normalisation and the fallback, not the
    contents of a 2.5 GB external download.
    """
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from bkkflow.sources import population_age

    raster_dir = tmp_path / "agesex-exact"
    raster_dir.mkdir()
    # Cover the pilot AOI (approx lon 100.4995-100.5025, lat 13.7195-13.7215)
    # at the WorldPop 3-arc resolution, so the real pilot cells land inside.
    size = 16
    transform = from_origin(100.4950, 13.7250, 0.0008333, 0.0008333)
    rows, cols = np.mgrid[0:size, 0:size]
    arrays = {
        "05": np.full((size, size), 100.0, dtype="float32"),
        # Vary strongly with position so cells genuinely disagree.
        "30": (cols * 10.0 + rows).astype("float32"),
    }
    for code in population_age.BAND_CODES:
        data = arrays.get(code, np.zeros((size, size), dtype="float32"))
        path = raster_dir / f"tha_t_{code}_2026_CN_100m_R2025A_v1.tif"
        with rasterio.open(
            path, "w", driver="GTiff", height=size, width=size, count=1,
            dtype="float32", crs="EPSG:4326", transform=transform, nodata=-99999.0,
        ) as dst:
            dst.write(data, 1)

    cells = pd.DataFrame({
        "cell_id": ["left", "right"],
        "lon": [100.4996, 100.5024],
        "lat": [13.7214, 13.7214],
    })
    weights = population_age.age_weights_by_cell(cells, raster_dir)
    assert weights["left"] != weights["right"], "per-cell sampling must vary by cell"
    for cell in weights.values():
        assert sum(cell.values()) == pytest.approx(1.0, rel=1e-6)

    config_path = runner.CONFIG_DIR / "population.json"
    original = read_json(config_path)
    config = dict(original)
    config["age_structure"] = {
        **dict(original.get("age_structure", {})),
        "mode": "per_cell",
        "raster_dir": str(raster_dir),
    }
    write_json(config_path, config)
    try:
        result = runner.execute_run(
            run_id="qa-percell", pilot_id="khlong-san-district", flood_enabled=True, max_agents=5
        )
    finally:
        write_json(config_path, original)

    run_dir = Path(result["run_dir"])
    demographics = read_json(run_dir / "population_qa.json")["demographics"]
    assert demographics["age_structure_mode"] == "per_cell"
    assert demographics["age_structure_spatial"] is True
    assert demographics["age_structure_source"] == "worldpop-tha-age-sex-2026-r2025a"

    persons = pd.read_parquet(run_dir / "persons.parquet")
    assert "unknown" not in set(persons["age_band"])
    assert set(persons["age_band"]) <= {"5_9", "30_34"}
    # Spatial variation must survive into the persons, not be flattened.
    per_cell_share = persons.groupby("home_cell_id").apply(
        lambda g: g.loc[g["age_band"] == "5_9", "weight"].sum() / g["weight"].sum(),
        include_groups=False,
    )
    assert per_cell_share.nunique() > 1, "all cells collapsed to one share"


def test_missing_band_rasters_fail_loudly_rather_than_silently(tmp_path):
    """A partial download must not be mistaken for a real age structure."""
    from bkkflow.sources import population_age

    cells = pd.DataFrame({"cell_id": ["a"], "lon": [0.5], "lat": [0.5]})
    with pytest.raises(FileNotFoundError, match="band rasters are absent"):
        population_age.age_weights_by_cell(cells, tmp_path / "empty")


def test_manifest_alone_identifies_an_age_structured_run(pilot_inputs):
    """The manifest is the canonical record, so it must carry the age structure.

    population_version is supplied by the staged pilot bundle and does not
    change when demographics do, so without population_model.age_structure a
    reader of manifest.json alone cannot tell an age-structured run from an
    unaged one.
    """
    result = runner.execute_run(
        run_id="qa-manifest-age", pilot_id="khlong-san-district", flood_enabled=True, max_agents=5
    )
    manifest = read_json(Path(result["run_dir"]) / "manifest.json")
    assert runner.manifest_module.validate_manifest(manifest) == []

    age = manifest["population_model"]["age_structure"]
    assert age["mode"] == "per_cell"
    assert age["spatial"] is True
    assert age["basis"] == "population_weighted_over_covered_cells"
    assert age["source_id"] == "worldpop-tha-age-sex-2026-r2025a"
    assert "unknown" not in age["band_shares"]
    assert age["coverage"]["unknown_population_share"] == pytest.approx(0.0)

    # It must agree with the QA record rather than restate it independently.
    qa = read_json(Path(result["run_dir"]) / "population_qa.json")["demographics"]
    assert age["mode"] == qa["age_structure_mode"]
    assert age["band_shares"] == qa["age_bands"]
    assert age["coverage"] == qa["age_coverage"]

    # The schema remains able to read the previous optional shape emitted after
    # #61: old basis label, no coverage block.
    age["basis"] = "population_weighted_over_cells"
    age.pop("coverage")
    assert runner.manifest_module.validate_manifest(manifest) == []


def test_partial_age_coverage_is_reported_truthfully(pilot_inputs, monkeypatch):
    from bkkflow.sources import population_age

    def one_covered_cell(cells, _age_dir):
        return {str(cells.iloc[0]["cell_id"]): {"65_plus": 1.0}}

    monkeypatch.setattr(population_age, "age_weights_by_cell", one_covered_cell)
    result = runner.execute_run(
        run_id="qa-partial-age", pilot_id="khlong-san-district",
        flood_enabled=True, max_agents=5,
    )
    run_dir = Path(result["run_dir"])
    persons = pd.read_parquet(run_dir / "persons.parquet")
    qa = read_json(run_dir / "population_qa.json")
    manifest = read_json(run_dir / "manifest.json")

    assert persons["weight"].sum() == pytest.approx(300.0)
    assert persons.loc[persons["age_band"] == "unknown", "weight"].sum() == pytest.approx(200.0)
    demographics = qa["demographics"]
    assert demographics["age_band_basis"] == "population_weighted_over_covered_cells"
    assert demographics["age_coverage"] == pytest.approx(
        {
            "occupied_cells_total": 2,
            "occupied_cells_covered": 1,
            "occupied_cells_unknown": 1,
            "population_weight_total": 300.0,
            "population_weight_covered": 100.0,
            "population_weight_unknown": 200.0,
            "covered_population_share": 1.0 / 3.0,
            "unknown_population_share": 2.0 / 3.0,
        }
    )
    assert any("1 of 2 occupied cells" in warning for warning in qa["warnings"])
    assert any("66.67%" in warning for warning in qa["warnings"])
    assert not any("every person" in warning for warning in qa["warnings"])
    assert manifest["population_model"]["age_structure"]["coverage"] == (
        demographics["age_coverage"]
    )
    assert runner.manifest_module.validate_manifest(manifest) == []
