"""Source ingestion: registry gate, OSM extracts and population rasters."""

from __future__ import annotations

from .registry import (  # noqa: F401
    APPROVED,
    REJECTED,
    VERIFY,
    LicenceGateError,
    Source,
    SourceRegistry,
    load_registry,
)

__all__ = [
    "APPROVED",
    "REJECTED",
    "VERIFY",
    "LicenceGateError",
    "Source",
    "SourceRegistry",
    "load_registry",
]
