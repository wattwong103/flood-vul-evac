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
    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run.py", "validate"])

    assert cli.main() == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["run_id"] == picked
    assert f"validating run {picked} ({note})" in err


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
