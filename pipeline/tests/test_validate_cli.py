"""``run.py validate`` without ``--run-id`` never silently lands on a sensitivity case."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow.util import write_json


def _validated_run(root: Path, run_id: str, age_s: int, case_id: str | None) -> None:
    active = {"state": "moderate", "configured_scenario_id": "configured"}
    manifest = {"run_id": run_id}
    if case_id is not None:
        manifest["active_scenario"] = {**active, "case_id": case_id}
    elif run_id != "legacy":
        manifest["active_scenario"] = active
    write_json(root / run_id / "manifest.json", manifest)
    validation = write_json(root / run_id / "validation.json", {"run_id": run_id, "passed": True})
    stamp = 1_700_000_000 - age_s
    os.utime(validation, (stamp, stamp))


# Manifests a run can be left with when it is cut off mid-write or hand-edited;
# ``None`` deletes the manifest.
UNREADABLE_MANIFESTS = {
    "torn": b'{"run_id": "torn", "active_scenario": {"case_id": "delay-me',
    "list-valued": b'[{"run_id": "torn"}]',
    "not-utf-8": b'{"run_id": "\xff"}',
    "nested-too-deep": b"[" * 5000 + b"]" * 5000,
    "missing": None,
}


def _unreadable_run(root: Path, run_id: str, age_s: int, kind: str) -> None:
    _validated_run(root, run_id, age_s, None)
    manifest = root / run_id / "manifest.json"
    raw = UNREADABLE_MANIFESTS[kind]
    if raw is None:
        manifest.unlink()
    else:
        manifest.write_bytes(raw)


def _validate_without_run_id(cli, root: Path, monkeypatch, capsys) -> tuple[str, str]:
    """Run ``run.py validate`` against ``root``; return the picked run id and stderr."""
    monkeypatch.setattr(cli, "RUNS_DIR", root)
    monkeypatch.setattr(sys, "argv", ["run.py", "validate"])
    assert cli.main() == 0
    out, err = capsys.readouterr()
    return json.loads(out)["run_id"], err


@pytest.mark.parametrize(("runs", "picked", "note"), [
    ([("ordinary", 20, None), ("legacy", 30, None), ("case-b", 10, "delay-mean-1800")],
     "ordinary", "newest run with no sensitivity case recorded"),
    ([("legacy", 30, None), ("case-a", 10, "compliance-0.60")],
     "legacy", "newest run with no sensitivity case recorded"),
    ([("case-a", 20, "compliance-0.60"), ("case-b", 10, "delay-mean-1800")],
     "case-b", "sensitivity case 'delay-mean-1800'; no ordinary run found"),
])
def test_validate_defaults_to_the_newest_ordinary_run(
    tmp_path, monkeypatch, capsys, runs, picked, note,
):
    import run as cli

    for run_id, age_s, case_id in runs:
        _validated_run(tmp_path, run_id, age_s, case_id)

    run_id, err = _validate_without_run_id(cli, tmp_path, monkeypatch, capsys)
    assert run_id == picked
    assert f"validating run {picked} ({note})" in err


@pytest.mark.parametrize("kind", UNREADABLE_MANIFESTS)
def test_validate_prefers_a_known_ordinary_run_to_a_newer_unreadable_one(
    tmp_path, monkeypatch, capsys, kind,
):
    import run as cli

    _unreadable_run(tmp_path, "unreadable", 10, kind)
    _validated_run(tmp_path, "case-b", 20, "delay-mean-1800")
    _validated_run(tmp_path, "ordinary", 30, None)

    run_id, err = _validate_without_run_id(cli, tmp_path, monkeypatch, capsys)
    assert run_id == "ordinary"
    assert "validating run ordinary (newest run with no sensitivity case recorded)" in err


@pytest.mark.parametrize("kind", UNREADABLE_MANIFESTS)
def test_validate_prefers_an_unreadable_run_to_a_newer_case_run(
    tmp_path, monkeypatch, capsys, kind,
):
    import run as cli

    _validated_run(tmp_path, "case-b", 10, "delay-mean-1800")
    _unreadable_run(tmp_path, "unreadable", 20, kind)
    _unreadable_run(tmp_path, "unreadable-older", 30, kind)

    run_id, err = _validate_without_run_id(cli, tmp_path, monkeypatch, capsys)
    assert run_id == "unreadable"
    assert (
        "validating run unreadable (manifest unreadable, so its sensitivity case is"
        " unknown; no ordinary run found)"
    ) in err


@pytest.mark.parametrize("active_scenario", [["moderate"], "moderate"])
def test_validate_counts_a_readable_manifest_with_an_odd_active_scenario_as_ordinary(
    tmp_path, monkeypatch, capsys, active_scenario,
):
    """As in ``api/runs.py``, whose ``active_scenario`` summary is null for such a run."""
    import run as cli

    _validated_run(tmp_path, "case-b", 10, "delay-mean-1800")
    _unreadable_run(tmp_path, "unreadable", 15, "torn")
    _validated_run(tmp_path, "odd-scenario", 20, None)
    write_json(
        tmp_path / "odd-scenario" / "manifest.json",
        {"run_id": "odd-scenario", "active_scenario": active_scenario},
    )

    run_id, err = _validate_without_run_id(cli, tmp_path, monkeypatch, capsys)
    assert run_id == "odd-scenario"
    assert "validating run odd-scenario (newest run with no sensitivity case recorded)" in err


def test_validate_reports_no_runs_and_keeps_an_explicit_run_id(tmp_path, monkeypatch, capsys):
    import run as cli

    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run.py", "validate"])
    assert cli.main() == 1
    assert "no runs found" in capsys.readouterr().err

    _validated_run(tmp_path, "ordinary", 20, None)
    _validated_run(tmp_path, "case-b", 10, "delay-mean-1800")
    monkeypatch.setattr(sys, "argv", ["run.py", "validate", "--run-id", "case-b"])
    assert cli.main() == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["run_id"] == "case-b"
    assert err == ""
