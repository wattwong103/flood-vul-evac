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
    return psl.assemble_case("report", labels, {"cand": candidate}, rungs, area="synthetic", window=WINDOW)


def spec(case, case_id="bias", candidates=DECLARED, block_m="auto", **override):
    """The lock entry case_spec builds, with a chosen block length or field swapped in for negative tests."""
    entry = psl.case_spec(case, case_id=case_id, candidates=candidates)
    return {**entry, **({} if block_m == "auto" else {"block_m": block_m}), **override}


def locked(*specs, n=199):
    """The lock with 199 draws, not the protocol's 999, so the suite stays fast; n is part of the lock."""
    return psl.lock_protocol(list(specs), null_seed=20261110, interval_seed=20261111, n_draws=n)


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
    assert difference["ci95"] is not None and difference["ci95"][0] <= 0  # not clearly above 0: a test assertion only
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
    seed = "0" if os.environ.get("PYTHONHASHSEED") != "0" else "1"  # a hash seed this process is not using
    other = subprocess.run([sys.executable, "-c", code, str(tests_dir)], capture_output=True, timeout=300,
                           env={**os.environ, "PYTHONHASHSEED": seed}, cwd=str(tests_dir.parent))
    assert other.returncode == 0, other.stderr.decode(errors="replace")
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
    case = psl.assemble_case("sensor", blocks, {"scenario": candidate}, {"channel": channel}, area="synthetic", window=WINDOW)
    protocol = locked(spec(case, "pilot", [{"name": "scenario", "timing": "declared", "distance_decay": True}]))
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
    case = psl.assemble_case("sensor", labels, {"cand": candidate}, {}, area="synthetic", window=WINDOW)
    assert psl.case_block_length(case) == psl.NOT_ESTIMABLE
    result = psl.evaluate(case, locked(spec(case, "sparse")), "sparse")
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
    with pytest.raises(ValueError, match="block length"):  # a defined case locked without a length
        psl.evaluate(case, locked(spec(case, block_m=None)), "bias")


# Review round (code-reviewer, python-reviewer): regressions
def test_the_locked_block_length_must_be_the_labels_own():
    # Else an interval width could be chosen after the scores are seen (D4).
    case = bias_case()
    assert psl.case_block_length(case) == 100
    for chosen in (400, psl.NOT_ESTIMABLE):
        with pytest.raises(ValueError, match="block length"):
            psl.evaluate(case, locked(spec(case, block_m=chosen)), "bias")


def test_a_protocol_changed_after_the_lock_is_refused():
    case = bias_case()
    template = json.dumps(psl.PROTOCOL, sort_keys=True)
    for change in (lambda p: p["definition"].update(min_positives=1), lambda p: p["null"].update(n=5),
                   lambda p: p["interval"]["fallback"].update(reason="other_policy"),
                   lambda p: p.update(claim_rule="adds skill when the lower bound is above 0")):
        protocol = locked(spec(case))
        change(protocol)
        with pytest.raises(ValueError, match="changed after"):
            psl.evaluate(case, protocol, "bias")
        with pytest.raises(ValueError, match="changed after"):
            psl.build_record(run_id="r", protocol=protocol, results=[])
    assert json.dumps(psl.PROTOCOL, sort_keys=True) == template and psl.PROTOCOL["null"]["n"] == 999
    for bad in ({"n_draws": 0}, {"null_seed": -1}, {"n_draws": 99.0}):
        with pytest.raises(ValueError, match="seed|n_draws"):
            psl.lock_protocol([spec(case)], **{"null_seed": 1, "interval_seed": 2, **bad})


def test_kind_names_windows_and_results_must_match_the_lock():
    case = bias_case()
    with pytest.raises(ValueError, match="kind"):  # a report case evaluated under a sensor lock
        psl.evaluate(case, locked(spec(case, kind="sensor")), "bias")
    twice = [{"name": "cand", "timing": "declared"}] * 2
    for candidates, message in ((twice, "once"), ([{"name": "label", "timing": "declared"}], "reserved"),
                                ([{"name": 7, "timing": "declared"}], "name")):
        with pytest.raises(ValueError, match=message):
            psl.lock_protocol([spec(case, candidates=candidates)], null_seed=1, interval_seed=2)
    naive = {**spec(case), "window": (WINDOW[0].tz_localize(None), WINDOW[1].tz_localize(None))}
    with pytest.raises(ValueError, match="time zone"):
        psl.lock_protocol([naive], null_seed=1, interval_seed=2)
    timed = [{"name": "cand", "timing": "timed", "issue_time": T0, "lead": pd.Timedelta(hours=6)}]
    entry = psl.lock_protocol([spec(case, candidates=timed)], null_seed=1, interval_seed=2)["cases"][0]["candidates"][0]
    assert entry == {"name": "cand", "timing": "timed", "distance_decay": False,
                     "issue_time": "2026-09-26T09:00:00+07:00", "lead_s": 21600}
    protocol = locked(spec(case), spec(case, case_id="second"))
    result = psl.evaluate(case, protocol, "bias")
    with pytest.raises(ValueError, match="every locked case"):  # a partial run never looks complete
        psl.build_record(run_id="r", protocol=protocol, results=[result])
    with pytest.raises(ValueError, match="every locked case"):
        psl.build_record(run_id="r", protocol=protocol, results=[result, result])
    for reserved in ("label", "state", "exposure"):
        frame = pd.DataFrame({"bi": [0], "bj": [0], "score": [1.0], "in_domain": [True]})
        with pytest.raises(ValueError, match="reserved"):
            psl.assemble_case("report", case.assign(state="reported")[["bi", "bj", "state"]], {reserved: frame}, {}, area="synthetic", window=WINDOW)
    with pytest.raises(ValueError, match="integer"):
        psl.case_block_length(case.assign(bi=case["bi"] + 0.5))


def test_every_undefined_path_and_both_fallback_reasons_give_null_metrics(monkeypatch):
    case = bias_case()
    empty = case.iloc[0:0]
    assert psl.case_block_length(empty) is None
    result = psl.evaluate(empty, locked(spec(empty, case_id="empty")), "empty")
    assert result["status"] == "undefined_no_labelled_blocks" and result["counts"] == {
        "blocks": 0, "positives": 0, "negatives": 0}
    few = case.assign(label=np.where(np.arange(len(case)) < 20, 0, 1))
    assert psl.evaluate(few, locked(spec(few, case_id="few")), "few")["status"] == "undefined_too_few_negatives"
    with monkeypatch.context() as patch:  # no correlogram lag computable: locked undefined (D4)
        patch.setattr(psl.pss, "correlation_range_m", lambda label: (_ for _ in ()).throw(ValueError("none")))
        assert psl.case_block_length(case) is None
        assert psl.evaluate(case, locked(spec(case, block_m=None)), "bias")["status"] == "undefined_no_correlogram_lag"
    bi, bj = grid(40)
    halves = pd.DataFrame({"bi": bi, "bj": bj, "state": np.where(bi < 20, "reported", "not_reported")})
    score = pd.DataFrame({"bi": bi, "bj": bj, "score": bi + 0.5 * bj, "in_domain": True})
    plane = psl.assemble_case("report", halves, {"cand": score}, {}, area="synthetic", window=WINDOW)
    plane_result = psl.evaluate(plane, locked(spec(plane, "plane")), "plane")
    assert plane_result["interval"]["reason"] == "correlation_range_exceeds_half_grid"
    assert plane_result["candidates"]["cand"]["ci95"] is None and plane_result["candidates"]["cand"]["auc"] is not None


def test_rain_and_persistence_rungs_are_scored_wetter_when_higher():
    case = bias_case()
    rng = np.random.default_rng(3)
    with_all = case.assign(rain_only=case["exposure"] * 50 + rng.random(len(case)), persistence=case["exposure"] * 2)
    result = psl.evaluate(with_all, locked(spec(with_all)), "bias")
    for rung in ("rain_only", "persistence"):
        assert result["rungs"][rung]["auc"] > 0.6 and result["rungs"][rung]["ci95"] is not None  # higher is wetter
        assert next(d for d in result["differences"] if d["rung"] == rung)["ci95"] is not None
    assert result["rungs"]["persistence"]["auc"] == pytest.approx(result["rungs"]["exposure"]["auc"])


def test_assembly_intersects_candidate_domains_and_keeps_report_cases_on_covered_blocks():
    labels = pd.DataFrame({"bi": [0, 1, 2, 3], "bj": 0, "state": ["reported", "not_reported", "unknown", "reported"]})
    first = pd.DataFrame({"bi": [0, 1, 2, 3], "bj": 0, "score": [1.0, 2.0, 3.0, np.nan],
                          "in_domain": [True, True, True, False]})
    second = first.assign(in_domain=True, score=1.0)
    rung = {"exposure": pd.DataFrame({"bi": [0, 1, 2, 3], "bj": 0, "value": [0.5, 0.4, 0.0, 0.3]})}
    case = psl.assemble_case("report", labels, {"a": first, "b": second}, rung, area="synthetic", window=WINDOW)
    assert case["bi"].tolist() == [0, 1] and case["label"].tolist() == [1, 0]  # block 2: zero cover; 3: not in a's
    sensor = psl.assemble_case("sensor", labels.assign(state=["observed_wet", "observed_dry", "unknown", "unknown"]),
                               {"a": first}, {}, area="synthetic", window=WINDOW)
    assert sensor["label"].tolist() == [1, 0, -1]  # a block without a sensor stays in the domain, unlabelled
    with pytest.raises(ValueError, match="exposure"):
        psl.assemble_case("report", labels, {"a": first}, {"exposure": rung["exposure"].iloc[:1]}, area="synthetic", window=WINDOW)
    with pytest.raises(ValueError, match="kind"):
        psl.assemble_case("satellite", labels, {"a": first}, {}, area="synthetic", window=WINDOW)


# Codex review of PR 4: regressions
def test_evaluation_is_bound_to_the_locked_data_window_area_and_rungs():
    case = bias_case()
    protocol = locked(spec(case))
    assert protocol["cases"][0]["rungs"] == ["exposure", "channel"] and len(protocol["cases"][0]["data_sha256"]) == 64
    shifted = (WINDOW[0] + pd.Timedelta(days=1), WINDOW[1] + pd.Timedelta(days=1))
    with pytest.raises(ValueError, match="window"):  # observations labelled for one window, locked for another
        psl.evaluate(case, locked(spec(case, window=shifted)), "bias")
    with pytest.raises(ValueError, match="area"):
        psl.evaluate(case, locked(spec(case, area="elsewhere")), "bias")
    with pytest.raises(ValueError, match="rung"):  # a baseline dropped after scoring
        psl.evaluate(case.drop(columns="exposure"), protocol, "bias")
    with pytest.raises(ValueError, match="rung"):  # or one added
        psl.evaluate(case.assign(persistence=1.0), protocol, "bias")
    flipped = case.assign(label=np.where(np.arange(len(case)) == 0, 1 - case["label"], case["label"]))
    with pytest.raises(ValueError, match="changed after"):
        psl.evaluate(flipped, protocol, "bias")


def test_a_result_carries_the_lock_that_produced_it():
    case = bias_case()
    first = locked(spec(case))
    second = psl.lock_protocol([spec(case)], null_seed=1, interval_seed=2, n_draws=199)
    result = psl.evaluate(case, second, "bias")
    assert result["lock_sha256"] == second["lock_sha256"] != first["lock_sha256"]
    with pytest.raises(ValueError, match="lock"):
        psl.build_record(run_id="r", protocol=first, results=[result])
    with pytest.raises(ValueError, match="fields"):  # nothing else, block positions included, enters the record
        psl.build_record(run_id="r", protocol=second, results=[{**result, "blocks": [[0, 0]]}])
