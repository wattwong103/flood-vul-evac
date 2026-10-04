"""Record source bytes and reject persistent drift before run publication.

This is a before/after check, not process isolation: an edit restored between
checks is not detectable. Execute release runs from a quiescent checkout.
"""
import hashlib
import subprocess
from pathlib import Path
from .util import REPO_ROOT, read_json, utc_now_iso, write_json

SOURCE_PATHS = ("pipeline", "api", "config", "schemas", "data/source-registry.json", "pyproject.toml")
SOURCE_SUFFIXES = {".py", ".json", ".toml", ".txt", ".yaml", ".yml"}


def capture_code_identity(root: Path = REPO_ROOT) -> dict:
    files = set()
    for name in SOURCE_PATHS:
        path = root / name
        candidates = path.rglob("*") if path.is_dir() else [path]
        files.update(p for p in candidates if p.is_file() and p.suffix in SOURCE_SUFFIXES)
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    commit = tree = None
    status = "unavailable"
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True,
                                       stderr=subprocess.DEVNULL, timeout=10).strip()
    try:
        if Path(git("rev-parse", "--show-toplevel")).resolve() == root.resolve():
            commit, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
            status = "dirty" if git("status", "--porcelain", "--untracked-files=all", "--", *SOURCE_PATHS) else "clean"
    except (OSError, subprocess.SubprocessError):
        commit = tree = None
    return {"git_commit": commit, "git_tree": tree, "git_status": status,
            "source_sha256": digest.hexdigest(), "source_files": len(files),
            "scope": list(SOURCE_PATHS), "verification": "captured_before_run"}


def verify_code_identity(before: dict, run_dir: Path, root: Path = REPO_ROOT) -> dict:
    after = capture_code_identity(root)
    if before != after:
        state_path = run_dir / "run_state.json"
        state = read_json(state_path) if state_path.is_file() else {"run_id": run_dir.name}
        write_json(state_path, {**state, "state": "failed_source_changed", "updated_at": utc_now_iso(),
                               "error": "Source changed during execution; generate a new run."})
        raise RuntimeError("Source changed during execution; run publication refused")
    return {**before, "verification": "matched_before_publication"}
