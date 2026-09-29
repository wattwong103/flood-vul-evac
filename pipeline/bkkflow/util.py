"""Shared helpers: hashing, deterministic JSON, artefact IO and logging.

Reproducibility is a product requirement, not a nicety. Everything that
identifies an input or an output goes through this module so that a run can be
re-derived from its manifest alone.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

LOGGER_NAME = "bkkflow"

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
STAGED_DIR = DATA_DIR / "staged"
CURATED_DIR = DATA_DIR / "curated"
RUNS_DIR = REPO_ROOT / "runs"


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    """Return a configured stream logger.

    A single stream handler is attached so repeated module imports in one
    process (pytest, the API, the CLI) do not duplicate output.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%H:%M:%S")
        )
        logger.addHandler(handler)
    logger.setLevel(os.environ.get("BKKFLOW_LOG_LEVEL", "INFO").upper())
    return logger


LOGGER = get_logger()


def utc_now_iso() -> str:
    """Current UTC instant as an ISO-8601 string with an explicit offset."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(payload: Any) -> str:
    """Hash a JSON-serialisable object with sorted keys.

    Used for stage keys: identical inputs and parameters must produce an
    identical key so work can be reused instead of silently repeated.
    """
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def write_json(path: str | Path, payload: Any) -> Path:
    """Write UTF-8 JSON with stable key order and a trailing newline."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    target.write_text(text, encoding="utf-8")
    return target


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_jsonl(path: str | Path, rows: Iterable[Any]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def licence_snapshot_text(licence: str, licence_url: str | None = None) -> str:
    """A stable single-line snapshot value stored inside every manifest.

    The run manifest requires a licence snapshot. Storing a deterministic
    string keeps manifests diffable even when the terms page is later revised;
    the retrieval timestamp records when the claim was true.
    """
    if licence_url:
        return f"{licence} ({licence_url})"
    return licence
