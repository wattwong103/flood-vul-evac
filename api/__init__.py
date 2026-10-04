"""BKK/FLOW read-only API service.

Serves immutable run artefacts described by ``docs/RUN_ARTIFACT_CONTRACT.md``
(contract ``bkkflow-run-v0.1``) to the Vite site. The service is strictly
read-only: it never writes into ``runs/`` and it never recomputes a metric the
pipeline is responsible for producing.

Run it from the repository root::

    python -m uvicorn api.app:app --reload --port 8000

The environment variables below all exist so tests can point the service at a
synthetic runs directory without touching the real one.
"""

from __future__ import annotations

__all__ = ["__version__", "CONTRACT_VERSION"]

__version__ = "0.1.0"

#: Frozen contract version this service implements. Kept in one place so the
#: site can assert that it is not talking to an incompatible service.
CONTRACT_VERSION = "bkkflow-run-v0.1"
