"""Immutable public map layers with SQLite RTree viewport lookup."""
from __future__ import annotations
import json
import math
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
import geopandas as gpd
import pandas as pd
import pyarrow.parquet as pq
import shapely

LAYERS = {
    "network": ("network_edges.parquet", ("edge_id", "length_m", "highway", "walk_allowed", "vehicle_allowed")),
    "buildings": ("buildings.parquet", ("building_id", "height_m", "height_source", "height_status",
        "levels", "refuge_status", "refuge_verified", "refuge_capacity", "refuge_accessible")),
}


class MapIndexUnavailable(RuntimeError):
    """A valid request cannot be served by this run's saved index."""


def build_map_index(run_dir: Path, analysis_crs: str) -> dict:
    """Install a complete index once, without replacing a published artifact.

    A crash leaves only a private temporary directory. A same-filesystem hard
    link publishes atomically and fails if another writer installed the target.
    Filesystems without hard-link support fail explicitly, never copy partially.
    """
    path = run_dir / "map.sqlite"
    if path.exists():
        raise FileExistsError(path)
    with tempfile.TemporaryDirectory(prefix=".map-", dir=run_dir) as temporary:
        staged = Path(temporary) / "map.sqlite"
        result = _build_map_index(run_dir, analysis_crs, staged)
        os.link(staged, path)
    return {**result, "path": str(path)}


def _build_map_index(run_dir: Path, analysis_crs: str, path: Path) -> dict:
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE features (id INTEGER PRIMARY KEY, layer TEXT NOT NULL, feature TEXT NOT NULL);
            CREATE VIRTUAL TABLE bounds USING rtree(id, minx, maxx, miny, maxy);
            CREATE INDEX feature_layer ON features(layer, id);
        """)
        next_id = 1
        counts = {}
        for layer, (filename, allowed) in LAYERS.items():
            source = run_dir / filename
            counts[layer] = 0
            if not source.is_file():
                continue
            parquet = pq.ParquetFile(source)
            columns = [c for c in (*allowed, "geometry_wkt") if c in parquet.schema.names]
            if "geometry_wkt" not in columns:
                raise ValueError(f"{filename} has no map geometry")
            for batch in parquet.iter_batches(batch_size=10000, columns=columns):
                frame = batch.to_pandas()
                geometries = gpd.GeoSeries(shapely.from_wkt(frame.pop("geometry_wkt")), crs=analysis_crs).to_crs("OGC:CRS84")
                features, boxes = [], []
                for record, geometry in zip(frame.to_dict("records"), geometries):
                    if geometry is None or geometry.is_empty or not geometry.is_valid:
                        raise ValueError(f"Invalid map geometry in {filename}")
                    minx, miny, maxx, maxy = geometry.bounds
                    if not all(math.isfinite(v) for v in geometry.bounds) or not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
                        raise ValueError(f"Map geometry is outside WGS84 in {filename}")
                    properties = {k: (None if pd.isna(v) else v) for k, v in record.items()}
                    item = {"type": "Feature", "geometry": shapely.geometry.mapping(geometry), "properties": properties}
                    features.append((next_id, layer, json.dumps(item, allow_nan=False, separators=(",", ":"))))
                    boxes.append((next_id, minx, maxx, miny, maxy))
                    next_id += 1
                db.executemany("INSERT INTO features VALUES (?, ?, ?)", features)
                db.executemany("INSERT INTO bounds VALUES (?, ?, ?, ?, ?)", boxes)
                counts[layer] += len(features)
        db.executemany("INSERT INTO metadata VALUES (?, ?)",
                       [("run_id", run_dir.name), ("counts", json.dumps(counts)), ("version", "1")])
    return {"path": str(path), "rows": next_id - 1, "counts": counts}


def query_map_index(run_dir: Path, layer: str, bbox: tuple[float, ...], *,
                    limit: int = 1000, after: int = 0) -> dict:
    if layer not in LAYERS:
        raise ValueError("Unknown public map layer")
    if len(bbox) != 4 or not all(math.isfinite(v) for v in bbox):
        raise ValueError("bbox must contain four finite WGS84 coordinates")
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox must be ordered west,south,east,north within WGS84")
    if not 1 <= limit <= 5000 or after < 0:
        raise ValueError("Invalid map page limit or cursor")
    path = run_dir / "map.sqlite"
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        metadata = dict(db.execute("SELECT key, value FROM metadata"))
        if metadata.get("run_id") != run_dir.name or metadata.get("version") != "1":
            raise MapIndexUnavailable("Map index run identity or version mismatch")
        # CROSS JOIN keeps RTree lookup first, rather than scanning every feature.
        selection = """FROM bounds b CROSS JOIN features f ON f.id=b.id
            WHERE b.maxx>=? AND b.minx<=? AND b.maxy>=? AND b.miny<=? AND f.layer=?"""
        parameters = (west, east, south, north, layer)
        matched = db.execute("SELECT count(*) " + selection, parameters).fetchone()[0]
        rows = db.execute("SELECT f.id, f.feature " + selection +
            " AND f.id>? ORDER BY f.id LIMIT ?", (*parameters, after, limit + 1)).fetchall()
    more = len(rows) > limit
    page = rows[:limit]
    return {"type": "FeatureCollection", "run_id": run_dir.name, "layer": layer,
        "available": True, "bbox": list(bbox), "selection": "feature bounding-box intersection",
        "matched_rows": matched, "returned": len(page), "limit": limit,
        "next_cursor": page[-1][0] if more else None, "truncated": more,
        "features": [json.loads(value) for _, value in page], "warnings": []}
