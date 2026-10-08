"""Independent saved-bundle audit for BKK-015e."""

from __future__ import annotations

import ast
import copy
import sys
from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

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
        ("source identity is invalid", changed(("source_versions", 0, "content_sha256"), "invalid")),
    ]

    for message, candidate in cases:
        write_json(published_run / "manifest.json", candidate)
        with pytest.raises(ValueError, match=message):
            replay_audit.load_audit_bundle(published_run)
    write_json(published_run / "manifest.json", original)


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
