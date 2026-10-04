"""Parquet access, GeoJSON construction and stats assembly.

Three rules hold throughout this module:

* A missing, empty or unreadable artefact is a warning, never an exception. A run
  in flight legitimately lacks half its tables.
* A value that cannot be computed is ``None``. A ``0.0`` asserts that something
  was measured and found to be zero, which is a different and stronger claim.
* No endpoint returns person-level data. Aggregates only.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from api.models import ApiWarning
from api.runs import RunRef
from pipeline.bkkflow.clearance import (
    EMPTY_CLEARANCE_MINUTES,
    weighted_clearance_minutes,
)

LOGGER = logging.getLogger("bkkflow.api.tables")

#: Columns that must never leave the service. The contract allows no person-level
#: export; buildings.parquet has no frozen column list, so a denylist plus a
#: substring check is the honest guard. Whatever is dropped is reported back in
#: ``omitted_columns`` rather than dropped silently.
SENSITIVE_COLUMNS: frozenset[str] = frozenset(
    {
        "person_id",
        "weight",
        "age_band",
        "sex_code",
        "sex",
        "dob",
        "date_of_birth",
        "name",
        "home_cell_id",
        "home_building_id",
        "mobility_profile",
        "household_id",
        "income",
        "protected",
        "sampled",
        "trip_id",
        "sequence",
        "purpose",
        "dest_id",
    }
)
_SENSITIVE_SUBSTRINGS = ("person", "household", "individual", "protected", "person_")

EVACUATION_UNSERVED_STATES: frozenset[str] = frozenset(
    {"stranded", "shelter_full", "route_failed", "did_not_depart"}
)
EVACUATION_ARRIVED_STATE = "arrived"
EVACUATION_NOT_ELIGIBLE_STATE = "not_eligible"


def make_warning(
    code: str, message: str, artefact: str | None = None
) -> ApiWarning:
    return ApiWarning(code=code, message=message, artefact=artefact)


def jsonable(value: Any) -> Any:
    """Convert numpy/pandas scalars to plain JSON, mapping NaN and inf to None.

    NaN is not valid JSON. A float column holding one missing value would
    otherwise serialise as the bare token ``NaN`` and break the site parser;
    ``None`` is both valid JSON and the honest encoding of "no measurement".
    """
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (str, int, np.integer)):
        return int(value) if isinstance(value, (np.integer,)) else value
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.ndarray):
        return [jsonable(item) for item in value.tolist()]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if value is pd.NaT:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def jsonable_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Render a DataFrame as a list of plain JSON-safe dicts."""
    return [
        {str(column): jsonable(row[column]) for column in frame.columns}
        for row in frame.to_dict(orient="records")
    ]


# --------------------------------------------------------------------------
# Parquet reading
# --------------------------------------------------------------------------


def parquet_columns(path: Path) -> list[str]:
    """Column names from Parquet footer metadata, or ``[]`` when unreadable.

    Reading the footer first keeps the common path cheap: a request can decide
    whether its filter applies without loading the file at all.
    """
    try:
        return list(pq.ParquetFile(path).schema_arrow.names)
    except Exception as exc:  # noqa: BLE001 - any pyarrow failure is a warning
        LOGGER.warning("cannot read parquet footer for %s: %r", path.name, exc)
        return []


def read_parquet(
    path: Path,
    *,
    columns: Sequence[str] | None = None,
    filters: list[tuple] | None = None,
) -> tuple[pd.DataFrame | None, list[ApiWarning]]:
    """Read a Parquet table, degrading to a warning on any failure.

    Returns ``(frame_or_None, warnings)``. ``None`` means the table could not be
    read at all; an empty frame means it was read and is empty, which the caller
    must not confuse with a missing table.
    """
    name = path.name
    if not path.exists():
        return None, [
            make_warning(
                "missing_artefact", f"{name} is not present in this run", name
            )
        ]

    available = parquet_columns(path)
    if not available:
        return None, [
            make_warning(
                "unreadable_artefact", f"{name} could not be opened as Parquet", name
            )
        ]

    selected: list[str] | None = None
    if columns is not None:
        selected = [column for column in columns if column in available]
        if not selected:
            return None, [
                make_warning(
                    "schema_mismatch",
                    f"{name} has none of the expected columns "
                    f"{sorted(columns)}; found {sorted(available)}",
                    name,
                )
            ]

    warnings: list[ApiWarning] = []
    frame: pd.DataFrame | None = None
    if filters:
        try:
            frame = pd.read_parquet(path, columns=selected, filters=filters)
        except Exception as exc:  # noqa: BLE001
            # Row-group statistics can be absent, or a column can be dictionary
            # encoded in a way the filter engine dislikes. A full read plus an
            # in-memory filter is slower but always correct.
            LOGGER.info("pushdown filter failed for %s (%r); reading in full", name, exc)
            try:
                frame = pd.read_parquet(path, columns=selected)
            except Exception as inner:  # noqa: BLE001
                return None, [
                    make_warning(
                        "unreadable_artefact",
                        f"{name} could not be read: {inner}",
                        name,
                    )
                ]
    else:
        try:
            frame = pd.read_parquet(path, columns=selected)
        except Exception as exc:  # noqa: BLE001
            return None, [
                make_warning(
                    "unreadable_artefact", f"{name} could not be read: {exc}", name
                )
            ]

    return frame, warnings


def artefact_path(run: RunRef, filename: str) -> Path:
    return run.path / filename


# --------------------------------------------------------------------------
# GeoJSON
# --------------------------------------------------------------------------


def wkt_to_geometry(
    wkt: Any, source_crs: str | None = None
) -> dict[str, Any] | None:
    """WKT to a GeoJSON geometry mapping, reprojected to WGS84.

    GeoJSON is defined in WGS84 longitude/latitude by RFC 7946, but the pipeline
    stores geometry in the run's analysis CRS, which is UTM metres for Bangkok.
    Serving stored coordinates directly would place every feature hundreds of
    kilometres from its true position, so projected geometry is transformed on
    the way out.

    `source_crs=None` passes coordinates through unchanged, which is correct
    for a run already stored in a geographic CRS.
    """
    if not isinstance(wkt, str) or not wkt.strip():
        return None
    try:
        from shapely import wkt as shapely_wkt

        geometry = shapely_wkt.loads(wkt)
    except Exception as exc:  # noqa: BLE001
        LOGGER.info("unparseable geometry skipped: %r", exc)
        return None
    if geometry is None or geometry.is_empty:
        return None

    if source_crs:
        try:
            from pyproj import Transformer
            from shapely.ops import transform as shapely_transform

            transformer = Transformer.from_crs(source_crs, "OGC:CRS84", always_xy=True)
            geometry = shapely_transform(transformer.transform, geometry)
        except Exception as exc:  # noqa: BLE001
            LOGGER.info("reprojection from %s failed, passing through: %r", source_crs, exc)

    interface = geometry.__geo_interface__
    if not isinstance(interface, dict):
        return None
    return jsonable(interface)



def feature(
    geometry: dict[str, Any] | None, properties: dict[str, Any]
) -> dict[str, Any]:
    """A single GeoJSON Feature. ``geometry: null`` is valid and used when the
    run has no geometry table; attributes are still worth returning."""
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": jsonable(properties),
    }


# --------------------------------------------------------------------------
# Coordinate resolution for mesh cells
# --------------------------------------------------------------------------


_MESH_COORD_COLUMN_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("centroid_lat", "centroid_lon"),
    ("lat", "lon"),
    ("latitude", "longitude"),
)
#: A cell-centre lookup is not part of the frozen contract, so the API looks for
#: one of these and otherwise returns null coordinates rather than inventing a
#: point from a gcode.
_MESH_COORD_TABLE_CANDIDATES: tuple[str, ...] = (
    "mesh_cells.parquet",
    "mesh_lookup.parquet",
    "gcode_lookup.parquet",
)


def resolve_mesh_coordinates(
    run: RunRef, frame: pd.DataFrame, gcode_column: str
) -> tuple[pd.Series, pd.Series, list[ApiWarning]]:
    """Latitude/longitude for each mesh row.

    ``mesh_volume.parquet`` is frozen with ``gcode`` but no coordinates, so the
    lat/lon the endpoint must return has to come from somewhere. Order of
    preference: coordinates already in the table, then a cell-centre lookup table
    in the run directory. If neither exists the coordinates are ``None`` and a
    warning says so -- a gcode is an identifier, not a position.
    """
    rows = len(frame)
    warnings: list[ApiWarning] = []
    empty = pd.Series([None] * rows, index=frame.index, dtype="object")

    for lat_name, lon_name in _MESH_COORD_COLUMN_CANDIDATES:
        if lat_name in frame.columns and lon_name in frame.columns:
            return frame[lat_name], frame[lon_name], warnings

    if gcode_column in frame.columns:
        for candidate in _MESH_COORD_TABLE_CANDIDATES:
            table_path = artefact_path(run, candidate)
            if not table_path.exists():
                continue
            lookup, lookup_warnings = read_parquet(table_path)
            if lookup is None or lookup.empty:
                warnings.extend(lookup_warnings)
                continue
            lat_column = next(
                (name for name, _ in _MESH_COORD_COLUMN_CANDIDATES if name in lookup.columns),
                None,
            )
            lon_column = next(
                (name for _, name in _MESH_COORD_COLUMN_CANDIDATES if name in lookup.columns),
                None,
            )
            if lat_column is None or lon_column is None or gcode_column not in lookup.columns:
                warnings.append(
                    make_warning(
                        "schema_mismatch",
                        f"{candidate} has no gcode/lat/lon triple; ignored",
                        candidate,
                    )
                )
                continue
            lookup = lookup[[gcode_column, lat_column, lon_column]].drop_duplicates(
                subset=[gcode_column]
            )
            merged = frame[[gcode_column]].merge(
                lookup, on=gcode_column, how="left"
            )
            missing = int(merged[lat_column].isna().sum())
            if missing:
                warnings.append(
                    make_warning(
                        "unmatched_rows",
                        f"{missing} mesh rows had no cell centre in {candidate}; "
                        "their coordinates are null",
                        candidate,
                    )
                )
            merged.index = frame.index
            return merged[lat_column], merged[lon_column], warnings

    warnings.append(
        make_warning(
            "missing_geometry",
            "no cell-centre coordinates are available for mesh_volume; lat and lon "
            "are null for every row",
            "mesh_volume.parquet",
        )
    )
    return empty, empty, warnings


# --------------------------------------------------------------------------
# Statistics assembly
# --------------------------------------------------------------------------


def _sum_or_none(series: pd.Series) -> float | None:
    if series is None or len(series) == 0:
        return None
    try:
        total = float(pd.to_numeric(series, errors="coerce").sum())
    except (TypeError, ValueError):
        return None
    return total if math.isfinite(total) else None


def _percentile_or_none(values: np.ndarray, percentile: float) -> float | None:
    if values.size == 0:
        return None
    value = float(np.percentile(values, percentile))
    return value if math.isfinite(value) else None


def _first_str(source: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def load_stats_file(run: RunRef) -> tuple[dict[str, Any] | None, list[ApiWarning]]:
    """Read a pipeline-written ``stats.json`` verbatim."""
    path = artefact_path(run, "stats.json")
    if not path.exists():
        return None, [
            make_warning(
                "missing_artefact",
                "stats.json is not present; the payload was assembled from the "
                "manifest and the available tables",
                "stats.json",
            )
        ]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        return None, [
            make_warning(
                "unreadable_artefact",
                f"stats.json could not be read ({exc}); the payload was assembled "
                "from the manifest and the available tables",
                "stats.json",
            )
        ]
    except json.JSONDecodeError as exc:
        return None, [
            make_warning(
                "unreadable_artefact",
                f"stats.json is invalid JSON at line {exc.lineno} column {exc.colno}; "
                "the payload was assembled from the manifest and the available tables",
                "stats.json",
            )
        ]
    if not isinstance(payload, dict):
        return None, [
            make_warning(
                "unreadable_artefact",
                "stats.json is not a JSON object; the payload was assembled from "
                "the manifest and the available tables",
                "stats.json",
            )
        ]
    return payload, []


def empty_stats_skeleton(run: RunRef) -> dict[str, Any]:
    """The contract section 4 shape with every derivable value null.

    Returning the full key set with nulls is deliberate: the site can render a
    "not measured" state for each field instead of showing a zero it would
    otherwise have to guess at.
    """
    return {
        "run_id": run.run_id,
        "validation_status": run.validation_status,
        "created_at": run.created_at,
        "geography": {
            "aoi_id": None,
            "name": None,
            "area_km2": None,
            "analysis_crs": None,
        },
        "population": {
            "residents_weighted": None,
            "people_present": None,
            "people_exposed": None,
            "exposed_share_of_present": None,
            "population_version": None,
            "time_profile": None,
        },
        "flood": {
            "max_depth_m": None,
            "flooded_area_km2": None,
            "edges_closed": None,
            "edges_total": None,
            "road_capacity_loss_share": None,
            "source_role": None,
            "model": {"name": None, "version": None},
        },
        "evacuation": {
            "cohort_weighted": None,
            "arrived_weighted": None,
            "unserved_weighted": None,
            "clearance_time_minutes": {"p5": None, "median": None, "p95": None},
            "top_bottleneck_edges": [],
        },
        "stages": [],
        "warnings": [],
        "sources": [],
    }


def _geography(run: RunRef, pilot: dict[str, Any] | None) -> dict[str, Any]:
    """Geography block. Area and name are not in the manifest schema, so they
    come from ``config/pilot.json`` and only when the aoi_id matches -- pairing
    a manifest with another district's area would be a fabricated number."""
    manifest_geography = run.manifest.get("geography")
    manifest_geography = (
        manifest_geography if isinstance(manifest_geography, dict) else {}
    )
    block = empty_stats_skeleton(run)["geography"]
    block["aoi_id"] = _first_str(manifest_geography, ("aoi_id",))
    block["analysis_crs"] = _first_str(manifest_geography, ("analysis_crs",))

    aoi = pilot.get("aoi") if isinstance(pilot, dict) else None
    if isinstance(aoi, dict) and aoi.get("aoi_id") == block["aoi_id"]:
        block["name"] = _first_str(aoi, ("name", "name_en"))
        area = aoi.get("area_km2")
        if isinstance(area, (int, float)) and not isinstance(area, bool):
            block["area_km2"] = float(area)
    elif block["aoi_id"] is not None and aoi is not None:
        LOGGER.info(
            "run %s aoi %s does not match the configured aoi; area and name left null",
            run.run_id,
            block["aoi_id"],
        )
    return block


def _population_block(
    run: RunRef, warnings: list[ApiWarning]
) -> dict[str, Any]:
    """Residents, people present and people exposed, as three distinct values.

    ``people_present`` counts people represented inside the AOI at model time;
    ``people_exposed`` counts those of them located in a cell with modelled water.
    The two are never summed: a zero-exposure evening and a 40 percent exposure
    evening have the same present population and very different risk.
    """
    block = empty_stats_skeleton(run)["population"]
    population_model = run.manifest.get("population_model")
    population_model = (
        population_model if isinstance(population_model, dict) else {}
    )
    block["population_version"] = _first_str(population_model, ("population_version",))
    time_profile = population_model.get("time_profile")
    if isinstance(time_profile, dict):
        # The contract vocabulary is day|evening|night; the manifest's
        # `status` field is a different vocabulary (illustrative|calibrated|
        # validated) and is not copied into this slot.
        block["time_profile"] = _first_str(time_profile, ("profile", "period", "scenario"))

    persons, person_warnings = read_parquet(
        artefact_path(run, "persons.parquet"), columns=["person_id", "weight"]
    )
    warnings.extend(person_warnings)
    if persons is None or persons.empty or "weight" not in persons.columns:
        if persons is not None and "weight" not in persons.columns:
            warnings.append(
                make_warning(
                    "schema_mismatch",
                    "persons.parquet has no weight column; weighted totals are null",
                    "persons.parquet",
                )
            )
        block["residents_weighted"] = None
        block["people_present"] = None
        return block

    block["residents_weighted"] = _sum_or_none(persons["weight"])

    weights = persons.set_index("person_id")["weight"] if "person_id" in persons.columns else None
    activities, activity_warnings = read_parquet(
        artefact_path(run, "activities.parquet"),
        columns=["person_id", "gcode", "lon", "lat", "start_time_s", "duration_s"],
    )
    warnings.extend(activity_warnings)
    if activities is None or activities.empty or "person_id" not in activities.columns:
        block["people_present"] = None
        return block

    present_ids = set(activities["person_id"].dropna().unique())
    if weights is not None:
        present_weight = weights[weights.index.isin(present_ids)]
        block["people_present"] = _sum_or_none(present_weight)
    else:
        block["people_present"] = None

    block["people_exposed"], _ = _exposed_weight(
        run, activities, weights, warnings
    )
    present = block["people_present"]
    exposed = block["people_exposed"]
    if present is not None and exposed is not None and present > 0:
        block["exposed_share_of_present"] = exposed / present
    return block


def _exposed_weight(
    run: RunRef,
    activities: pd.DataFrame,
    weights: pd.Series | None,
    warnings: list[ApiWarning],
) -> tuple[float | None, str | None]:
    """Weighted people in an activity cell that carries modelled water."""
    slices, slice_warnings = read_parquet(
        artefact_path(run, "flood_slices.parquet"),
        columns=["cell_id", "time_s", "depth_m"],
    )
    warnings.extend(slice_warnings)
    if slices is None or slices.empty or "cell_id" not in slices.columns:
        return None, None
    depth_column = "depth_m" if "depth_m" in slices.columns else None
    if depth_column is None:
        warnings.append(
            make_warning(
                "schema_mismatch",
                "flood_slices.parquet has no depth_m column; exposure is null",
                "flood_slices.parquet",
            )
        )
        return None, None

    flooded_cells = set(
        slices.loc[
            pd.to_numeric(slices[depth_column], errors="coerce").fillna(0.0) > 0.0,
            "cell_id",
        ].dropna()
    )
    if not flooded_cells:
        # Cells exist and none are wet. Zero is a real measurement here.
        return 0.0, None

    if "gcode" not in activities.columns:
        warnings.append(
            make_warning(
                "schema_mismatch",
                "activities.parquet has no gcode column, so activity locations "
                "cannot be matched to flood cells; exposure is null",
                "activities.parquet",
            )
        )
        return None, None

    exposed_ids = set(
        activities.loc[activities["gcode"].isin(flooded_cells), "person_id"].dropna()
    )
    if weights is None:
        return None, None
    return _sum_or_none(weights[weights.index.isin(exposed_ids)]), None


def _flood_block(run: RunRef, warnings: list[ApiWarning]) -> dict[str, Any]:
    block = empty_stats_skeleton(run)["flood"]
    scenario = run.manifest.get("flood_scenario")
    scenario = scenario if isinstance(scenario, dict) else {}
    block["model"] = {
        "name": _first_str(scenario, ("model_name", "name")),
        "version": _first_str(scenario, ("model_version", "version")),
    }

    slices, slice_warnings = read_parquet(
        artefact_path(run, "flood_slices.parquet"),
        columns=["cell_id", "depth_m", "source_role"],
    )
    warnings.extend(slice_warnings)
    if slices is not None and not slices.empty:
        if "depth_m" in slices.columns:
            depths = pd.to_numeric(slices["depth_m"], errors="coerce").dropna()
            if not depths.empty:
                block["max_depth_m"] = float(depths.max())
        if "source_role" in slices.columns:
            roles = sorted({str(role) for role in slices["source_role"].dropna()})
            if len(roles) == 1:
                block["source_role"] = roles[0]
            elif roles:
                # Mixed provenance is a real finding, not a missing value.
                block["source_role"] = "mixed:" + ",".join(roles)

    block["flooded_area_km2"] = _flooded_area(run, slices, warnings)

    edges, edge_warnings = read_parquet(
        artefact_path(run, "network_edges.parquet"), columns=["edge_id"]
    )
    warnings.extend(edge_warnings)
    if edges is not None and "edge_id" in edges.columns:
        block["edges_total"] = int(edges["edge_id"].nunique())

    states, state_warnings = read_parquet(
        artefact_path(run, "edge_states.parquet"),
        columns=["edge_id", "closed", "capacity_multiplier"],
    )
    warnings.extend(state_warnings)
    if states is not None and not states.empty and "edge_id" in states.columns:
        if "closed" in states.columns:
            closed = states["closed"].fillna(False).astype(bool)
            block["edges_closed"] = int(states.loc[closed, "edge_id"].nunique())
        if "capacity_multiplier" in states.columns:
            multiplier = pd.to_numeric(
                states["capacity_multiplier"], errors="coerce"
            ).dropna()
            if not multiplier.empty:
                share = 1.0 - float(multiplier.mean())
                block["road_capacity_loss_share"] = min(1.0, max(0.0, share))
    return block


def _flooded_area(
    run: RunRef, slices: pd.DataFrame | None, warnings: list[ApiWarning]
) -> float | None:
    """Flooded area from the reporting grid size.

    Area needs a cell size. ``mesh_volume.parquet`` carries ``mesh_size_m``; the
    number of distinct wet cells times the cell area is the only derivation the
    artefacts support, so anything else stays null.
    """
    if slices is None or slices.empty or "cell_id" not in slices.columns:
        return None
    mesh, mesh_warnings = read_parquet(
        artefact_path(run, "mesh_volume.parquet"), columns=["gcode", "mesh_size_m"]
    )
    warnings.extend(mesh_warnings)
    if mesh is None or mesh.empty or "mesh_size_m" not in mesh.columns:
        return None

    sizes = pd.to_numeric(mesh["mesh_size_m"], errors="coerce").dropna()
    if sizes.empty:
        return None
    mesh_size_m = float(sizes.max())
    if mesh_size_m <= 0:
        return None

    wet = slices
    if "depth_m" in slices.columns:
        wet = slices.loc[
            pd.to_numeric(slices["depth_m"], errors="coerce").fillna(0.0) > 0.0
        ]
    wet_cells = set(wet["cell_id"].dropna())
    if not wet_cells:
        # Depth was measured and no cell is wet: zero is a measurement.
        return 0.0

    grid_cells = set(mesh["gcode"].dropna())
    if grid_cells:
        matched = wet_cells & grid_cells
        if matched:
            wet_cells = matched
        else:
            warnings.append(
                make_warning(
                    "unmatched_rows",
                    "flood cell ids do not intersect the reporting grid; flooded "
                    "area is null rather than estimated from a foreign grid",
                    "flood_slices.parquet",
                )
            )
            return None

    cell_area_km2 = (mesh_size_m / 1000.0) ** 2
    return len(wet_cells) * cell_area_km2


def _evacuation_block(run: RunRef, warnings: list[ApiWarning]) -> dict[str, Any]:
    block = empty_stats_skeleton(run)["evacuation"]
    states, state_warnings = read_parquet(
        artefact_path(run, "evacuation_states.parquet"),
        columns=["person_id", "state", "event_time_s", "weight"],
    )
    warnings.extend(state_warnings)
    if states is None or states.empty or "state" not in states.columns:
        return block

    weights = (
        pd.to_numeric(states["weight"], errors="coerce")
        if "weight" in states.columns
        else None
    )
    if weights is not None and weights.notna().any():
        eligible = states["state"] != EVACUATION_NOT_ELIGIBLE_STATE
        block["cohort_weighted"] = _sum_or_none(weights[eligible])
        arrived = states["state"] == EVACUATION_ARRIVED_STATE
        block["arrived_weighted"] = _sum_or_none(weights[arrived])
        unserved = states["state"].isin(EVACUATION_UNSERVED_STATES)
        block["unserved_weighted"] = _sum_or_none(weights[unserved])
    else:
        warnings.append(
            make_warning(
                "schema_mismatch",
                "evacuation_states.parquet has no usable weight column; weighted "
                "evacuation totals are null",
                "evacuation_states.parquet",
            )
        )

    block["clearance_time_minutes"] = _clearance_times(states, run, warnings)
    # The contract's list is intentionally empty: no artefact in section 3 ties
    # a clearance delay to a specific edge, so naming bottleneck edges here
    # would be a guess.
    block["top_bottleneck_edges"] = []
    return block


def _clearance_times(
    states: pd.DataFrame, run: RunRef, warnings: list[ApiWarning]
) -> dict[str, float | None]:
    """Apply the canonical clearance definition using saved warning metadata."""
    scenario = run.manifest.get("evacuation_scenario")
    departure = scenario.get("departure_model") if isinstance(scenario, dict) else None
    if not isinstance(departure, dict) or "warning_time_s" not in departure:
        warnings.append(
            make_warning(
                "missing_warning_time",
                "manifest.json has no evacuation warning_time_s; clearance quantiles "
                "cannot be reconstructed and are null",
                "manifest.json",
            )
        )
        return dict(EMPTY_CLEARANCE_MINUTES)
    try:
        result = weighted_clearance_minutes(
            states, warning_time_s=departure["warning_time_s"]
        )
    except ValueError as exc:
        warnings.append(
            make_warning(
                "invalid_clearance_data",
                f"clearance quantiles are null: {exc}",
                "evacuation_states.parquet",
            )
        )
        return dict(EMPTY_CLEARANCE_MINUTES)
    if all(value is None for value in result.values()):
        warnings.append(
            make_warning(
                "no_measurements",
                "no arrived records are present; clearance quantiles are null",
                "evacuation_states.parquet",
            )
        )
    return result


def reconcile_stats_clearance(run: RunRef, payload: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct the stats clearance block from its authoritative artefacts."""
    result = dict(payload)
    evacuation = result.get("evacuation")
    evacuation = dict(evacuation) if isinstance(evacuation, dict) else {}
    warnings: list[ApiWarning] = []
    states, read_warnings = read_parquet(
        artefact_path(run, "evacuation_states.parquet"),
        columns=["state", "event_time_s", "weight"],
    )
    warnings.extend(read_warnings)
    if states is None:
        clearance = dict(EMPTY_CLEARANCE_MINUTES)
    else:
        clearance = _clearance_times(states, run, warnings)
    evacuation["clearance_time_minutes"] = clearance
    result["evacuation"] = evacuation
    existing = result.get("warnings")
    result["warnings"] = list(existing) if isinstance(existing, list) else []
    result["warnings"].extend(warning.model_dump() for warning in warnings)
    return result


def _stages(run: RunRef) -> list[dict[str, Any]]:
    """Per-stage status and row counts, passed through from run_state."""
    for key in ("stages", "stage_rail"):
        stages = run.run_state.get(key)
        if isinstance(stages, list) and stages:
            return [jsonable(stage) for stage in stages if isinstance(stage, dict)]
    return []


def _sources(run: RunRef, registry: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Source rows for the stats payload.

    Licence comes from the manifest's ``licence_snapshot`` -- the claim the run
    actually made at retrieval time. Status is not in the manifest schema, so it
    is looked up in the registry and left null when the source is unknown.
    """
    registry_status: dict[str, str] = {}
    if isinstance(registry, dict):
        for source in registry.get("sources", []) or []:
            if isinstance(source, dict) and isinstance(source.get("source_id"), str):
                registry_status[source["source_id"]] = str(source.get("status", ""))

    rows: list[dict[str, Any]] = []
    for entry in run.manifest.get("source_versions", []) or []:
        if not isinstance(entry, dict):
            continue
        source_id = entry.get("source_id")
        if not isinstance(source_id, str):
            continue
        rows.append(
            {
                "source_id": source_id,
                "licence": _first_str(entry, ("licence_snapshot", "licence")),
                "status": registry_status.get(source_id),
            }
        )
    return rows


def assemble_stats(
    run: RunRef,
    pilot: dict[str, Any] | None = None,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the contract section 4 payload from the manifest and the tables.

    This is a fallback path. When ``stats.json`` exists it is served verbatim,
    because the pipeline owns that document and its provenance.
    """
    payload = empty_stats_skeleton(run)
    warnings: list[ApiWarning] = list(run.warnings)
    payload["geography"] = _geography(run, pilot)
    payload["population"] = _population_block(run, warnings)
    payload["flood"] = _flood_block(run, warnings)
    payload["evacuation"] = _evacuation_block(run, warnings)
    payload["stages"] = _stages(run)
    payload["sources"] = _sources(run, registry)

    run_warnings: list[Any] = []
    for warning in warnings:
        run_warnings.append(warning.model_dump())
    for raw in run.manifest.get("warnings", []) or []:
        if isinstance(raw, str):
            run_warnings.append({"code": "run_warning", "message": raw, "artefact": None})
        elif isinstance(raw, dict):
            run_warnings.append(raw)
    payload["warnings"] = run_warnings

    # validation_status is copied from the manifest and never recomputed.
    payload["validation_status"] = run.validation_status
    return payload
