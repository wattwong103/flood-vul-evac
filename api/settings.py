"""Environment-driven settings.

Settings are read from the environment on every request rather than cached at
import time. A run under construction changes on disk between two requests, and
the test suite needs to relocate the runs directory mid-process; a snapshot
taken at import would silently serve the first location forever.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: ``api/settings.py`` -> ``api`` -> repository root.
REPO_ROOT = Path(__file__).resolve().parents[1]

#: Vite's dev server default. The site is a separate origin, so CORS is required.
DEFAULT_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

DEFAULT_MESH_ROW_LIMIT = 5_000
DEFAULT_LINK_FEATURE_LIMIT = 5_000
DEFAULT_BUILDING_ROW_LIMIT = 2_000
#: Hard ceiling on any caller-supplied ``limit`` so one request cannot ask the
#: service to materialise a whole run into memory.
MAX_ROW_LIMIT = 50_000


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if not raw:
        return default
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    return candidate


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """Resolved filesystem locations and cache sizing."""

    repo_root: Path
    runs_dir: Path
    data_dir: Path
    config_dir: Path
    cors_origins: tuple[str, ...]
    stats_cache_size: int
    stats_cache_ttl_seconds: float

    @property
    def source_registry_path(self) -> Path:
        return self.data_dir / "source-registry.json"

    @property
    def pilot_config_path(self) -> Path:
        return self.config_dir / "pilot.json"

    @property
    def city_config_path(self) -> Path:
        return self.config_dir / "pilot.city.json"

    @property
    def bangkok_aoi_path(self) -> Path:
        return self.data_dir / "curated" / "aoi" / "bangkok-bma.geojson"


def _cors_origins() -> tuple[str, ...]:
    raw = os.environ.get("BKKFLOW_CORS_ORIGINS", "").strip()
    if not raw:
        return DEFAULT_CORS_ORIGINS
    origins = tuple(part.strip() for part in raw.split(",") if part.strip())
    return origins or DEFAULT_CORS_ORIGINS


def get_settings() -> Settings:
    """Build a :class:`Settings` from the current environment."""
    repo_root = _env_path("BKKFLOW_REPO_ROOT", REPO_ROOT)
    return Settings(
        repo_root=repo_root,
        runs_dir=_env_path("BKKFLOW_RUNS_DIR", repo_root / "runs"),
        data_dir=_env_path("BKKFLOW_DATA_DIR", repo_root / "data"),
        config_dir=_env_path("BKKFLOW_CONFIG_DIR", repo_root / "config"),
        cors_origins=_cors_origins(),
        stats_cache_size=max(1, _env_int("BKKFLOW_STATS_CACHE_SIZE", 32)),
        stats_cache_ttl_seconds=max(
            0.0, _env_float("BKKFLOW_STATS_CACHE_TTL_S", 30.0)
        ),
    )
