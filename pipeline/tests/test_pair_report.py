"""Checked dry/moderate comparison-report contract."""

from __future__ import annotations

import hashlib
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import report
from bkkflow import replay_audit, runner
from bkkflow.util import read_json, write_json
from test_pilot_publication import pilot_inputs  # noqa: F401


@pytest.fixture
def published_pair(pilot_inputs: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:  # noqa: F811
    monkeypatch.setattr(report, "RUNS_DIR", pilot_inputs)
    runner.execute_run(
        run_id="pair-dry", pilot_id="khlong-san-district",
        flood_enabled=False, max_agents=3,
    )
    runner.execute_run(
        run_id="pair-moderate", pilot_id="khlong-san-district",
        flood_enabled=True, max_agents=3, cohort_from_run="pair-dry",
    )
    return "pair-dry", "pair-moderate"


def test_load_checked_pair_accepts_one_audited_dry_moderate_pair(
    published_pair: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audited: list[str] = []
    audit_saved_run = replay_audit.audit_saved_run

    def record_audit(path: Path) -> dict[str, Any]:
        audited.append(Path(path).name)
        return audit_saved_run(path)

    monkeypatch.setattr(report.replay_audit, "audit_saved_run", record_audit)
    pair = report.load_checked_pair(*reversed(published_pair))

    assert pair.aoi_id == "khlong-san-district"
    assert pair.aoi_label == "Khlong San"
    assert (pair.dry.run_id, pair.moderate.run_id) == published_pair
    assert pair.audit_status == "PASS"
    assert sorted(audited) == sorted(published_pair)


def _registered_json(
    run_id: str, role: str, mutate: Callable[[dict[str, Any]], None]
) -> dict[str, Any]:
    run_dir = report.RUNS_DIR / run_id
    manifest = read_json(run_dir / "manifest.json")
    entry = next(item for item in manifest["outputs"] if item["role"] == role)
    path = run_dir / entry["uri"]
    payload = read_json(path)
    mutate(payload)
    write_json(path, payload)
    entry["content_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(run_dir / "manifest.json", manifest)
    return payload


def _as_aoi(run: report.CheckedRun, aoi_id: str, label: str) -> report.CheckedRun:
    bundle = run.bundle
    manifest, stats = deepcopy(bundle.manifest), deepcopy(bundle.stats)
    metadata, denominators = deepcopy(bundle.cohort_metadata), deepcopy(bundle.denominators)
    manifest["geography"]["aoi_id"] = aoi_id
    stats["geography"].update(aoi_id=aoi_id, name=label)
    metadata["aoi_id"] = aoi_id
    denominators["pairing"]["common_identity"]["aoi_id"] = aoi_id
    stats["denominators"] = denominators
    bundle = replace(
        bundle, aoi_id=aoi_id, manifest=manifest, stats=stats,
        cohort_metadata=metadata, denominators=denominators,
    )
    return replace(run, bundle=bundle)


def test_load_checked_pair_is_area_generic(
    published_pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    audited_run = report._audited_run
    monkeypatch.setattr(
        report, "_audited_run",
        lambda run_id: _as_aoi(audited_run(run_id), "bang-rak-district", "Bang Rak"),
    )

    pair = report.load_checked_pair(*published_pair)

    assert (pair.aoi_id, pair.aoi_label) == ("bang-rak-district", "Bang Rak")


def test_load_checked_pair_rejects_duplicate_state_and_broken_reference(
    published_pair: tuple[str, str],
) -> None:
    dry_id, moderate_id = published_pair
    moderate_dir = report.RUNS_DIR / moderate_id
    manifest_path, state_path = (
        moderate_dir / "manifest.json",
        moderate_dir / "run_state.json",
    )
    manifest, state = read_json(manifest_path), read_json(state_path)
    manifest["active_scenario"]["state"] = "dry"
    state["active_scenario"]["state"] = "dry"
    write_json(manifest_path, manifest)
    write_json(state_path, state)
    with pytest.raises(ValueError, match="exactly one dry and one moderate"):
        report.load_checked_pair(dry_id, moderate_id)

    manifest["active_scenario"]["state"] = "moderate"
    state["active_scenario"]["state"] = "moderate"
    write_json(manifest_path, manifest)
    write_json(state_path, state)
    _registered_json(
        moderate_id,
        "cohort_metadata",
        lambda value: value.update(reference_run_id="unrelated-run"),
    )
    with pytest.raises(ValueError, match="moderate cohort must reference dry run"):
        report.load_checked_pair(dry_id, moderate_id)


def test_load_checked_pair_rejects_common_identity_and_assumption_mismatches(
    published_pair: tuple[str, str],
) -> None:
    dry_id, moderate_id = published_pair
    moderate_dir = report.RUNS_DIR / moderate_id
    manifest_path, stats_path = moderate_dir / "manifest.json", moderate_dir / "stats.json"
    original_manifest, original_stats = read_json(manifest_path), read_json(stats_path)
    cases: list[tuple[str, Callable[[dict[str, Any], dict[str, Any]], None]]] = [
        ("AOI label", lambda _manifest, stats: stats["geography"].update(name="Other")),
        ("source/code identity", lambda manifest, _stats: manifest["code_identity"].update(git_tree="0" * 40)),
        ("population assumptions", lambda manifest, _stats: manifest["population_model"].update(population_version="other")),
        ("PFLOW assumptions", lambda manifest, _stats: manifest["pflow_contract"]["aggregation"].update(version="other")),
        ("evacuation assumptions", lambda manifest, _stats: manifest["evacuation_scenario"]["destinations"][0].update(operator="other")),
    ]
    for message, mutate in cases:
        manifest = read_json(manifest_path)
        stats = read_json(stats_path)
        mutate(manifest, stats)
        write_json(manifest_path, manifest)
        write_json(stats_path, stats)
        with pytest.raises(ValueError, match=message):
            report.load_checked_pair(dry_id, moderate_id)
        write_json(manifest_path, original_manifest)
        write_json(stats_path, original_stats)


def test_load_checked_pair_rejects_cross_aoi_and_failed_audit(
    published_pair: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dry_id, moderate_id = published_pair
    audited_run = report._audited_run
    monkeypatch.setattr(
        report, "_audited_run",
        lambda run_id: _as_aoi(audited_run(run_id), "bang-rak-district", "Bang Rak")
        if run_id == moderate_id else audited_run(run_id),
    )
    with pytest.raises(ValueError, match="AOI identity"):
        report.load_checked_pair(dry_id, moderate_id)

    denominators = _registered_json(
        dry_id, "denominators",
        lambda value: value["quantities"]["sample"].update(weight=1.0),
    )
    stats = read_json(report.RUNS_DIR / dry_id / "stats.json")
    stats["denominators"] = denominators
    write_json(report.RUNS_DIR / dry_id / "stats.json", stats)
    with pytest.raises(ValueError, match="audit failed"):
        report.load_checked_pair(dry_id, moderate_id)


def test_write_pair_evidence_is_complete_and_area_generic(
    published_pair: tuple[str, str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audited_run = report._audited_run
    monkeypatch.setattr(
        report, "_audited_run",
        lambda run_id: _as_aoi(audited_run(run_id), "bang-rak-district", "Bang Rak"),
    )
    pair = report.load_checked_pair(*published_pair)

    path = report.write_pair_evidence(pair, tmp_path)
    text = path.read_text(encoding="utf-8")

    assert path.name == "bang-rak-pair-evidence.md"
    assert text.startswith("# Bang Rak dry–moderate saved-pair evidence")
    assert "Khlong San" not in text
    assert all(value in text for value in (*published_pair, "bang-rak-district", "PASS"))
    assert all(f"`{code}`" in text for code in ("F", "S", "P", "E", "C", "A"))
    assert all(f"`{state}`" in text for state in replay_audit.TERMINAL_STATES)
    assert all(value in text for value in ("E/P", "p5", "p50", "p95", "residual_abs"))
    assert all(value in text for value in ("integerized", "hypothetical_unverified", "remaining"))
    assert all(value in text for value in ("0.78", "0.60", "0.90", "not executed"))
    assert all(value in text for value in (
        "sample-only", "no reweighting", "not a district or Bangkok total",
        "non-representative", "non-hydraulic", "uncalibrated", "not causal", "not operational",
        "not predictive", "not safety guidance", "incomplete sensitivity",
    ))
    manifest_hash = pair.dry.audit["audited_hashes"]["manifest.json"]
    assert manifest_hash in text
    assert pair.dry.bundle.manifest["code_identity"]["git_commit"] in text


@pytest.mark.parametrize("claim", [
    "isolates the flood term",
    "flood caused the change",
    "representative of Bangkok",
    "operationally safe",
    "predicts evacuation safety",
])
def test_pair_evidence_rejects_banned_claims(claim: str) -> None:
    with pytest.raises(ValueError, match="banned evidence claim"):
        report._validate_evidence_language(f"Result: {claim}.")


def test_comparison_figure_is_area_generic_and_noncausal(
    published_pair: tuple[str, str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audited_run = report._audited_run
    monkeypatch.setattr(
        report, "_audited_run",
        lambda run_id: _as_aoi(audited_run(run_id), "bang-rak-district", "Bang Rak"),
    )
    pair = report.load_checked_pair(*published_pair)
    captured: list[Any] = []
    subplots = report.plt.subplots

    def capture(*args, **kwargs):
        figure, axes = subplots(*args, **kwargs)
        captured.append(figure)
        return figure, axes

    monkeypatch.setattr(report.plt, "subplots", capture)
    comparison = report.figure_comparison(pair, tmp_path)
    overview = report.figure_scenario_overview(pair.moderate, tmp_path)
    present = report.figure_present_profile(pair.moderate, tmp_path)

    assert [paths[0].name for paths in (comparison, overview, present)] == [
        "bang-rak-dry-vs-moderate.png",
        "bang-rak-moderate-overview.png",
        "bang-rak-moderate-present-profile.png",
    ]
    for figure in captured:
        title = figure._suptitle.get_text() if figure._suptitle else ""
        figure_text = " ".join([title, *(item.get_text() for item in figure.texts)])
        assert "Bang Rak" in figure_text and "Khlong San" not in figure_text
        report._validate_evidence_language(figure_text)
    assert "within-model fixed-declared-assumption contrast" in " ".join(
        item.get_text() for item in captured[0].texts
    )


def test_overview_uses_hash_bound_run_aoi(
    published_pair: tuple[str, str], tmp_path: Path,
) -> None:
    pair = report.load_checked_pair(*published_pair)
    aoi_output = pair.moderate.bundle.outputs["aoi"]
    aoi_path = pair.moderate.bundle.run_dir / aoi_output["uri"]

    assert report.figure_scenario_overview(pair.moderate, tmp_path)[0].is_file()
    aoi_path.write_bytes(aoi_path.read_bytes() + b"changed-after-audit")
    with pytest.raises(ValueError, match="checked report artifact changed after audit: aoi"):
        report.figure_scenario_overview(pair.moderate, tmp_path)


def test_present_series_spatially_sums_each_original_timestamp() -> None:
    mesh = pd.DataFrame({
        "time_s": [0, 0, 600, 600, 3600, 3600],
        "total_pop": [10.0, 20.0, 12.0, 23.0, 15.0, 25.0],
    })
    activities = pd.DataFrame([
        {"person_id": "p1", "start_time_s": 0, "end_time_s": 600,
         "weight": 10.0},
        {"person_id": "p2", "start_time_s": 0, "end_time_s": 7200,
         "weight": 20.0},
        {"person_id": "p3", "start_time_s": 600, "end_time_s": 3600,
         "weight": 15.0},
        {"person_id": "p4", "start_time_s": 3600, "end_time_s": 7200,
         "weight": 20.0},
    ])

    series = report._present_series(mesh, activities)

    assert series["time_h"].tolist() == [0.0, 1 / 6, 1.0]
    assert series["total_pop"].tolist() == [30.0, 35.0, 40.0]

    duplicated_transition = mesh.copy()
    duplicated_transition.loc[duplicated_transition["time_s"] == 600, "total_pop"] += 5
    with pytest.raises(ValueError, match="does not conserve unique active people"):
        report._present_series(duplicated_transition, activities)


def test_publish_pair_report_is_atomic_and_pair_gated(
    published_pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_checked_pair = report.load_checked_pair
    scenario_overview = report.figure_scenario_overview
    present_profile = report.figure_present_profile
    comparison = report.figure_comparison
    pair = report.load_checked_pair(*published_pair)
    moderate_dir = pair.moderate.bundle.run_dir

    monkeypatch.setattr(
        report, "load_checked_pair",
        lambda *_args: (_ for _ in ()).throw(ValueError("pair mismatch")),
    )
    with pytest.raises(ValueError, match="pair mismatch"):
        report.publish_pair_report(*published_pair)
    assert not list(moderate_dir.glob("*pair-report*"))

    monkeypatch.setattr(report, "load_checked_pair", lambda *_args: pair)

    def placeholder(_value, directory: Path, name: str) -> list[Path]:
        path = directory / name
        path.write_bytes(b"not-a-real-png")
        return [path]

    monkeypatch.setattr(
        report, "figure_scenario_overview",
        lambda run, directory: placeholder(run, directory, "overview.png"),
    )
    monkeypatch.setattr(
        report, "figure_present_profile",
        lambda run, directory: placeholder(run, directory, "present.png"),
    )
    monkeypatch.setattr(
        report, "figure_comparison",
        lambda _pair, _directory: (_ for _ in ()).throw(RuntimeError("figure failed")),
    )
    with pytest.raises(RuntimeError, match="figure failed"):
        report.publish_pair_report(*published_pair)
    assert not list(moderate_dir.glob("*pair-report*"))

    monkeypatch.setattr(report, "load_checked_pair", load_checked_pair)
    monkeypatch.setattr(report, "figure_scenario_overview", scenario_overview)
    monkeypatch.setattr(report, "figure_present_profile", present_profile)
    monkeypatch.setattr(report, "figure_comparison", comparison)
    result = report.publish_pair_report(*reversed(published_pair))
    target = Path(result["report_dir"])
    assert target.is_dir() and result["audit_status"] == "PASS"
    assert all(Path(path).is_file() for path in [*result["figures"], result["evidence"]])
    assert all(Path(path).read_bytes().startswith(b"\x89PNG") for path in result["figures"])
    assert not list(moderate_dir.glob(".pair-report-*"))


def test_main_requires_exactly_two_runs_and_uses_atomic_publisher(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    called: list[tuple[str, str]] = []
    monkeypatch.setattr(
        report, "publish_pair_report",
        lambda first, second: called.append((first, second)) or {"report_dir": "saved"},
    )
    monkeypatch.setattr(sys, "argv", ["report.py", "run-a", "run-b"])
    assert report.main() == 0
    assert called == [("run-a", "run-b")]
    assert '"report_dir": "saved"' in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["report.py", "only-one"])
    with pytest.raises(SystemExit):
        report.main()


def test_publish_atomic_retries_a_transient_handle(tmp_path, monkeypatch):
    """A sync client holding the new directory must not lose the report.

    Measured on a Dropbox-synced tree: the rename is refused immediately and
    succeeds once the handle releases. Retrying preserves atomicity -- the
    rename itself is never replaced by a copy.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "figure.png").write_bytes(b"x" * 32)
    target = tmp_path / "published"

    calls = {"n": 0}
    real_replace = Path.replace

    def flaky(self, other):
        if self == scratch:
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError(32, "used by another process")
        return real_replace(self, other)

    monkeypatch.setattr(Path, "replace", flaky)
    monkeypatch.setattr(report.time, "sleep", lambda _seconds: None)

    report._publish_atomic(scratch, target)

    assert calls["n"] == 3, "must retry until the handle releases"
    assert target.is_dir() and (target / "figure.png").is_file()


def test_publish_atomic_gives_up_with_a_useful_message(tmp_path, monkeypatch):
    """A handle that never releases must name the real cause, not just fail."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    target = tmp_path / "published"

    def always_locked(self, other):
        raise PermissionError(32, "used by another process")

    monkeypatch.setattr(Path, "replace", always_locked)
    monkeypatch.setattr(report.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="could not be published after 3 attempts"):
        report._publish_atomic(scratch, target, attempts=3)
    assert not target.exists()


def test_cleanup_failure_does_not_mask_the_real_error(tmp_path, monkeypatch):
    """A failing cleanup must not replace the original exception.

    This previously hid the true cause: TemporaryDirectory.__exit__ raised
    PermissionError during removal and swallowed whatever the block had raised,
    which is why the real failure went undiagnosed for so long.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "figure.png").write_bytes(b"x")

    monkeypatch.setattr(Path, "replace", lambda self, other: (_ for _ in ()).throw(
        PermissionError(32, "used by another process")))
    monkeypatch.setattr(report.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        report.shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(
            PermissionError(5, "cleanup also failed"))
    )

    with pytest.raises(RuntimeError, match="could not be published"):
        report._publish_atomic(scratch, tmp_path / "published", attempts=2)
