"""Run discovery.

Scans ``runs/*/`` and resolves each run's ``manifest.json`` and ``run_state.json``.
The governing assumption is that a run directory is being written *right now*:
it may not exist yet, it may be half-populated, and a file may be truncated
mid-write. Every one of those cases degrades to a skipped run plus a logged
warning. Discovery never raises for a bad run directory, because one corrupt run
must not take the whole listing down.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from api.errors import RunNotFoundError
from api.models import ApiWarning
from api.settings import get_settings

LOGGER = logging.getLogger("bkkflow.api.runs")


def _first_str(source: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    return None

#: A run id is a directory name. Anything containing a separator or a parent
#: reference is rejected before it is ever joined onto a path.
_RUN_ID_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
)


@dataclass
class RunRef:
    """One resolvable run directory."""

    run_id: str
    path: Path
    manifest: dict[str, Any]
    run_state: dict[str, Any]
    warnings: list[ApiWarning] = field(default_factory=list)
    has_manifest: bool = True
    has_run_state: bool = True

    @property
    def created_at(self) -> str | None:
        value = self.manifest.get("created_at")
        if isinstance(value, str) and value:
            return value
        value = self.run_state.get("created_at")
        return value if isinstance(value, str) and value else None

    @property
    def validation_status(self) -> str | None:
        value = self.manifest.get("validation_status")
        if isinstance(value, str) and value:
            return value
        value = self.run_state.get("validation_status")
        return value if isinstance(value, str) and value else None

    @property
    def state(self) -> str | None:
        """Overall run state, e.g. ``running`` or ``failed_validation``."""
        return _first_str(self.run_state, ("state", "run_state", "status"))

    @property
    def stage(self) -> str | None:
        """The stage the run is on.

        A run_state may name the current stage directly, or only record an
        overall state. Falling back to the state keeps the summary column
        populated; the two are also reported separately so the site can tell
        "which stage" from "did it finish".
        """
        stage = _first_str(self.run_state, ("stage", "current_stage"))
        if stage:
            return stage
        return self.state

    @property
    def population_version(self) -> str | None:
        population_model = self.manifest.get("population_model")
        if isinstance(population_model, dict):
            value = population_model.get("population_version")
            if isinstance(value, str) and value:
                return value
        value = self.run_state.get("population_version")
        return value if isinstance(value, str) and value else None

    @property
    def warnings_count(self) -> int:
        """Warnings the run itself recorded, plus any this service added.

        ``run_state.warnings`` wins when present because the pipeline knows what
        it was worried about; the manifest list is the fallback.
        """
        state_warnings = self.run_state.get("warnings")
        if isinstance(state_warnings, list):
            return len(state_warnings)
        manifest_warnings = self.manifest.get("warnings")
        if isinstance(manifest_warnings, list):
            return len(manifest_warnings)
        return len(self.warnings)

    def sort_key(self) -> tuple[float, str]:
        """Newest first ordering key: parsed ``created_at``, else mtime."""
        stamp = _parse_iso(self.created_at)
        if stamp is None:
            try:
                stamp = self.path.stat().st_mtime
            except OSError:
                stamp = 0.0
        return (stamp, self.run_id)


def _parse_iso(value: str | None) -> float | None:
    """Best-effort ISO-8601 to epoch seconds. ``None`` when unparseable."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    try:
        if parsed.tzinfo is None:
            return parsed.timestamp()
        return parsed.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read a JSON object. Returns ``(payload, error)``; never raises."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "file not found"
    except OSError as exc:
        return None, f"unreadable: {exc.strerror or exc}"
    except UnicodeDecodeError as exc:
        return None, f"not valid UTF-8: {exc}"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON at line {exc.lineno} column {exc.colno}"
    if not isinstance(payload, dict):
        return None, f"expected a JSON object, found {type(payload).__name__}"
    return payload, None


def _load_run(path: Path, run_id: str | None = None) -> RunRef:
    """Resolve one run directory. Raises :class:`RunNotFoundError` only when the
    manifest is unusable, which is exactly the case the contract calls a 404."""
    resolved_id = run_id or path.name
    manifest, manifest_error = _read_json(path / "manifest.json")
    if manifest is None:
        # A directory with no manifest is not a run; a manifest that exists but
        # cannot be parsed is a broken run. Both are unresolvable by id.
        raise RunNotFoundError(
            resolved_id,
            f"run manifest unavailable for '{resolved_id}': {manifest_error}",
        )

    run_state, state_error = _read_json(path / "run_state.json")
    warnings: list[ApiWarning] = []
    if run_state is None:
        run_state = {}
        # A valid manifest with no run_state is a run still being started. It is
        # servable; the caller just needs to know progress is not known yet.
        warnings.append(
            ApiWarning(
                code="missing_run_state",
                message=(
                    "run_state.json is not readable yet; stage and progress are "
                    f"unavailable ({state_error})"
                ),
                artefact="run_state.json",
            )
        )
        LOGGER.warning("run %s: run_state.json unavailable (%s)", resolved_id, state_error)

    return RunRef(
        run_id=resolved_id,
        path=path,
        manifest=manifest,
        run_state=run_state,
        warnings=warnings,
        has_manifest=True,
        has_run_state=run_state is not None and bool(run_state),
    )


def discover_runs(runs_dir: Path | None = None) -> tuple[list[RunRef], list[str]]:
    """List resolvable runs newest first.

    Returns ``(runs, skipped_run_ids)``. ``skipped_run_ids`` names the
    directories that looked like runs but could not be read; the id is taken
    from the directory name so an operator can find and fix it on disk.
    """
    settings = get_settings()
    directory = runs_dir or settings.runs_dir
    if not directory.exists():
        LOGGER.info("runs directory %s does not exist yet", directory)
        return [], []

    try:
        candidates = sorted(p for p in directory.iterdir() if p.is_dir())
    except OSError as exc:
        LOGGER.warning("runs directory %s is not listable: %s", directory, exc)
        return [], []

    runs: list[RunRef] = []
    skipped: list[str] = []
    for candidate in candidates:
        if not (candidate / "manifest.json").exists():
            # Not a run directory yet. Common while a run is being staged.
            LOGGER.debug("skipping %s: no manifest.json", candidate.name)
            continue
        try:
            ref = _load_run(candidate)
        except RunNotFoundError as exc:
            LOGGER.warning("skipping run %s: %s", candidate.name, exc.message)
            skipped.append(candidate.name)
            continue
        except Exception as exc:  # defensive: one bad directory, never a 500
            LOGGER.warning("skipping run %s: unexpected error %r", candidate.name, exc)
            skipped.append(candidate.name)
            continue
        runs.append(ref)

    runs.sort(key=lambda run: run.sort_key(), reverse=True)
    return runs, skipped


def resolve_run(run_id: str) -> RunRef:
    """Resolve a single run id, or raise :class:`RunNotFoundError`."""
    if not run_id or len(run_id) > 128 or set(run_id) - _RUN_ID_CHARS or ".." in run_id:
        raise RunNotFoundError(str(run_id), f"run not found: {run_id!r}")

    settings = get_settings()
    path = settings.runs_dir / run_id
    # Refuse to serve a path that escapes the runs directory.
    try:
        path.resolve().relative_to(settings.runs_dir.resolve())
    except (ValueError, OSError):
        raise RunNotFoundError(run_id, f"run not found: {run_id}") from None

    if not path.is_dir():
        raise RunNotFoundError(run_id, f"run not found: {run_id}")

    try:
        return _load_run(path)
    except RunNotFoundError:
        raise
    except Exception as exc:  # defensive
        LOGGER.warning("run %s: unexpected error %r", run_id, exc)
        raise RunNotFoundError(run_id, f"run not found: {run_id}") from exc


class StatsCache:
    """In-process LRU+TTL cache for assembled stats payloads.

    Keyed by ``(run_id, stats_mtime)`` so a cached payload is invalidated the
    moment the pipeline rewrites ``stats.json`` -- mtime, not TTL, is the
    correctness signal; TTL only bounds how long an unchanged file is served
    from memory between polls. This exists so a site polling every few seconds
    during a run does not re-read and re-aggregate the same Parquet files.
    """

    def __init__(self, max_entries: int = 32, ttl_seconds: float = 30.0) -> None:
        self._max_entries = max(1, max_entries)
        self._ttl_seconds = max(0.0, ttl_seconds)
        self._entries: "OrderedDict[tuple[str, float], tuple[float, dict[str, Any]]]" = (
            OrderedDict()
        )
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple[str, float]) -> dict[str, Any] | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            stored_at, payload = entry
            if self._ttl_seconds and (now - stored_at) > self._ttl_seconds:
                del self._entries[key]
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return payload

    def put(self, key: tuple[str, float], payload: dict[str, Any]) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic(), payload)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def configure(self, max_entries: int, ttl_seconds: float) -> None:
        """Re-size the cache and drop anything held under the old sizing."""
        self._max_entries = max(1, max_entries)
        self._ttl_seconds = max(0.0, ttl_seconds)
        self.clear()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = 0
            self.misses = 0


#: Process-wide cache. A single instance is shared by every request handler so a
#: poll from one page warms the read for the next.
STATS_CACHE = StatsCache()


def stats_mtime(run_path: Path) -> float:
    """mtime of ``stats.json``, or ``0.0`` when it is absent.

    ``0.0`` is a legitimate cache key: it means "no stats.json exists", so an
    assembled payload is re-derived rather than served stale once the file lands.
    """
    try:
        return os.stat(run_path / "stats.json").st_mtime
    except OSError:
        return 0.0
