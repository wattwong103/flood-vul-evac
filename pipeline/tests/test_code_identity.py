"""Source changes must be detected before a run becomes visible as published."""
import subprocess
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bkkflow.code_identity import capture_code_identity, verify_code_identity
from bkkflow.util import read_json


def source_tree(tmp_path):
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "pipeline/run.py").write_text("print('baseline')\n")
    return tmp_path


def test_content_identity_is_available_without_git(tmp_path):
    root = source_tree(tmp_path)
    before = capture_code_identity(root)
    assert before["git_commit"] is None
    assert before["git_tree"] is None
    assert before["git_status"] == "unavailable"
    assert len(before["source_sha256"]) == 64
    assert verify_code_identity(before, tmp_path / "run", root)["verification"] == "matched_before_publication"


@pytest.mark.parametrize("change", ["edit", "add", "delete"])
def test_changed_source_blocks_publication_and_records_failure(tmp_path, change):
    root = source_tree(tmp_path)
    before = capture_code_identity(root)
    if change == "edit":
        (root / "pipeline/run.py").write_text("print('changed')\n")
    elif change == "add":
        (root / "pipeline/new.py").write_text("x = 1\n")
    else:
        (root / "pipeline/run.py").unlink()
    run = tmp_path / "run"
    run.mkdir()
    with pytest.raises(RuntimeError, match="Source changed"):
        verify_code_identity(before, run, root)
    assert read_json(run / "run_state.json")["state"] == "failed_source_changed"
    assert not (run / "manifest.json").exists()


def test_git_identity_ignores_generated_outputs_but_detects_source_edits(tmp_path):
    root = source_tree(tmp_path)
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
    git("init", "-q")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "add", "pipeline")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
    before = capture_code_identity(root)
    assert before["git_commit"] == git("rev-parse", "HEAD")
    assert before["git_tree"] == git("rev-parse", "HEAD^{tree}")
    assert before["git_status"] == "clean"
    (root / "data").mkdir()
    (root / "data/generated.json").write_text("{}")
    assert capture_code_identity(root) == before
    (root / "pipeline/run.py").write_text("print('edited')\n")
    assert capture_code_identity(root)["git_status"] == "dirty"


def test_manifest_code_identity_requires_verified_digest(tmp_path):
    from jsonschema import Draft202012Validator
    from bkkflow.manifest import load_schema
    validator = Draft202012Validator(load_schema()["properties"]["code_identity"])
    identity = capture_code_identity(source_tree(tmp_path))
    assert list(validator.iter_errors(identity))  # a capture alone is not verified
    verified = verify_code_identity(identity, tmp_path / "run", tmp_path)
    assert not list(validator.iter_errors(verified))
    verified["source_sha256"] = "invalid"
    assert list(validator.iter_errors(verified))
