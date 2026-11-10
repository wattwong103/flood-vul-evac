"""Tests for the BKK-056b psk-v1 ladder: protocol lock, case assembly, evaluation and the record.

Synthetic fixtures only: no sensor feed, report source, gauge or real run is read. The planted
reporting-bias case is the failure BKK-056 exists to catch: a surface that only tracks exposure.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import flood  # noqa: E402
from bkkflow import observed_extent as oec  # noqa: E402
from bkkflow import point_skill as psk  # noqa: E402
from bkkflow import point_skill_ladder as psl  # noqa: E402
from bkkflow import point_skill_scores as pks  # noqa: E402

CRS = "EPSG:32647"
T0 = pd.Timestamp("2026-09-26 09:00", tz="Asia/Bangkok")
WINDOW = (T0, T0 + pd.Timedelta(hours=6))
DECLARED = [{"name": "cand", "timing": "declared"}]


def grid(side):
    bi, bj = np.indices((side, side))
    return bi.ravel(), bj.ravel()


def bias_case(side=40, seed=5):
    """Reports follow building cover, not water; the candidate is cover plus noise."""
    rng = np.random.default_rng(seed)
    bi, bj = grid(side)
    cover = rng.uniform(0.05, 0.95, side * side)
    reported = rng.random(side * side) < cover
    counts = pd.DataFrame({"bi": bi[reported], "bj": bj[reported], "time": T0 + pd.Timedelta(hours=1), "count": 1})
    labels, _ = psk.report_labels(counts, pd.DataFrame({"bi": bi, "bj": bj, "cover": cover}), WINDOW)
    candidate = pd.DataFrame({"bi": bi, "bj": bj, "score": cover + rng.normal(0, 0.15, side * side), "in_domain": True})
    rungs = {"exposure": pd.DataFrame({"bi": bi, "bj": bj, "value": cover}),
             "channel": pd.DataFrame({"bi": bi, "bj": bj, "value": rng.uniform(0, 500, side * side)})}
    return psl.assemble_case("report", labels, {"cand": candidate}, rungs)


def spec(case, case_id="bias", kind="report", candidates=DECLARED, block_m="auto"):
    return {"case_id": case_id, "kind": kind, "area": "synthetic", "window": WINDOW, "candidates": candidates,
            "block_m": psl.case_block_length(case) if block_m == "auto" else block_m}


def locked(*specs, n=199):
    protocol = psl.lock_protocol(list(specs), null_seed=20261110, interval_seed=20261111)
    protocol["null"]["n"] = protocol["interval"]["n"] = n  # fewer draws keep the suite fast
    return protocol


def fixture_record():
    case = bias_case()
    protocol = locked(spec(case))
    return psl.build_record(run_id="synthetic", protocol=protocol, results=[psl.evaluate(case, protocol, "bias")])


def walk(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield path + (key,), key, item
            yield from walk(item, path + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, path + (index,))


# The planted reporting-bias case (tasks.md BKK-056b; protocol s4)
def test_a_surface_that_only_tracks_exposure_beats_chance_but_not_the_exposure_rung():
    case = bias_case()
    result = psl.evaluate(case, locked(spec(case)), "bias")
    candidate, exposure = result["candidates"]["cand"], result["rungs"]["exposure"]
    assert result["status"] == "ok" and candidate["null"]["p_ge_observed"] < 0.05  # it beats chance
    difference = next(d for d in result["differences"] if d["rung"] == "exposure")
    assert difference["ci95"] is not None and not difference["ci95"][0] > 0  # a test assertion only
    assert difference["difference"] == pytest.approx(candidate["auc"] - exposure["auc"]) and exposure["auc"] > 0.6


# D5: numbers and intervals, never a verdict
def test_the_record_has_every_rung_and_no_verdict_or_place():
    record = fixture_record()
    assert record["protocol"]["claim_rule"] is None and record["labels"]["is_calibration"] is False
    result = record["results"][0]
    assert set(result["rungs"]) == {"exposure", "channel", "rain_only", "persistence"}  # never dropped
    for rung, reason in (("rain_only", "BKK-036B"), ("persistence", "prior observation")):
        assert result["rungs"][rung]["status"] == "not_available" and reason in result["rungs"][rung]["reason"]
        assert result["rungs"][rung]["auc"] is None
        null_difference = next(d for d in result["differences"] if d["rung"] == rung)
        assert null_difference["difference"] is None and null_difference["ci95"] is None and null_difference["reason"]
    words = ("verdict", "beat", "outperform", "adds skill", "adds_skill", "better than")
    for path, key, value in walk(record):
        assert key not in {"verdict", "claim", "adds_skill", "bi", "bj"}, path  # no verdict; no block leaves (D1)
        assert not (isinstance(value, str) and any(word in value.lower() for word in words)), path


def test_fixed_seeds_give_a_byte_identical_record_across_processes():
    first, second = psl.record_json(fixture_record()), psl.record_json(fixture_record())
    assert first == second and json.loads(first)["results"][0]["status"] == "ok"
    tests_dir = Path(__file__).resolve().parent
    code = "import sys; sys.path.insert(0, sys.argv[1]); import test_point_skill_ladder as t, bkkflow.point_skill_ladder as l; " \
           "sys.stdout.buffer.write(l.record_json(t.fixture_record()).encode())"
    env = {**os.environ, "PYTHONHASHSEED": "12345"}
    other = subprocess.run([sys.executable, "-c", code, str(tests_dir)], capture_output=True, env=env, check=True,
                           cwd=str(tests_dir.parent), timeout=300)
    assert other.stdout.decode() == first


# No observation reaches the scenario builders (s1)
@pytest.mark.parametrize("module", ["point_skill.py", "point_skill_stats.py", "point_skill_scores.py",
                                    "point_skill_ladder.py"])
def test_no_psk_module_imports_the_depth_builders(module):
    tree = ast.parse((Path(psk.__file__).parent / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module not in {"flood", "bkkflow.flood"}
            assert not {"build_depth_surface", "build_flood_slices", "flood"} & {alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            assert not any(alias.name.endswith("flood") for alias in node.names)


def test_a_full_sensor_case_never_calls_the_builders_or_changes_the_surface(monkeypatch):
    diagonal = gpd.GeoDataFrame(geometry=[LineString([(10, 20), (810, 820)])], crs=CRS)
    square = box(0, 0, 800, 800)
    scenario = flood.FloodScenario("t", "moderate", 0, 600, 1200, decay_length_m=150.0, peak_depth_m=0.55)
    surface = flood.build_depth_surface(diagonal, scenario=scenario, analysis_crs=CRS, aoi_geometry=square)
    slices = flood.build_flood_slices(surface, scenario=scenario)
    before = slices.copy()

    def refuse(*args, **kwargs):
        raise AssertionError("an observation path reached a scenario builder")
    monkeypatch.setattr(flood, "build_depth_surface", refuse)
    monkeypatch.setattr(flood, "build_flood_slices", refuse)

    nodes, origin = oec.declared_nodes(slices, diagonal, square)
    candidate = pks.block_scores(pks.scenario_points(nodes), higher_is_wetter=True)
    rng = np.random.default_rng(9)
    sensors = candidate[["bi", "bj"]].assign(sensor_id=lambda f: [f"s{k}" for k in range(len(f))],
                                             x=lambda f: origin[0] + 100 * f["bi"] + 25,
                                             y=lambda f: origin[1] + 100 * f["bj"] + 25)
    wet = rng.permutation(len(sensors)) < len(sensors) // 2
    feed = pd.concat([pd.DataFrame({"sensor_id": s, "depth_m": 0.3 if w else 0.05,
                                    "time": T0 + pd.to_timedelta(np.arange(10) * 30, unit="min")})
                      for s, w in zip(sensors["sensor_id"], wet)])
    labels = psk.sensor_labels(feed, dict.fromkeys(sensors["sensor_id"], 10), WINDOW)
    blocks, _ = psk.block_sensor_labels(labels, sensors, origin)
    channel = nodes[["i", "j", "aoi_frac"]].assign(value=pks.channel_distance(nodes, diagonal.geometry.union_all()))
    channel = pks.block_scores(channel, higher_is_wetter=False).rename(columns={"score": "value"})
    case = psl.assemble_case("sensor", blocks, {"scenario": candidate}, {"channel": channel})
    protocol = locked(spec(case, "pilot", "sensor", [{"name": "scenario", "timing": "declared", "distance_decay": True}]))
    record = psl.build_record(run_id="r", protocol=protocol, results=[psl.evaluate(case, protocol, "pilot")])
    assert record["results"][0]["status"] == "ok"
    assert slices.equals(before)  # the harness reads the surface and never changes it
    note = next(d for d in record["results"][0]["differences"] if d["rung"] == "channel")["note"]
    assert "by construction" in note and "different water layers" in note  # D6: stated, not a finding


# Undefined cases and the fallback
def test_a_case_below_thirty_per_class_is_undefined_with_null_metrics():
    case = bias_case(side=10)  # 100 blocks: fewer than 30 in a class is possible; force it
    case = case.assign(label=np.where(np.arange(len(case)) < 12, 1, 0))
    protocol = locked(spec(case, block_m=None))
    result = psl.evaluate(case, protocol, "bias")
    assert result["status"] == "undefined_too_few_positives" and result["counts"]["positives"] == 12
    assert all(result[key] is None for key in ("candidates", "rungs", "differences", "interval"))
    json.dumps(result, allow_nan=False)


def test_sparse_sensor_labels_keep_auc_and_null_but_have_no_interval():
    rng = np.random.default_rng(7)
    bi, bj = grid(60)
    states = np.full(bi.size, "unknown", dtype=object)
    picked = rng.choice(bi.size, 70, replace=False)
    states[picked] = np.where(np.arange(70) % 2 == 0, "observed_wet", "observed_dry")
    labels = pd.DataFrame({"bi": bi, "bj": bj, "state": states})
    candidate = pd.DataFrame({"bi": bi, "bj": bj, "score": rng.random(bi.size), "in_domain": True})
    case = psl.assemble_case("sensor", labels, {"cand": candidate}, {})
    assert psl.case_block_length(case) == psl.NOT_ESTIMABLE
    result = psl.evaluate(case, locked(spec(case, "sparse", "sensor")), "sparse")
    assert result["status"] == "ok" and result["interval"]["reason"] == "no_lag_with_min_pairs"
    assert result["candidates"]["cand"]["auc"] is not None and result["candidates"]["cand"]["null"]["n_undefined"] == 0
    assert result["candidates"]["cand"]["ci95"] is None
    assert all(d["ci95"] is None for d in result["differences"])  # under the fallback both intervals are null


# The lock
def test_the_lock_fixes_cases_before_any_score_and_evaluation_refuses_the_rest():
    case = bias_case()
    protocol = locked(spec(case))
    assert psl.PROTOCOL["cases"] == [] and psl.PROTOCOL["claim_rule"] is None  # locking copies the template
    with pytest.raises(ValueError, match="not a locked"):
        psl.evaluate(case, protocol, "other")
    timed = [{"name": "cand", "timing": "timed", "issue_time": T0, "lead": pd.Timedelta(hours=3)}]
    with pytest.raises(ValueError, match="window"):  # [t, t + lead] must be the case window (D6)
        psl.lock_protocol([spec(case, candidates=timed)], null_seed=1, interval_seed=2)
    for bad in (150, 0, "capped", True):
        with pytest.raises(ValueError, match="multiple of 100"):
            psl.lock_protocol([spec(case, block_m=bad)], null_seed=1, interval_seed=2)
    with pytest.raises(ValueError, match="seed"):
        psl.lock_protocol([spec(case)], null_seed=np.int64(1), interval_seed=2)
    with pytest.raises(ValueError, match="once"):
        psl.lock_protocol([spec(case), spec(case)], null_seed=1, interval_seed=2)
    with pytest.raises(ValueError, match="candidate"):
        psl.evaluate(case.drop(columns="cand"), protocol, "bias")
    with pytest.raises(ValueError, match="not locked"):  # a defined case locked without a length
        psl.evaluate(case, locked(spec(case, block_m=None)), "bias")
    altered = locked(spec(case, block_m=psl.NOT_ESTIMABLE))
    altered["interval"]["fallback"]["reason"] = "other_policy"
    with pytest.raises(ValueError, match="fallback"):
        psl.evaluate(case, altered, "bias")


def test_assembly_intersects_candidate_domains_and_keeps_report_cases_on_covered_blocks():
    labels = pd.DataFrame({"bi": [0, 1, 2, 3], "bj": 0, "state": ["reported", "not_reported", "unknown", "reported"]})
    first = pd.DataFrame({"bi": [0, 1, 2, 3], "bj": 0, "score": [1.0, 2.0, 3.0, np.nan], "in_domain": [1, 1, 1, 0] == 1})
    second = first.assign(in_domain=True, score=1.0)
    rung = {"exposure": pd.DataFrame({"bi": [0, 1, 2, 3], "bj": 0, "value": [0.5, 0.4, 0.0, 0.3]})}
    case = psl.assemble_case("report", labels, {"a": first, "b": second}, rung)
    assert case["bi"].tolist() == [0, 1] and case["label"].tolist() == [1, 0]  # block 2: zero cover; 3: not in a's
    sensor = psl.assemble_case("sensor", labels.assign(state=["observed_wet", "observed_dry", "unknown", "unknown"]),
                               {"a": first}, {})
    assert sensor["label"].tolist() == [1, 0, -1]  # a block without a sensor stays in the domain, unlabelled
    with pytest.raises(ValueError, match="exposure"):
        psl.assemble_case("report", labels, {"a": first}, {"exposure": rung["exposure"].iloc[:1]})
    with pytest.raises(ValueError, match="kind"):
        psl.assemble_case("satellite", labels, {"a": first}, {})
