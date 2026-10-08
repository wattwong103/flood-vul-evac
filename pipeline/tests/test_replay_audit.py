"""Independent saved-bundle audit for BKK-015e."""

from __future__ import annotations

import ast
import copy
import math
import sys
from pathlib import Path

import geopandas as gpd
import networkx as nx
import pandas as pd
import pytest
from shapely import wkt
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import replay_audit, runner
from bkkflow.util import read_json, write_json
from test_pilot_publication import pilot_inputs  # noqa: F401


@pytest.fixture
def published_run(pilot_inputs: Path) -> Path:  # noqa: F811
    result = runner.execute_run(
        run_id="audit-source", pilot_id="khlong-san-district",
        flood_enabled=True, max_agents=3,
    )
    return Path(result["run_dir"])


def test_load_bundle_verifies_saved_identity_hashes_and_rows(published_run: Path) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)

    assert bundle.run_id == "audit-source"
    assert bundle.aoi_id == "khlong-san-district"
    assert set(replay_audit.REQUIRED_ROLES) <= set(bundle.outputs)
    assert bundle.manifest["code_identity"]["source_sha256"]
    assert bundle.manifest["population_model"]["seed"] == bundle.cohort_metadata["seed"]
    assert bundle.stats["denominators"] == bundle.denominators
    assert {"manifest.json", "stats.json", "run_state.json"} <= set(bundle.file_hashes)
    for role, frame in bundle.tables.items():
        assert bundle.outputs[role]["row_count"] == len(frame)


def test_load_bundle_rejects_tampered_registered_output(published_run: Path) -> None:
    path = published_run / "evacuation_states.parquet"
    path.write_bytes(path.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="output hash mismatch.*evacuation_states"):
        replay_audit.load_audit_bundle(published_run)


def test_load_bundle_rejects_manifest_and_identity_contradictions(
    published_run: Path,
) -> None:
    original = read_json(published_run / "manifest.json")
    def changed(path: tuple[str | int, ...], value: object) -> dict:
        candidate, target = copy.deepcopy(original), None
        target = candidate
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return candidate

    missing = copy.deepcopy(original)
    missing["outputs"].pop()
    missing_active = copy.deepcopy(original)
    missing_active.pop("active_scenario")
    duplicate_role, duplicate_uri = copy.deepcopy(original), copy.deepcopy(original)
    duplicate_role["outputs"].append({**duplicate_role["outputs"][0], "uri": "duplicate.parquet"})
    duplicate_uri["outputs"].append({**duplicate_uri["outputs"][0], "role": "duplicate_role"})
    cases = [
        ("missing required output role", missing),
        ("duplicate output role", duplicate_role),
        ("duplicate output URI", duplicate_uri),
        ("output path escapes", changed(("outputs", 0, "uri"), "../escape.parquet")),
        ("output row count mismatch", changed(("outputs", 0, "row_count"), 5)),
        ("run identity mismatch", changed(("run_id",), "wrong-run")),
        ("AOI identity mismatch", changed(("geography", "aoi_id"), "wrong-aoi")),
        ("seed identity mismatch", changed(("evacuation_scenario", "seed"), 1)),
        ("sample-cap identity mismatch", changed(("pflow_contract", "activity_generator", "parameters", "sample_cap"), 1)),
        ("active-scenario identity mismatch", missing_active),
        ("active-scenario identity mismatch", changed(("active_scenario", "state"), "legacy")),
        ("active-scenario identity mismatch", changed(("active_scenario", "configured_scenario_id"), "wrong")),
        ("source identity is invalid", changed(("source_versions", 0, "content_sha256"), "invalid")),
    ]

    for message, candidate in cases:
        write_json(published_run / "manifest.json", candidate)
        with pytest.raises(ValueError, match=message):
            replay_audit.load_audit_bundle(published_run)
    write_json(published_run / "manifest.json", original)


def test_load_bundle_rejects_run_state_scenario_mismatch(published_run: Path) -> None:
    state = read_json(published_run / "run_state.json")
    state["active_scenario"]["state"] = "dry"
    write_json(published_run / "run_state.json", state)

    with pytest.raises(ValueError, match="active-scenario identity mismatch"):
        replay_audit.load_audit_bundle(published_run)


def test_load_bundle_rejects_stats_contract_mismatch(published_run: Path) -> None:
    stats = read_json(published_run / "stats.json")
    stats["denominators"]["contract_version"] = "broken"
    write_json(published_run / "stats.json", stats)

    with pytest.raises(ValueError, match="denominator contract mismatch"):
        replay_audit.load_audit_bundle(published_run)


def test_auditor_does_not_import_or_call_pipeline_builders() -> None:
    tree = ast.parse(Path(replay_audit.__file__).read_text(encoding="utf-8"))
    local_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.level or (node.module or "").startswith("bkkflow"))
    }
    local_imports |= {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names if alias.name.startswith("bkkflow")
    }
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert not local_imports
    assert not calls & {
        "select_cohort", "simulate_evacuation", "build_denominator_contract",
        "weighted_clearance_minutes", "_build_stats", "route_lookup",
    }


def test_reconstruct_cohort_metrics_matches_saved_bundle(published_run: Path) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    audit = replay_audit.reconstruct_cohort_metrics(bundle)

    assert audit.denominators == bundle.denominators
    assert audit.clearance_time_minutes == bundle.stats["evacuation"]["clearance_time_minutes"]
    assert audit.cohort_person_ids == tuple(bundle.tables["cohort"]["person_id"])
    assert set(audit.cohort_person_ids) <= set(audit.present_person_ids) <= set(audit.sample_person_ids)


def _split_terminal_bundle(bundle: replay_audit.AuditBundle) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sample, present, cohort = replay_audit._derive_populations(bundle)
    splits = (
        (8.882412251852449, 88.91758774814755),
        (52.13314519160798, 50.06685480839202),
        (24.649969248210954, 24.250030751789044),
    )
    records = []
    for row, (arrived_weight, full_weight) in zip(
        bundle.tables["evacuation_states"].to_dict("records"), splits, strict=True,
    ):
        records.append({**row, "weight": arrived_weight})
        records.append({
            **row,
            "state": "shelter_full",
            "reason": "capacity_exhausted",
            "weight": full_weight,
            "outcome_id": f"{row['source_person_id']}:shelter_full:1",
        })
    states = pd.DataFrame(records, columns=bundle.tables["evacuation_states"].columns)
    bundle.tables["evacuation_states"] = states

    cohort_weight = math.fsum(float(value) for value in cohort["weight"])
    terminal = bundle.denominators["quantities"]["terminal_states"]
    shares = bundle.denominators["shares"]["terminal_of_cohort"]
    for state in replay_audit.TERMINAL_STATES:
        group = states.loc[states["state"] == state]
        weight = math.fsum(float(value) for value in group["weight"])
        terminal[state] = {
            "outcome_records": len(group),
            "source_rows": group["source_person_id"].nunique(),
            "weight": weight,
        }
        shares[state] = weight / cohort_weight
    arrived = terminal["arrived"]
    bundle.denominators["clearance_denominator"] = {
        "outcome_records": arrived["outcome_records"],
        "source_rows": arrived["source_rows"],
        "weight": arrived["weight"],
        "population": "arrivals_only",
    }
    bundle.denominators["unserved_derived"]["weight"] = math.fsum(
        terminal[state]["weight"]
        for state in replay_audit.TERMINAL_STATES
        if state != "arrived"
    )
    direct_weight = math.fsum(float(value) for value in states["weight"])
    grouped_weight = math.fsum(item["weight"] for item in terminal.values())
    assert direct_weight == cohort_weight
    assert direct_weight.hex() != grouped_weight.hex()
    bundle.denominators["conservation"].update(
        terminal_weight=direct_weight,
        residual_abs=abs(cohort_weight - direct_weight),
    )
    return sample, present, cohort


def test_reconstruct_denominators_sums_original_split_outcome_records(
    published_run: Path,
) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    sample, present, cohort = _split_terminal_bundle(bundle)

    reconstructed = replay_audit._reconstruct_denominators(bundle, sample, present, cohort)

    assert reconstructed == bundle.denominators


def test_reconstruct_denominators_rejects_one_ulp_contract_alteration(
    published_run: Path,
) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    sample, present, cohort = _split_terminal_bundle(bundle)
    saved = bundle.denominators["conservation"]["terminal_weight"]
    bundle.denominators["conservation"]["terminal_weight"] = math.nextafter(saved, math.inf)

    with pytest.raises(ValueError, match="denominator reconstruction mismatch"):
        replay_audit._reconstruct_denominators(bundle, sample, present, cohort)


def test_reconstruct_denominators_rejects_split_source_weight_drift(
    published_run: Path,
) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    sample, present, cohort = _split_terminal_bundle(bundle)
    bundle.tables["evacuation_states"].loc[0, "weight"] += 0.01

    with pytest.raises(ValueError, match="terminal source conservation mismatch"):
        replay_audit._reconstruct_denominators(bundle, sample, present, cohort)


def test_reconstruct_cohort_metrics_rejects_terminal_weight_drift(published_run: Path) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    bundle.tables["evacuation_states"].loc[0, "weight"] += 0.25

    with pytest.raises(ValueError, match="terminal .* mismatch"):
        replay_audit.reconstruct_cohort_metrics(bundle)


def test_reconstruct_cohort_metrics_derives_sampling_probability(published_run: Path) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    forged = 0.123
    bundle.cohort_metadata["sampling_probability"] = forged
    bundle.denominators["pairing"]["common_identity"]["sampling_probability"] = forged
    bundle.tables["cohort"]["sampling_probability"] = forged

    with pytest.raises(ValueError, match="cohort identity mismatch"):
        replay_audit.reconstruct_cohort_metrics(bundle)


def test_inverse_weighted_clearance_is_arrivals_only_and_null_when_empty() -> None:
    states = pd.DataFrame({
        "state": ["arrived", "route_failed", "arrived"],
        "event_time_s": [660.0, 999.0, 720.0], "weight": [0.1, 50.0, 0.2],
    })
    assert replay_audit.inverse_weighted_clearance(states, warning_time_s=600.0) == {
        "p5": 1.0, "median": 2.0, "p95": 2.0,
    }
    states["state"] = "route_failed"
    assert replay_audit.inverse_weighted_clearance(states, warning_time_s=600.0) == {
        "p5": None, "median": None, "p95": None,
    }


def test_reconstruct_peak_routes_matches_saved_route_evidence(published_run: Path) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    audit = replay_audit.reconstruct_peak_routes(bundle)

    assert set(audit.routes) == set(bundle.tables["cohort"]["person_id"])
    assert audit.top_bottleneck_edges == bundle.stats["evacuation"]["top_bottleneck_edges"]
    assert all(route.status == "routed" and route.cost_s >= 0 for route in audit.routes.values())


def test_published_network_wkt_preserves_projected_length_precision(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest,
) -> None:
    pilot_runs = request.getfixturevalue("pilot_inputs")
    build_network = runner.network_module.build_network
    geometry = LineString([
        (661528.0098183819791302, 1517009.1526174470782280),
        (661530.0351116514066234, 1517010.4595167222432792),
    ])

    def with_precision_edge(*args, **kwargs):
        build = build_network(*args, **kwargs)
        edge = gpd.GeoDataFrame(
            [{
                "edge_id": "precision-regression-edge",
                "u": -9002,
                "v": -9001,
                "length_m": geometry.length,
                "highway": "residential",
                "network_version": str(build.edges.iloc[0]["network_version"]),
                "walk_allowed": True,
                "vehicle_allowed": True,
                "speed_walk_mps": 1.25,
                "speed_vehicle_mps": 20 / 3.6,
                "oneway": False,
            }],
            geometry=[geometry],
            crs=build.edges.crs,
        )
        build.edges = gpd.GeoDataFrame(
            pd.concat([build.edges, edge], ignore_index=True),
            geometry="geometry",
            crs=build.edges.crs,
        )
        return build

    monkeypatch.setattr(runner.network_module, "build_network", with_precision_edge)
    result = runner.execute_run(
        run_id="precision-publication", pilot_id="khlong-san-district",
        flood_enabled=True, max_agents=3,
    )
    run_dir = Path(result["run_dir"])
    assert run_dir.parent == pilot_runs
    saved = pd.read_parquet(run_dir / "network_edges.parquet")
    row = saved.loc[saved["edge_id"] == "precision-regression-edge"].iloc[0]

    assert abs(wkt.loads(row["geometry_wkt"]).length - row["length_m"]) <= 1e-6
    assert replay_audit.audit_saved_run(run_dir)["status"] == "PASS"


def test_reconstruct_peak_routes_rejects_geometry_length_mismatch(
    published_run: Path,
) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    walk_edge = bundle.tables["network_edges"]["walk_allowed"].astype(bool)
    row = bundle.tables["network_edges"].index[walk_edge][0]
    bundle.tables["network_edges"].loc[row, "length_m"] += 0.01

    with pytest.raises(ValueError, match="geometry-length mismatch"):
        replay_audit.reconstruct_peak_routes(bundle)


def test_reconstruct_peak_routes_rejects_closure_contradiction(published_run: Path) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    peak = bundle.tables["edge_states"]["time_s"] == bundle.manifest["flood_scenario"]["parameters"]["peak_time_s"]
    row = bundle.tables["edge_states"].index[peak & (bundle.tables["edge_states"]["mode"] == 0)][0]
    bundle.tables["edge_states"].loc[row, "speed_multiplier"] = 0.0
    bundle.tables["edge_states"].loc[row, "closed"] = False

    with pytest.raises(ValueError, match="closure contradiction"):
        replay_audit.reconstruct_peak_routes(bundle)


def test_reconstruct_peak_routes_rejects_destination_tie(published_run: Path) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    refuges = bundle.tables["refuges"]
    refuges.loc[refuges.index[0], ["x", "y"]] = refuges.loc[refuges.index[1], ["x", "y"]].to_numpy()

    with pytest.raises(ValueError, match="destination tie"):
        replay_audit.reconstruct_peak_routes(bundle)


def test_reconstruct_peak_routes_rejects_parallel_edge_tie(published_run: Path) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    edge = bundle.tables["network_edges"].iloc[[0]].assign(edge_id="parallel")
    peak_time = bundle.manifest["flood_scenario"]["parameters"]["peak_time_s"]
    states = bundle.tables["edge_states"]
    state = states.loc[(states["time_s"] == peak_time) & (states["mode"] == 0)].iloc[[0]].assign(edge_id="parallel")
    bundle.tables["network_edges"] = pd.concat([bundle.tables["network_edges"], edge])
    bundle.tables["edge_states"] = pd.concat([bundle.tables["edge_states"], state])

    with pytest.raises(ValueError, match="parallel-edge tie"):
        replay_audit.reconstruct_peak_routes(bundle)


def test_unique_shortest_route_rejects_unexplained_path_tie() -> None:
    graph = nx.Graph()
    graph.add_edge(0, 1, cost=1.0, edge_id="a", length_m=1.0)
    graph.add_edge(1, 3, cost=1.0, edge_id="b", length_m=1.0)
    graph.add_edge(0, 2, cost=1.0, edge_id="c", length_m=1.0)
    graph.add_edge(2, 3, cost=1.0, edge_id="d", length_m=1.0)

    with pytest.raises(ValueError, match="path tie"):
        replay_audit.unique_shortest_route(graph, 0, 3)


def test_integerized_capacity_partition_preserves_fractional_weight() -> None:
    assert replay_audit.integerized_capacity_partition(2.4, 1) == (1.2, 1.2, 0)
    assert replay_audit.integerized_capacity_partition(0.4, 1) == (0.4, 0.0, 0)
    assert replay_audit.integerized_capacity_partition(2.4, 0) == (0.0, 2.4, 0)
    assert replay_audit.integerized_capacity_partition(2.8, 10) == (2.8, 0.0, 7)


def test_replay_evacuation_matches_saved_terminal_evidence(published_run: Path) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    audit = replay_audit.replay_evacuation(bundle)

    assert set(audit.states["outcome_id"]) == set(bundle.tables["evacuation_states"]["outcome_id"])
    assert audit.denominators == bundle.denominators
    assert audit.clearance_time_minutes == bundle.stats["evacuation"]["clearance_time_minutes"]
    assert audit.remaining_capacity == {
        item["dest_id"]: item["remaining"] for item in bundle.stats["evacuation"]["destinations"]
    }
    report = replay_audit.final_audit_report(bundle)
    assert report["status"] == "PASS" and report["audited_hashes"]
    assert report["reconstructed"]["terminal_records"] == len(audit.states)


def test_final_audit_report_never_passes_failed_replay(published_run: Path) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    bundle.tables["evacuation_states"].loc[0, "reason"] = "forged"

    report = replay_audit.final_audit_report(bundle)

    assert report["status"] == "FAIL"
    assert "PASS" not in str(report)
    assert report["checks"][0]["status"] == "FAIL"


@pytest.mark.parametrize("field", ["cohort_weighted", "median_clearance", "terminal_event"])
def test_final_audit_report_rejects_non_finite_published_metrics(
    published_run: Path, field: str,
) -> None:
    bundle = replay_audit.load_audit_bundle(published_run)
    if field == "terminal_event":
        bundle.tables["evacuation_states"].loc[0, "event_time_s"] = float("nan")
    elif field == "median_clearance":
        bundle.stats["evacuation"]["clearance_time_minutes"]["median"] = float("nan")
    else:
        bundle.stats["evacuation"][field] = float("nan")

    report = replay_audit.final_audit_report(bundle)

    assert report["status"] == "FAIL"
    assert "PASS" not in str(report)
