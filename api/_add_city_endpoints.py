"""Insert the city-layer endpoints into the FastAPI app.

Kept as a file rather than an inline heredoc because PowerShell has no
heredoc, and because the insertion is large enough to be worth reviewing.
"""

from pathlib import Path

APP = Path("api/app.py")

NEW = '''    @app.get("/v1/runs/{run_id}/population-grid")
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
        frame, read_warnings = read_parquet(CURATED_DIR / "city" / "destinations.parquet")
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
                geometry = wkt_to_geometry(record.get("geometry_wkt"))
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

'''

ANCHOR = '''    @app.get("/", include_in_schema=False)
    def root() -> JSONResponse:'''


def main() -> int:
    source = APP.read_text(encoding="utf-8")
    if source.count(ANCHOR) != 1:
        raise SystemExit(f"anchor found {source.count(ANCHOR)} times; expected exactly 1")
    if "population-grid" in source:
        print("endpoints already present; nothing to do")
        return 0
    APP.write_text(source.replace(ANCHOR, NEW + ANCHOR), encoding="utf-8")
    print("endpoints added")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
