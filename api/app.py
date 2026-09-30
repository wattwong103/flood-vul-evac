"""FastAPI application factory.

Read-only service over immutable run artefacts. Every handler is defensive by
design: a run directory being written concurrently, a truncated Parquet footer
or a missing table produces a structured warning in the response body, never a
500. A run that cannot be resolved at all produces the contract's 404 envelope.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import CONTRACT_VERSION, __version__
from api.errors import install_error_handlers
from api.models import (
    ApiWarning,
    BuildingsMeta,
    BuildingsResponse,
    ClearanceTimes,
    ConfigResponse,
    EvacuationResponse,
    EvacuationTotals,
    ExportResponse,
    ArtefactEntry,
    HealthResponse,
    LinksMeta,
    LinksResponse,
    MeshResponse,
    RunDetailResponse,
    RunListResponse,
    RunSummary,
    StateShare,
    ValidationResponse,
)
from api.runs import (
    STATS_CACHE,
    RunRef,
    discover_runs,
    resolve_run,
    stats_mtime,
)
from api.settings import (
    DEFAULT_BUILDING_ROW_LIMIT,
    DEFAULT_LINK_FEATURE_LIMIT,
    DEFAULT_MESH_ROW_LIMIT,
    MAX_ROW_LIMIT,
    Settings,
    get_settings,
)
from api.tables import (
    EVACUATION_ARRIVED_STATE,
    EVACUATION_NOT_ELIGIBLE_STATE,
    EVACUATION_UNSERVED_STATES,
    SENSITIVE_COLUMNS,
    _clearance_times,
    _SENSITIVE_SUBSTRINGS,
    artefact_path,
    assemble_stats,
    feature,
    jsonable,
    jsonable_rows,
    load_stats_file,
    make_warning,
    read_parquet,
    resolve_mesh_coordinates,
    wkt_to_geometry,
)
from api.models import AoiSummary

LOGGER = logging.getLogger("bkkflow.api")

MESH_ROW_COLUMNS = (
    "gcode",
    "lat",
    "lon",
    "time_s",
    "stationary_pop",
    "travelling_pop",
    "total_pop",
)
EDGE_STATE_COLUMNS = (
    "edge_id",
    "time_s",
    "mode",
    "depth_m",
    "speed_multiplier",
    "capacity_multiplier",
    "closed",
    "threshold_set_version",
    "reason_code",
)
EDGE_COLUMNS = (
    "edge_id",
    "u",
    "v",
    "length_m",
    "highway",
    "walk_allowed",
    "vehicle_allowed",
    "geometry_wkt",
)
LINK_VOLUME_COLUMNS = ("edge_id", "hour", "volume", "mode", "distance_m")
EVACUATION_COLUMNS = ("person_id", "state", "event_time_s", "weight", "dest_id")

#: PFLOW mode codes. The query accepts either the code or the name so the site
#: does not have to translate.
MODE_CODE_BY_NAME: dict[str, str] = {
    "walk": "0",
    "walking": "0",
    "bicycle": "1",
    "bike": "1",
    "bus": "2",
    "car": "3",
    "train": "4",
}

_BUILDING_GEOMETRY_COLUMNS = ("geometry_wkt", "wkt", "geom_wkt")


def get_ctx(request: Request) -> Settings:
    """Request-scoped settings: pinned at app creation, else from the environment."""
    pinned: Settings | None = getattr(request.app.state, "settings", None)
    return pinned or get_settings()


SettingsDep = Annotated[Settings, Depends(get_ctx)]


def _analysis_crs(run: "RunRef") -> str | None:
    """The CRS the run's stored geometry is in, from its own manifest.

    GeoJSON must be emitted in WGS84, so every geometry-served endpoint needs
    to know what the artefacts were written in.
    """
    geography = (run.manifest or {}).get("geography") or {}
    value = geography.get("analysis_crs")
    return str(value) if value else None


def _read_json_object(path: Path) -> tuple[dict[str, Any] | None, list[ApiWarning]]:
    name = path.name
    if not path.exists():
        return None, [
            make_warning("missing_artefact", f"{name} does not exist", name)
        ]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [
            make_warning("unreadable_artefact", f"{name} could not be read: {exc}", name)
        ]
    if not isinstance(payload, dict):
        return None, [
            make_warning("unreadable_artefact", f"{name} is not a JSON object", name)
        ]
    return payload, []


def _sidecar_digest(
    path: Path, manifest_hashes: dict[str, str]
) -> tuple[str | None, str | None]:
    """Resolve an artefact's sha256 from a sidecar file or the manifest.

    Only these two sources are consulted. Hashing the artefact itself is
    deliberately *not* an option here: ``persons.parquet`` and friends run to
    hundreds of megabytes, and an export endpoint that computes a digest would
    read every run directory in full. A run that needs a verified bundle
    produces sidecars when it writes.
    """
    sidecar = path.with_name(path.name + ".sha256")
    if sidecar.is_file():
        try:
            # Typical form is "<digest>  <filename>", as written by sha256sum.
            token = sidecar.read_text(encoding="utf-8", errors="replace").split()
            if token and re.fullmatch(r"[a-fA-F0-9]{64}", token[0]):
                return token[0].lower(), "sidecar"
        except OSError as exc:
            LOGGER.warning("cannot read sidecar %s: %s", sidecar.name, exc)
    digest = manifest_hashes.get(path.name)
    if digest:
        return digest, "manifest"
    return None, None


def _datetime_from_epoch(epoch: float) -> str | None:
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
    except (OverflowError, OSError, ValueError):
        return None


def _filter_by_mode(frame: pd.DataFrame, mode: str) -> pd.DataFrame:
    """Match a ``mode`` query against the stored code or its PFLOW name."""
    if "mode" not in frame.columns:
        return frame
    tokens = {mode.lower()}
    code = MODE_CODE_BY_NAME.get(mode.lower())
    if code:
        tokens.add(code)
    normalised = frame["mode"].astype(str).str.lower()
    return frame.loc[normalised.isin(tokens)]


def _resolve_time(
    frame: pd.DataFrame, time_s: int | None, column: str, prefer: str
) -> tuple[int | None, bool, list[ApiWarning]]:
    """Pick a time slice, defaulting to the first or last available one.

    Defaulting rather than erroring keeps the site usable against a run whose
    model clock does not start at midnight. The response says which time was
    served and that it was chosen by the API.
    """
    if column not in frame.columns or frame.empty:
        return time_s, False, []
    available = pd.to_numeric(frame[column], errors="coerce").dropna()
    if available.empty:
        return time_s, False, []
    if time_s is not None:
        return time_s, False, []
    chosen = float(available.min()) if prefer == "first" else float(available.max())
    return int(chosen), True, []


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    ``settings`` is optional; tests pass one to pin a synthetic runs directory.
    """
    resolved = settings or get_settings()
    app = FastAPI(
        title="BKK/FLOW run artefact API",
        version=__version__,
        description=(
            "Read-only service for immutable BKK/FLOW run artefacts. "
            f"Implements contract {CONTRACT_VERSION}."
        ),
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    install_error_handlers(app)
    STATS_CACHE.configure(
        max_entries=resolved.stats_cache_size, ttl_seconds=resolved.stats_cache_ttl_seconds
    )

    # ---------------------------------------------------------------- health

    @app.get("/v1/health", response_model=HealthResponse, tags=["service"])
    def health(ctx: SettingsDep) -> HealthResponse:
        runs, _ = discover_runs(ctx.runs_dir)
        return HealthResponse(
            status="ok",
            version=__version__,
            contract_version=CONTRACT_VERSION,
            runs_dir=str(ctx.runs_dir),
            runs_dir_exists=ctx.runs_dir.is_dir(),
            run_count=len(runs),
        )

    # --------------------------------------------------------------- sources

    @app.get("/v1/sources", tags=["provenance"])
    def get_sources(ctx: SettingsDep) -> dict[str, Any]:
        """Serve ``data/source-registry.json`` verbatim.

        A pass-through artefact: the registry is the licence record of record and
        this service does not reinterpret a licence.
        """
        payload, _ = _read_json_object(ctx.source_registry_path)
        if payload is None:
            return {
                "registry_version": None,
                "sources": [],
                "warnings": [
                    {
                        "code": "missing_artefact",
                        "message": (
                            f"source registry is unavailable at {ctx.source_registry_path}"
                        ),
                        "artefact": "source-registry.json",
                    }
                ],
            }
        payload.setdefault("sources", [])
        return payload

    # ----------------------------------------------------------------- runs

    @app.get("/v1/runs", response_model=RunListResponse, tags=["runs"])
    def list_runs(ctx: SettingsDep) -> RunListResponse:
        runs, skipped = discover_runs(ctx.runs_dir)
        summaries = [
            RunSummary(
                run_id=run.run_id,
                created_at=run.created_at,
                validation_status=run.validation_status,
                stage=run.stage,
                state=run.state,
                population_version=run.population_version,
                warnings_count=run.warnings_count,
            )
            for run in runs
        ]
        warnings = [
            make_warning(
                "skipped_run",
                f"run '{run_id}' was skipped because its manifest could not be read",
                "manifest.json",
            )
            for run_id in skipped
        ]
        return RunListResponse(
            count=len(summaries), runs=summaries, skipped=skipped, warnings=warnings
        )

    @app.get("/v1/runs/{run_id}", response_model=RunDetailResponse, tags=["runs"])
    def get_run(run_id: str, ctx: SettingsDep) -> RunDetailResponse:
        run = resolve_run(run_id)
        return RunDetailResponse(
            run_id=run.run_id,
            run_state=jsonable(run.run_state),
            manifest=jsonable(run.manifest),
            manifest_available=run.has_manifest,
            warnings=list(run.warnings),
        )

    @app.get("/v1/runs/{run_id}/stats", tags=["runs"])
    def get_stats(run_id: str, ctx: SettingsDep) -> dict[str, Any]:
        """The contract section 4 payload.

        Returned as a documented ``dict`` rather than a response model: when
        ``stats.json`` exists it is served verbatim, and a model would silently
        drop any field the pipeline adds before the contract is updated.
        """
        run = resolve_run(run_id)
        cache_key = (run.run_id, stats_mtime(run.path))
        cached = STATS_CACHE.get(cache_key)
        if cached is not None:
            return cached

        payload, _ = load_stats_file(run)
        if payload is None:
            pilot, _ = _read_json_object(ctx.pilot_config_path)
            registry, _ = _read_json_object(ctx.source_registry_path)
            payload = assemble_stats(run, pilot, registry)
        STATS_CACHE.put(cache_key, payload)
        return payload

    # ----------------------------------------------------------------- mesh

    @app.get("/v1/runs/{run_id}/mesh", response_model=MeshResponse, tags=["geometry"])
    def get_mesh(
        run_id: str,
        ctx: SettingsDep,
        time: Annotated[int | None, Query(ge=0, le=2_592_000)] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_ROW_LIMIT)] = DEFAULT_MESH_ROW_LIMIT,
    ) -> MeshResponse:
        """One time slice of ``mesh_volume.parquet`` as GeoJSON-ready rows."""
        run = resolve_run(run_id)
        warnings: list[ApiWarning] = []

        frame, read_warnings = read_parquet(artefact_path(run, "mesh_volume.parquet"))
        warnings.extend(read_warnings)
        if frame is None:
            return MeshResponse(
                run_id=run.run_id, limit=limit, rows=[], warnings=warnings
            )

        time_s, defaulted, time_warnings = _resolve_time(
            frame, time, "time_s", prefer="first"
        )
        warnings.extend(time_warnings)
        if time_s is not None and "time_s" in frame.columns:
            frame = frame.loc[
                pd.to_numeric(frame["time_s"], errors="coerce") == float(time_s)
            ]
        if time is not None and frame.empty and defaulted is False:
            warnings.append(
                make_warning(
                    "no_rows",
                    f"mesh_volume.parquet has no rows at time {time}s",
                    "mesh_volume.parquet",
                )
            )

        gcode_column = "gcode" if "gcode" in frame.columns else None
        if gcode_column is None:
            warnings.append(
                make_warning(
                    "schema_mismatch",
                    "mesh_volume.parquet has no gcode column; rows are returned "
                    "without a cell identifier",
                    "mesh_volume.parquet",
                )
            )
            lat = pd.Series([None] * len(frame), index=frame.index, dtype="object")
            lon = pd.Series([None] * len(frame), index=frame.index, dtype="object")
        else:
            lat, lon, coord_warnings = resolve_mesh_coordinates(run, frame, gcode_column)
            warnings.extend(coord_warnings)

        selected = pd.DataFrame(index=frame.index)
        for column in MESH_ROW_COLUMNS:
            if column in ("lat", "lon"):
                selected[column] = lat if column == "lat" else lon
            elif column in frame.columns:
                selected[column] = frame[column]

        matched = len(selected)
        truncated = matched > limit
        if truncated:
            selected = selected.head(limit)
            warnings.append(
                make_warning(
                    "truncated",
                    f"{matched - limit} mesh rows were dropped by the limit of {limit}",
                    "mesh_volume.parquet",
                )
            )

        return MeshResponse(
            run_id=run.run_id,
            time_s=time_s,
            time_defaulted=defaulted,
            columns=[column for column in MESH_ROW_COLUMNS if column in selected.columns],
            matched_rows=matched,
            returned=len(selected),
            truncated=truncated,
            limit=limit,
            rows=jsonable_rows(selected),
            warnings=warnings,
        )

    # ---------------------------------------------------------------- links

    @app.get("/v1/runs/{run_id}/links", response_model=LinksResponse, tags=["geometry"])
    def get_links(
        run_id: str,
        ctx: SettingsDep,
        time: Annotated[int | None, Query(ge=0, le=2_592_000)] = None,
        mode: Annotated[str | None, Query(max_length=32)] = None,
        limit: Annotated[
            int, Query(ge=1, le=MAX_ROW_LIMIT)
        ] = DEFAULT_LINK_FEATURE_LIMIT,
    ) -> LinksResponse:
        """Edge states joined to network geometry as a GeoJSON FeatureCollection."""
        run = resolve_run(run_id)
        warnings: list[ApiWarning] = []

        states, read_warnings = read_parquet(
            artefact_path(run, "edge_states.parquet"), columns=list(EDGE_STATE_COLUMNS)
        )
        warnings.extend(read_warnings)
        if states is None or states.empty:
            return LinksResponse(
                features=[],
                meta=LinksMeta(
                    run_id=run.run_id,
                    time_s=time,
                    mode=mode,
                    limit=limit,
                    geometry_available=False,
                    warnings=warnings,
                ),
            )

        if mode:
            states = _filter_by_mode(states, mode)

        time_s, defaulted, time_warnings = _resolve_time(
            states, time, "time_s", prefer="last"
        )
        warnings.extend(time_warnings)
        if time_s is not None and "time_s" in states.columns:
            states = states.loc[
                pd.to_numeric(states["time_s"], errors="coerce") == float(time_s)
            ]
        if time is not None and states.empty and not defaulted:
            # A model clock does not necessarily start at midnight, so an
            # explicit time outside the run's range must be reported, not
            # silently answered with an empty map.
            warnings.append(
                make_warning(
                    "no_rows",
                    f"edge_states.parquet has no rows at time {time}s",
                    "edge_states.parquet",
                )
            )

        # link_volume is keyed on hour, not seconds, so it joins to the slice's
        # whole hour. A null hour column is left absent rather than guessed.
        volumes, volume_warnings = read_parquet(
            artefact_path(run, "link_volume.parquet"), columns=list(LINK_VOLUME_COLUMNS)
        )
        warnings.extend(volume_warnings)
        if volumes is not None and not volumes.empty and time_s is not None:
            if "hour" in volumes.columns and "edge_id" in volumes.columns:
                hour = time_s // 3600
                volumes = volumes.loc[
                    pd.to_numeric(volumes["hour"], errors="coerce") == float(hour)
                ]
                if mode and "mode" in volumes.columns:
                    volumes = _filter_by_mode(volumes, mode)
                join_on = ["edge_id"] + (["mode"] if "mode" in states.columns and "mode" in volumes.columns else [])
                states = states.merge(volumes, on=join_on, how="left")
            else:
                warnings.append(
                    make_warning(
                        "schema_mismatch",
                        "link_volume.parquet has no edge_id/hour pair; volume was not joined",
                        "link_volume.parquet",
                    )
                )

        edges, edge_warnings = read_parquet(
            artefact_path(run, "network_edges.parquet"), columns=list(EDGE_COLUMNS)
        )
        warnings.extend(edge_warnings)
        geometry_available = False
        if edges is not None and not edges.empty and "edge_id" in edges.columns:
            states = states.merge(edges, on="edge_id", how="left")
            geometry_available = bool(states.get("geometry_wkt").notna().any())
        else:
            warnings.append(
                make_warning(
                    "missing_artefact",
                    "network_edges.parquet is unavailable; features are returned with "
                    "null geometry",
                    "network_edges.parquet",
                )
            )

        matched = len(states)
        truncated = matched > limit
        if truncated:
            states = states.head(limit)
            warnings.append(
                make_warning(
                    "truncated",
                    f"{matched - limit} edge features were dropped by the limit of {limit}",
                    "edge_states.parquet",
                )
            )

        features: list[dict[str, Any]] = []
        for record in states.to_dict(orient="records"):
            geometry = wkt_to_geometry(record.get("geometry_wkt"), _analysis_crs(run))
            properties = {
                key: value
                for key, value in record.items()
                if key not in ("geometry_wkt", "u", "v")
            }
            features.append(feature(geometry, properties))

        return LinksResponse(
            features=features,
            meta=LinksMeta(
                run_id=run.run_id,
                time_s=time_s,
                time_defaulted=defaulted,
                mode=mode,
                matched_features=matched,
                returned=len(features),
                truncated=truncated,
                limit=limit,
                geometry_available=geometry_available,
                warnings=warnings,
            ),
        )

    # ------------------------------------------------------------ buildings

    @app.get(
        "/v1/runs/{run_id}/buildings", response_model=BuildingsResponse, tags=["exposure"]
    )
    def get_buildings(
        run_id: str,
        ctx: SettingsDep,
        limit: Annotated[int, Query(ge=1, le=MAX_ROW_LIMIT)] = DEFAULT_BUILDING_ROW_LIMIT,
    ) -> BuildingsResponse:
        """Aggregated building exposure.

        The contract has no frozen column list for buildings.parquet, so the
        handler drops anything that looks person-level and reports what it
        dropped. No person-level field leaves the service from any endpoint.
        """
        run = resolve_run(run_id)
        warnings: list[ApiWarning] = []

        frame, read_warnings = read_parquet(artefact_path(run, "buildings.parquet"))
        warnings.extend(read_warnings)
        if frame is None:
            return BuildingsResponse(
                meta=BuildingsMeta(run_id=run.run_id, limit=limit, warnings=warnings)
            )

        columns = [str(column) for column in frame.columns]
        dropped = sorted(
            column
            for column in columns
            if column.lower() in SENSITIVE_COLUMNS
            or any(token in column.lower() for token in _SENSITIVE_SUBSTRINGS)
        )
        if dropped:
            frame = frame.drop(columns=[column for column in dropped if column in frame.columns])
            warnings.append(
                make_warning(
                    "columns_omitted",
                    f"person-level or protected columns were omitted: {dropped}",
                    "buildings.parquet",
                )
            )

        geometry_column = next(
            (column for column in _BUILDING_GEOMETRY_COLUMNS if column in frame.columns),
            None,
        )
        has_lon_lat = "lon" in frame.columns and "lat" in frame.columns
        geometry_available = bool(geometry_column) or has_lon_lat

        matched = len(frame)
        truncated = matched > limit
        if truncated:
            frame = frame.head(limit)
            warnings.append(
                make_warning(
                    "truncated",
                    f"{matched - limit} building rows were dropped by the limit of {limit}",
                    "buildings.parquet",
                )
            )

        features: list[dict[str, Any]] = []
        if geometry_available:
            for record in frame.to_dict(orient="records"):
                geometry = None
                if geometry_column:
                    geometry = wkt_to_geometry(record.get(geometry_column), _analysis_crs(run))
                elif has_lon_lat:
                    lon = record.get("lon")
                    lat = record.get("lat")
                    if lon is not None and lat is not None:
                        geometry = {
                            "type": "Point",
                            "coordinates": [jsonable(lon), jsonable(lat)],
                        }
                properties = {
                    key: value
                    for key, value in record.items()
                    if key not in _BUILDING_GEOMETRY_COLUMNS
                }
                features.append(feature(geometry, properties))
        else:
            warnings.append(
                make_warning(
                    "missing_geometry",
                    "buildings.parquet carries no geometry column; rows are returned "
                    "without a map layer",
                    "buildings.parquet",
                )
            )

        return BuildingsResponse(
            features=features,
            rows=[] if geometry_available else jsonable_rows(frame),
            meta=BuildingsMeta(
                run_id=run.run_id,
                matched_rows=matched,
                returned=len(features) if geometry_available else len(frame),
                truncated=truncated,
                limit=limit,
                geometry_available=geometry_available,
                columns=[str(column) for column in frame.columns],
                omitted_columns=dropped,
                warnings=warnings,
            ),
        )

    # ----------------------------------------------------------- evacuation

    @app.get(
        "/v1/runs/{run_id}/evacuation", response_model=EvacuationResponse, tags=["exposure"]
    )
    def get_evacuation(run_id: str, ctx: SettingsDep) -> EvacuationResponse:
        """State distribution, clearance percentiles and unserved/stranded totals."""
        run = resolve_run(run_id)
        warnings: list[ApiWarning] = []

        states, read_warnings = read_parquet(
            artefact_path(run, "evacuation_states.parquet"),
            columns=list(EVACUATION_COLUMNS),
        )
        warnings.extend(read_warnings)
        if states is None or states.empty or "state" not in states.columns:
            if states is not None and states.empty:
                # The table exists and is readable but holds no records. That is
                # a different finding from a missing table, and the site must not
                # render the two identically.
                warnings.append(
                    make_warning(
                        "empty_table",
                        "evacuation_states.parquet exists but contains no records; "
                        "no evacuation result was produced by this run",
                        "evacuation_states.parquet",
                    )
                )
            elif states is not None:
                warnings.append(
                    make_warning(
                        "schema_mismatch",
                        "evacuation_states.parquet has no state column",
                        "evacuation_states.parquet",
                    )
                )
            return EvacuationResponse(
                run_id=run.run_id, available=False, warnings=warnings
            )

        weights = (
            pd.to_numeric(states["weight"], errors="coerce")
            if "weight" in states.columns
            else None
        )
        total_weight = (
            float(weights.sum())
            if weights is not None and float(weights.sum()) > 0
            else None
        )

        distribution: list[StateShare] = []
        for state, group in states.groupby("state", dropna=True, sort=True):
            group_weights = (
                pd.to_numeric(group["weight"], errors="coerce")
                if "weight" in group.columns
                else None
            )
            weight = (
                float(group_weights.sum())
                if group_weights is not None and group_weights.notna().any()
                else None
            )
            share = (
                weight / total_weight
                if weight is not None and total_weight not in (None, 0.0)
                else None
            )
            distribution.append(
                StateShare(
                    state=str(state),
                    count=int(len(group)),
                    weight=weight,
                    share=share,
                )
            )

        cohort = arrived = unserved = stranded = None
        if total_weight is not None:

            def _sum(mask: pd.Series) -> float | None:
                subset = weights[mask]
                return float(subset.sum()) if subset.notna().any() else None

            cohort = _sum(states["state"] != EVACUATION_NOT_ELIGIBLE_STATE)
            arrived = _sum(states["state"] == EVACUATION_ARRIVED_STATE)
            unserved = _sum(states["state"].isin(EVACUATION_UNSERVED_STATES))
            stranded = _sum(states["state"] == "stranded")

        clearance = ClearanceTimes()
        if "event_time_s" in states.columns:
            times = _clearance_times(states, warnings)
            clearance = ClearanceTimes(**times)
        else:
            warnings.append(
                make_warning(
                    "schema_mismatch",
                    "evacuation_states.parquet has no event_time_s column; clearance "
                    "percentiles are null",
                    "evacuation_states.parquet",
                )
            )

        return EvacuationResponse(
            run_id=run.run_id,
            available=True,
            state_distribution=distribution,
            clearance_time_minutes=clearance,
            totals=EvacuationTotals(
                cohort_weighted=cohort,
                arrived_weighted=arrived,
                unserved_weighted=unserved,
                stranded_weighted=stranded,
            ),
            warnings=warnings,
        )

    # ----------------------------------------------------------- validation

    @app.get(
        "/v1/runs/{run_id}/validation", response_model=ValidationResponse, tags=["runs"]
    )
    def get_validation(run_id: str, ctx: SettingsDep) -> ValidationResponse:
        """Serve ``validation.json`` verbatim: checks, thresholds and results."""
        run = resolve_run(run_id)
        payload, warnings = _read_json_object(artefact_path(run, "validation.json"))
        if payload is None:
            return ValidationResponse(
                run_id=run.run_id, available=False, validation=None, warnings=warnings
            )
        return ValidationResponse(
            run_id=run.run_id, available=True, validation=payload, warnings=[]
        )

    # --------------------------------------------------------------- export

    @app.get("/v1/runs/{run_id}/export", response_model=ExportResponse, tags=["runs"])
    def get_export(
        run_id: str,
        ctx: SettingsDep,
        limit: Annotated[int, Query(ge=1, le=MAX_ROW_LIMIT)] = MAX_ROW_LIMIT,
    ) -> ExportResponse:
        """Manifest plus an inventory of the run directory.

        Only metadata is listed. Contents are never streamed: a run can hold
        hundreds of megabytes of Parquet, and this endpoint describes the bundle
        rather than shipping it. sha256 values are only reported when a sidecar
        file or the manifest already records one, so no large file is read here.
        """
        run = resolve_run(run_id)
        warnings: list[ApiWarning] = []

        manifest_hashes: dict[str, str] = {}
        for output in run.manifest.get("outputs", []) or []:
            if not isinstance(output, dict):
                continue
            uri = output.get("uri")
            digest = output.get("content_sha256")
            if isinstance(uri, str) and isinstance(digest, str):
                manifest_hashes[Path(uri).name] = digest

        artefacts: list[ArtefactEntry] = []
        total_bytes = 0
        truncated = False
        try:
            found = sorted(
                (path for path in run.path.rglob("*") if path.is_file()),
                key=lambda path: path.relative_to(run.path).as_posix(),
            )
        except OSError as exc:
            LOGGER.warning("run %s: cannot list artefacts: %s", run.run_id, exc)
            found = []
            warnings.append(
                make_warning(
                    "unreadable_artefact",
                    f"the run directory could not be listed: {exc}",
                )
            )

        for path in found:
            relative = path.relative_to(run.path).as_posix()
            try:
                stat = path.stat()
            except OSError:
                continue
            total_bytes += stat.st_size
            if len(artefacts) >= limit:
                truncated = True
                continue

            digest, source = _sidecar_digest(path, manifest_hashes)
            artefacts.append(
                ArtefactEntry(
                    path=relative,
                    size_bytes=int(stat.st_size),
                    modified_at=_datetime_from_epoch(stat.st_mtime),
                    sha256=digest,
                    sha256_source=source,
                )
            )

        if truncated:
            warnings.append(
                make_warning(
                    "truncated",
                    f"the artefact list was capped at {limit} entries",
                )
            )

        return ExportResponse(
            run_id=run.run_id,
            validation_status=run.validation_status,
            created_at=run.created_at,
            manifest=jsonable(run.manifest),
            artefact_count=len(found),
            total_bytes=total_bytes,
            truncated=truncated,
            limit=limit,
            artefacts=artefacts,
            warnings=warnings,
        )

    # --------------------------------------------------------------- config

    @app.get("/v1/config", response_model=ConfigResponse, tags=["service"])
    def get_config(ctx: SettingsDep) -> ConfigResponse:
        """Pilot AOI, CRS, aggregation grid and the declared scenario status."""
        pilot, warnings = _read_json_object(ctx.pilot_config_path)
        if pilot is None:
            return ConfigResponse(warnings=warnings)

        aoi_raw = pilot.get("aoi") if isinstance(pilot.get("aoi"), dict) else {}
        grid = pilot.get("aggregation_grid")
        runs, _ = discover_runs(ctx.runs_dir)

        scenario: dict[str, Any] = {
            "declared": False,
            "pilot_decision_status": pilot.get("decision_status"),
            "model_name": None,
            "model_version": None,
            "time_step_seconds": None,
            "runs_declaring_scenario": 0,
            "latest_run_id": None,
        }
        declaring = 0
        for run in runs:
            scenario_block = run.manifest.get("flood_scenario")
            if not isinstance(scenario_block, dict):
                continue
            declaring += 1
            scenario.update(
                {
                    "model_name": scenario_block.get("model_name"),
                    "model_version": scenario_block.get("model_version"),
                    "time_step_seconds": scenario_block.get("time_step_seconds"),
                    "latest_run_id": run.run_id,
                }
            )
        scenario["declared"] = declaring > 0
        scenario["runs_declaring_scenario"] = declaring
        if not declaring:
            warnings.append(
                make_warning(
                    "no_scenario_declared",
                    "no run in this runs directory declares a flood scenario",
                )
            )

        return ConfigResponse(
            aoi=AoiSummary(
                aoi_id=aoi_raw.get("aoi_id"),
                name=aoi_raw.get("name"),
                name_en=aoi_raw.get("name_en"),
                area_km2=(
                    float(aoi_raw["area_km2"])
                    if isinstance(aoi_raw.get("area_km2"), (int, float))
                    and not isinstance(aoi_raw.get("area_km2"), bool)
                    else None
                ),
                **{k: v for k, v in aoi_raw.items() if k not in {"aoi_id", "name", "name_en", "area_km2"}},
            ),
            analysis_crs=pilot.get("analysis_crs"),
            storage_crs=pilot.get("storage_crs"),
            aggregation_grid=jsonable(grid) if isinstance(grid, dict) else {},
            decision_status=pilot.get("decision_status"),
            resolved_at=pilot.get("resolved_at"),
            scenario=scenario,
            warnings=warnings,
        )

    @app.get("/v1/runs/{run_id}/population-grid")
    def get_population_grid(
        run_id: str,
        ctx: SettingsDep,
        limit: Annotated[int, Query(ge=1, le=MAX_ROW_LIMIT)] = DEFAULT_MESH_ROW_LIMIT,
    ) -> dict[str, Any]:
        """The aggregated resident baseline on its public reporting grid.

        City runs publish a 1 km grid rather than a 100 m mesh, so this is a
        distinct artefact from the pilot's ``mesh_volume.parquet``. The
        aggregation conserves the population total exactly, which the run's own
        validation report checks.
        """
        run = resolve_run(run_id)
        warnings: list[ApiWarning] = []
        frame, read_warnings = read_parquet(artefact_path(run, "population_grid_1km.parquet"))
        warnings.extend(read_warnings)
        if frame is None:
            return {
                "run_id": run.run_id,
                "available": False,
                "rows": [],
                "matched_rows": 0,
                "returned": 0,
                "truncated": False,
                "limit": limit,
                "warnings": [
                    make_warning(
                        "artefact_missing",
                        "this run has no population_grid_1km.parquet; pilot runs publish "
                        "mesh_volume.parquet instead, served by /mesh",
                        "population_grid_1km.parquet",
                    )
                ],
            }

        matched = len(frame)
        truncated = matched > limit
        if truncated:
            frame = frame.head(limit)
            warnings.append(
                make_warning(
                    "truncated",
                    f"{matched - limit} grid cells were dropped by the limit of {limit}",
                    "population_grid_1km.parquet",
                )
            )
        return {
            "run_id": run.run_id,
            "available": True,
            "grid_size_m": 1000,
            "quantity": "resident_baseline",
            "quantity_note": (
                "Residents per cell. This is a resident baseline, not a time-of-day "
                "population, and it is never summed with exposed or cohort figures."
            ),
            "columns": [str(column) for column in frame.columns],
            "matched_rows": matched,
            "returned": int(len(frame)),
            "truncated": truncated,
            "limit": limit,
            "rows": jsonable_rows(frame),
            "warnings": warnings,
        }

    @app.get("/v1/runs/{run_id}/observed-water")
    def get_observed_water(run_id: str, ctx: SettingsDep) -> dict[str, Any]:
        """Observed surface-water extent, when the run carries an observation.

        This is the only hazard layer in the project that is measured rather
        than modelled or declared. It reports **extent**, never depth, and a
        yearly composite cannot resolve within-year timing. Both facts are
        repeated in the payload so a client cannot present it as a forecast.
        """
        run = resolve_run(run_id)
        warnings: list[ApiWarning] = []
        payload, json_warnings = _read_json_object(artefact_path(run, "observed_water.json"))
        warnings.extend(json_warnings)
        if payload is None:
            return {
                "run_id": run.run_id,
                "available": False,
                "is_observation": False,
                "years": [],
                "warnings": [
                    make_warning(
                        "artefact_missing",
                        "this run has no observed_water.json; it carries no observed hazard layer",
                        "observed_water.json",
                    )
                ],
            }
        return {
            "run_id": run.run_id,
            "available": payload.get("status") == "ok",
            "status": payload.get("status"),
            "is_observation": True,
            "source_id": payload.get("source_id"),
            "licence": payload.get("licence"),
            "product": payload.get("product"),
            "measures": payload.get("measures"),
            "baseline_year": payload.get("baseline_year"),
            "years": jsonable(payload.get("years", [])),
            "unavailable_years": jsonable(payload.get("unavailable_years", [])),
            "interpretation_notes": payload.get("interpretation_notes", []),
            "note": payload.get("note"),
            "warnings": warnings,
        }

    @app.get("/v1/runs/{run_id}/observed-water/cells")
    def get_observed_water_cells(
        run_id: str,
        ctx: SettingsDep,
        year: int | None = Query(default=None),
        min_share: float = Query(default=0.05, ge=0.0, le=1.0),
        limit: Annotated[int, Query(ge=1, le=MAX_ROW_LIMIT)] = DEFAULT_MESH_ROW_LIMIT,
    ) -> dict[str, Any]:
        """Observed water as 1 km cells, ready for the map.

        Aggregated to the same fixed 1 km public grid as the population layer,
        because the source 30 m classification would otherwise mean hundreds of
        thousands of points. `min_share` filters the long tail of cells with a
        handful of water pixels, which otherwise hides the real pattern.
        """
        run = resolve_run(run_id)
        warnings: list[ApiWarning] = []
        frame, read_warnings = read_parquet(
            ctx.data_dir / "curated" / "city" / "observed_water_cells.parquet"
        )
        warnings.extend(read_warnings)
        if frame is None:
            return {
                "type": "FeatureCollection",
                "features": [],
                "available": False,
                "warnings": [
                    make_warning(
                        "artefact_missing",
                        "no observed_water_cells.parquet has been staged; run "
                        "pipeline/build_observed_cells.py to build it from the cached tiles",
                        "observed_water_cells.parquet",
                    )
                ],
            }

        years = sorted(int(value) for value in frame["year"].unique())
        available_years = years
        if year is not None:
            if year not in years:
                warnings.append(
                    make_warning(
                        "year_not_available",
                        f"{year} is not among the staged years {years}; the wettest staged year is used",
                        "observed_water_cells.parquet",
                    )
                )
            else:
                frame = frame[frame["year"] == year]
        if frame.empty:
            frame = pd.read_parquet(ctx.data_dir / "curated" / "city" / "observed_water_cells.parquet")
            frame = frame[frame["year"] == max(years)]

        filtered = frame[frame["water_share"] >= min_share]
        if filtered.empty:
            filtered = frame

        matched = len(filtered)
        truncated = matched > limit
        if truncated:
            filtered = filtered.sort_values("water_km2", ascending=False).head(limit)
            warnings.append(
                make_warning(
                    "truncated",
                    f"{matched - limit} cells were dropped by the limit of {limit}, keeping the wettest",
                    "observed_water_cells.parquet",
                )
            )

        features = [
            feature(
                {"type": "Point", "coordinates": [float(row.lon), float(row.lat)]},
                {
                    "cell_id": row.cell_id,
                    "year": int(row.year),
                    "water_share": float(row.water_share),
                    "water_km2": float(row.water_km2),
                    "source_role": "observed",
                    "measures": "extent_only",
                },
            )
            for row in filtered.itertuples()
        ]
        return {
            "type": "FeatureCollection",
            "available": True,
            "run_id": run.run_id,
            "grid_size_m": 1000,
            "is_observation": True,
            "measures": "water extent, NOT depth, duration or direction",
            "available_years": available_years,
            "year": int(filtered["year"].iloc[0]) if len(filtered) else None,
            "min_share": min_share,
            "matched_rows": matched,
            "returned": len(features),
            "truncated": truncated,
            "features": features,
            "warnings": warnings,
        }

    @app.get("/v1/runs/{run_id}/destinations")
    def get_destinations(
        run_id: str,
        ctx: SettingsDep,
        limit: Annotated[int, Query(ge=1, le=MAX_ROW_LIMIT)] = DEFAULT_BUILDING_ROW_LIMIT,
        destination_class: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Destination candidates recovered from OSM tags.

        Every record is unverified. ``verified_count`` is reported prominently so
        a client cannot present an ``amenity=shelter`` tag as a refuge by
        omission.
        """
        run = resolve_run(run_id)
        warnings: list[ApiWarning] = []
        frame, read_warnings = read_parquet(
            ctx.data_dir / "curated" / "city" / "destinations.parquet"
        )
        warnings.extend(read_warnings)
        if frame is None:
            return {
                "run_id": run.run_id,
                "available": False,
                "rows": [],
                "matched_rows": 0,
                "returned": 0,
                "truncated": False,
                "verified_count": 0,
                "warnings": [
                    make_warning(
                        "artefact_missing",
                        "destination candidates are staged in data/curated/city/destinations.parquet "
                        "and were not produced for this run",
                        "destinations.parquet",
                    )
                ],
            }

        if destination_class:
            frame = frame[frame["destination_class"] == destination_class]
        matched = len(frame)
        truncated = matched > limit
        if truncated:
            frame = frame.head(limit)
            warnings.append(
                make_warning(
                    "truncated",
                    f"{matched - limit} destination rows were dropped by the limit of {limit}",
                    "destinations.parquet",
                )
            )
        return {
            "run_id": run.run_id,
            "available": True,
            "matched_rows": matched,
            "returned": int(len(frame)),
            "truncated": truncated,
            "limit": limit,
            "verified_count": 0,
            "verified_note": (
                "Zero records are verified. An OSM tag is a mapping decision, not an "
                "operational guarantee: none carries an operator, a capacity or an "
                "inspection date, and none may be presented as a refuge."
            ),
            "by_class": {
                str(key): int(value)
                for key, value in frame["destination_class"].value_counts().items()
            },
            "rows": jsonable_rows(frame),
            "warnings": warnings,
        }

    @app.get("/v1/runs/{run_id}/network")
    def get_network(
        run_id: str,
        ctx: SettingsDep,
        limit: Annotated[int, Query(ge=1, le=MAX_ROW_LIMIT)] = DEFAULT_MESH_ROW_LIMIT,
    ) -> dict[str, Any]:
        """Network summary, plus a bounded, evenly spaced sample of edges.

        A city run holds close to a million edges, so full geometry is not
        served. The sample is deterministic rather than random, so repeated
        calls return the same edges and the map does not shimmer.
        """
        run = resolve_run(run_id)
        warnings: list[ApiWarning] = []
        stats_payload, stats_warnings = load_stats_file(run)
        warnings.extend(stats_warnings)
        network_block = (stats_payload or {}).get("network", {})

        frame, read_warnings = read_parquet(artefact_path(run, "network_edges.parquet"))
        warnings.extend(read_warnings)
        sampled_rows: list[dict[str, Any]] = []
        matched = 0
        if frame is not None and "geometry_wkt" in frame.columns:
            matched = len(frame)
            step = max(matched // max(limit, 1), 1)
            sample = frame.iloc[::step].head(limit)
            for record in sample.to_dict(orient="records"):
                geometry = wkt_to_geometry(record.get("geometry_wkt"), _analysis_crs(run))
                if geometry is None:
                    continue
                sampled_rows.append(
                    feature(
                        geometry,
                        {
                            "edge_id": record.get("edge_id"),
                            "length_m": record.get("length_m"),
                            "highway": record.get("highway"),
                            "walk_allowed": record.get("walk_allowed"),
                            "vehicle_allowed": record.get("vehicle_allowed"),
                        },
                    )
                )
            if matched > len(sampled_rows):
                warnings.append(
                    make_warning(
                        "sampled",
                        f"{matched:,} edges exist; {len(sampled_rows):,} evenly spaced edges are "
                        "returned for display. City-scale edge geometry is not served in full.",
                        "network_edges.parquet",
                    )
                )
        return {
            "run_id": run.run_id,
            "available": bool(network_block) or frame is not None,
            "summary": jsonable(network_block),
            "matched_rows": matched,
            "returned": len(sampled_rows),
            "sample_is_spatial_subset": True,
            "features": sampled_rows,
            "warnings": warnings,
        }

    @app.get("/", include_in_schema=False)
    def root() -> JSONResponse:
        return JSONResponse(
            {
                "service": "bkk-flow-api",
                "version": __version__,
                "contract_version": CONTRACT_VERSION,
                "docs": "/docs",
                "health": "/v1/health",
            }
        )

    return app


#: Module-level app for ``uvicorn api.app:app``.
app = create_app()
