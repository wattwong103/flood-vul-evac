"""Pydantic response models.

Two rules shape this module:

1. Anything the pipeline owns (``stats.json``, ``validation.json``, the
   manifest, ``run_state.json``, the source registry) is passed through as
   ``dict`` rather than re-modelled. Re-modelling a pass-through artefact
   silently drops fields the contract has not frozen yet.
2. Anything this service composes is modelled, so a shape change breaks the
   tests instead of the site.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiWarning(BaseModel):
    """A structured, machine-readable warning.

    A missing artefact for one run is expected while a run is in flight, so it
    is reported as data the caller can render, not as an exception. ``code`` is
    stable and safe to switch on; ``message`` is for humans.
    """

    code: str
    message: str
    artefact: str | None = None


class ErrorResponse(BaseModel):
    """The contract's error envelope."""

    error: str
    run_id: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    contract_version: str
    runs_dir: str
    runs_dir_exists: bool
    run_count: int


class RunSummary(BaseModel):
    run_id: str
    created_at: str | None = None
    validation_status: str | None = None
    stage: str | None = None
    state: str | None = Field(
        default=None,
        description="Overall run state, e.g. 'running' or 'failed_validation'.",
    )
    population_version: str | None = None
    warnings_count: int = 0


class RunListResponse(BaseModel):
    count: int
    runs: list[RunSummary]
    skipped: list[str] = Field(
        default_factory=list,
        description="Run ids skipped because their manifest could not be read.",
    )
    warnings: list[ApiWarning] = Field(default_factory=list)


class RunDetailResponse(BaseModel):
    run_id: str
    run_state: dict[str, Any]
    manifest: dict[str, Any] | None = None
    manifest_available: bool = False
    warnings: list[ApiWarning] = Field(default_factory=list)


class MeshResponse(BaseModel):
    type: str = "FeatureCollection"
    features: list[dict[str, Any]] = Field(default_factory=list)
    run_id: str
    time_s: int | None = None
    time_defaulted: bool = False
    available_times: list[int] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    matched_rows: int = 0
    returned: int = 0
    truncated: bool = False
    limit: int = 0
    rows: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[ApiWarning] = Field(default_factory=list)


class LinksMeta(BaseModel):
    run_id: str
    time_s: int | None = None
    time_defaulted: bool = False
    mode: str | None = None
    matched_features: int = 0
    returned: int = 0
    truncated: bool = False
    limit: int = 0
    geometry_available: bool = False
    warnings: list[ApiWarning] = Field(default_factory=list)


class LinksResponse(BaseModel):
    """A GeoJSON FeatureCollection with a foreign ``meta`` member.

    RFC 7946 allows foreign members, so the payload stays a valid FeatureCollection
    while still carrying the truncation flag the site needs.
    """

    type: str = "FeatureCollection"
    features: list[dict[str, Any]] = Field(default_factory=list)
    meta: LinksMeta


class BuildingsMeta(BaseModel):
    run_id: str
    matched_rows: int = 0
    returned: int = 0
    truncated: bool = False
    limit: int = 0
    geometry_available: bool = False
    columns: list[str] = Field(default_factory=list)
    omitted_columns: list[str] = Field(default_factory=list)
    warnings: list[ApiWarning] = Field(default_factory=list)


class BuildingsResponse(BaseModel):
    type: str = "FeatureCollection"
    features: list[dict[str, Any]] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    meta: BuildingsMeta


class StateShare(BaseModel):
    state: str
    count: int
    weight: float | None = None
    share: float | None = None


class ClearanceTimes(BaseModel):
    """Clearance time in minutes. ``null`` where it could not be computed."""

    p5: float | None = None
    median: float | None = None
    p95: float | None = None


class EvacuationTotals(BaseModel):
    cohort_weighted: float | None = None
    arrived_weighted: float | None = None
    unserved_weighted: float | None = None
    stranded_weighted: float | None = None


class EvacuationResponse(BaseModel):
    run_id: str
    available: bool = False
    state_distribution: list[StateShare] = Field(default_factory=list)
    clearance_time_minutes: ClearanceTimes = Field(default_factory=ClearanceTimes)
    totals: EvacuationTotals = Field(default_factory=EvacuationTotals)
    denominators: dict[str, Any] | None = None
    warnings: list[ApiWarning] = Field(default_factory=list)


class ValidationResponse(BaseModel):
    run_id: str
    available: bool = False
    validation: dict[str, Any] | None = None
    warnings: list[ApiWarning] = Field(default_factory=list)


class ArtefactEntry(BaseModel):
    path: str
    size_bytes: int
    modified_at: str | None = None
    sha256: str | None = None
    sha256_source: str | None = Field(
        default=None,
        description="'sidecar' or 'manifest' when known, null otherwise.",
    )


class ExportResponse(BaseModel):
    run_id: str
    validation_status: str | None = None
    created_at: str | None = None
    manifest: dict[str, Any] | None = None
    artefact_count: int = 0
    total_bytes: int = 0
    truncated: bool = False
    limit: int = 0
    artefacts: list[ArtefactEntry] = Field(default_factory=list)
    warnings: list[ApiWarning] = Field(default_factory=list)


class AoiSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    aoi_id: str | None = None
    name: str | None = None
    name_en: str | None = None
    area_km2: float | None = None


class ConfigResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    aoi: AoiSummary = Field(default_factory=AoiSummary)
    analysis_crs: str | None = None
    storage_crs: str | None = None
    aggregation_grid: dict[str, Any] = Field(default_factory=dict)
    decision_status: str | None = None
    resolved_at: str | None = None
    scenario: dict[str, Any] = Field(default_factory=dict)
    warnings: list[ApiWarning] = Field(default_factory=list)
