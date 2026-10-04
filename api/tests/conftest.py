"""Test setup.

The runs directory is redirected through the environment, which is the same
mechanism the service uses in production. The repository root is put on
``sys.path`` so ``import api.app`` resolves no matter where pytest is invoked
from.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from api.runs import STATS_CACHE  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_stats_cache():
    """The stats cache is process-wide; isolate tests from each other's reads."""
    STATS_CACHE.clear()
    yield
    STATS_CACHE.clear()
