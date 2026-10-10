"""Drainage-discharge susceptibility screening index for Bangkok.

What this is
------------
A **relative screening index of drainage-discharge susceptibility**, built
from mapped infrastructure geometry only, on the public 1 km grid. Cells that
drain poorly, sit far from a mapped channel, are crossed by a mapped
overflow-flood path, or contain a flood-susceptible village score higher than
cells that do not. That is the entire claim.

What this is not
----------------
* It is **not** a hydraulic model and **not** a flood depth. No field in the
  output is a depth, and the module never emits one. A cell with a high index
  is not "under water"; it is "poorly drained relative to its neighbours".
* It **ignores rainfall, river stage, tides, pump and gate operation, drainage
  capacity, land surface and subsidence**. Those dominate real Bangkok
  flooding. Bangkok floods because water arrives faster than the engineered
  system can discharge it, and *neither* the arrival term nor the capacity
  term appears anywhere in this index.
* The underlying drainage geometry is a **mapped layer, not an observation of
  water**. MitrEarth is a cartographic compilation; a channel mapped here is a
  channel drawn on a map, and its capacity, condition and current state are
  unknown. Absence of a mapped channel is absence of a *map record*, which is
  not the same as absence of a channel on the ground.
* It is a **screening** aid: it sorts cells for follow-up. It does not predict
  when, where or how deep water will stand.

Every output row carries ``source_role = "screening_index"`` for exactly this
reason, and the tests assert that no depth-labelled field or band exists.

The index
---------
Three normalised sub-scores, each in 0-1 and each pointing the same way (up =
worse), combined as a weighted mean::

    risk_index = sum(w_k * c_k) / sum(w_k)   over the components that exist,
                clipped to [0, 1]

    c_density   = 1 - minmax(drainage_km_per_km2)                       w = 0.35
    c_distance  = min(distance_to_drainage_m, 2000) / 2000              w = 0.35
    c_flag      = 0.5 * in_overflow_path + 0.5 * susceptible_village    w = 0.30

Monotonicity, which is the property the whole thing rests on:

* more mapped drainage in the cell  -> lower ``c_density`` -> lower risk
* further from a mapped channel      -> higher ``c_distance`` -> higher risk
* on a mapped overflow path          -> higher ``c_flag`` -> higher risk
* inside a flood-susceptible village -> higher ``c_flag`` -> higher risk

``COMPONENT_WEIGHTS`` is the single auditable place the weights live, and they
sum to 1.0. They are a declared ordering, not a fitted result: no calibration
data exists to fit them against, and implying otherwise would be the exact
failure this module exists to avoid.

Why min-max and not rank normalisation
--------------------------------------
Min-max is used because it is linear in the physical quantity: ``c_distance``
is literally "what fraction of the 2 km search radius separates this cell from
a channel", which a reader can check against the map. Rank normalisation is
equally monotone but destroys that: two cells 5 m from a channel would sit at
opposite ends of a rank scale and the index would stop being interpretable
against any measured quantity. The accepted cost is outlier sensitivity, which
is recorded in the result summary.

Nulls, never zeros
------------------
Where a value cannot be computed it is ``null`` (NaN or ``pd.NA``), never
``0``. A null means "unknown"; a 0 would claim "no drainage here", which is a
different and much stronger statement that the map cannot support.
Specifically:

* ``distance_to_drainage_m`` is null beyond the 2,000 m search radius. The
  radius is not a truncation of a known distance; beyond it the answer is
  simply not known, so 2,000 is never written into the field.
* ``basin_id`` and ``basin_drainage_density`` are null outside every mapped
  basin.
* ``in_overflow_path`` and ``susceptible_village`` are ``pd.NA`` when their
  layer is unavailable, not ``False``. A false would read as "no overflow
  mapped here", which is a claim about the world.
* ``drainage_m`` is 0 only for a cell that genuinely contains no mapped
  channel. A cell that is empty is a *measured* 0 m; a cell that cannot be
  assessed is null.
* A missing input file degrades to a recorded unavailability in
  ``DrainageResult.inputs`` plus a warning. It never raises. If no grid can be
  built at all, the result is ``status="unavailable"`` with zero rows.

The one place a null is scored rather than dropped
--------------------------------------------------
``c_distance`` for a cell with no channel within 2 km is set to 1.0, the value
it would take at the radius itself, so that "further from drainage raises
risk" holds at the boundary instead of reversing there. The emitted
``distance_to_drainage_m`` stays null and ``index_inputs_complete`` is False,
so the imputation is visible rather than hidden.

``c_flag`` averages whichever of the two mapped-hazard flags are known, so a
missing village layer removes only the village half of the term and leaves the
overflow half intact. Weights are renormalised over the components that exist,
which only happens when a whole input layer is absent, so all cells stay
comparable with each other.

Bands
-----
Fixed cut points on ``risk_index``, at even quarters of the 0-1 range::

    low         [0.00, 0.25)
    moderate    [0.25, 0.50)
    high        [0.50, 0.75)
    very_high   [0.75, 1.00]

These are quarters of the *scale*, not quantiles of the AOI, and on the real
Bangkok grid the shares are very unequal: most cells land in ``high`` and
``low`` is empty. That is stated in the result summary rather than smoothed
away. The alternative - cutting the bands at this AOI's quartiles - would
re-cut every boundary whenever the input changes, and a screening index whose
band edges move under the reader is not auditable. Read a band as "position on
the 0-1 scale", never as "top N% of the city".

Grid identity
-------------
Cell ids must match the published public grid, so ``build_drainage_index``
prefers an existing ``population_grid_1km.parquet`` for ``gx, gy, x, y`` and
falls back to deriving the grid from the AOI bounds at
``grid_size_m = 1000.0``. The two origins are not the same, and that is
deliberate: the published grid is anchored on the 100 m population-cell
bounds, which sit a few metres east and roughly a kilometre north of the AOI
bounding box. Anchoring on the AOI would silently renumber every cell against
the population grid it is meant to be read beside, so the published grid wins
and the source used is recorded in the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely import STRtree

from .util import CURATED_DIR, RUNS_DIR, sha256_file, utc_now_iso

#: Stamped on every emitted row. This is the contract that stops the index
#: being read downstream as a measurement of water.
SOURCE_ROLE = "screening_index"

INDEX_VERSION = "bkk-drainage-screening-v0.1"

ANALYSIS_CRS = "EPSG:32647"
from .city_method import PUBLIC_GRID_M as GRID_SIZE_M  # noqa: E402

#: Straight-line search radius for the nearest-channel distance. Beyond it the
#: value is unknown, so the field is null rather than capped.
DISTANCE_CUTOFF_M = 2000.0

MITREARTH_DIR = CURATED_DIR / "city" / "mitrearth"
DRAINAGE_FILE = "drainage_system.parquet"
BASIN_FILE = "drainage_basin.parquet"
OVERFLOW_FILE = "overflow_flood.parquet"
VILLAGE_FILE = "flood_susceptible_village.parquet"
AOI_FILE = CURATED_DIR / "aoi" / "bangkok-bma.parquet"
PUBLIC_GRID_GLOB = "*/population_grid_1km.parquet"

#: The three sub-scores and their weights. Auditable, and asserted in tests.
COMPONENT_WEIGHTS: dict[str, float] = {
    "density_absence": 0.35,
    "distance_absence": 0.35,
    "discharge_flag": 0.30,
}

#: (label, lower, upper), upper exclusive except for the final band.
BANDS: tuple[tuple[str, float, float], ...] = (
    ("low", 0.00, 0.25),
    ("moderate", 0.25, 0.50),
    ("high", 0.50, 0.75),
    ("very_high", 0.75, 1.00),
)

#: Emitted column order, kept explicit so consumers can rely on it.
OUTPUT_COLUMNS: tuple[str, ...] = (
    "cell_id",
    "gx",
    "gy",
    "x",
    "y",
    "lon",
    "lat",
    "cell_area_km2",
    "drainage_m",
    "drainage_km_per_km2",
    "distance_to_drainage_m",
    "in_overflow_path",
    "basin_id",
    "basin_drainage_density",
    "susceptible_village",
    "index_components",
    "risk_index",
    "risk_band",
    "index_inputs_complete",
    "source_role",
)

LIMITATIONS: tuple[str, ...] = (
    "Relative screening index of drainage-discharge susceptibility, not a "
    "hydraulic model and not a flood depth.",
    "Ignores rainfall, river stage, tides, pump and gate operation, drainage "
    "capacity, land surface and subsidence, all of which dominate real "
    "Bangkok flooding.",
    "The drainage geometry is a mapped layer, not an observation of water: a "
    "mapped channel is a drawn channel, and its condition and capacity are "
    "unknown.",
    "Components are min-max normalised across the AOI, so the index expresses "
    "position within this distribution and is not comparable with another AOI "
    "without recomputation.",
    "The weights are a declared ordering, not a fitted or calibrated result.",
)


@dataclass
class DrainageResult:
    """The index table plus everything needed to audit how it was built."""

    frame: pd.DataFrame
    status: str
    grid_source: str
    inputs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    written_at: str = field(default_factory=utc_now_iso)

    def as_dict(self) -> dict[str, Any]:
        """Provenance payload. The table itself is written separately."""
        return {
            "index_version": INDEX_VERSION,
            "source_role": SOURCE_ROLE,
            "status": self.status,
            "measures": (
                "relative screening index of drainage-discharge susceptibility "
                "from mapped infrastructure geometry"
            ),
            "is_simulation": False,
            "is_observation": False,
            "is_flood_depth": False,
            "grid_source": self.grid_source,
            "grid_size_m": GRID_SIZE_M,
            "distance_cutoff_m": DISTANCE_CUTOFF_M,
            "component_weights": dict(COMPONENT_WEIGHTS),
            "bands": [{"band": label, "min": low, "max": high} for label, low, high in BANDS],
            "rows": int(len(self.frame)),
            "inputs": self.inputs,
            "summary": self.summary,
            "warnings": list(self.warnings),
            "limitations": list(LIMITATIONS),
            "written_at": self.written_at,
        }


# --------------------------------------------------------------------------
# grid
# --------------------------------------------------------------------------


def latest_public_grid(runs_dir: str | Path = RUNS_DIR) -> Path | None:
    """Most recently written published 1 km grid, if any run has published one."""
    candidates = sorted(
        Path(runs_dir).glob(PUBLIC_GRID_GLOB), key=lambda p: p.stat().st_mtime
    )
    return candidates[-1] if candidates else None


def empty_frame() -> pd.DataFrame:
    """An empty table with the full output schema, so absence stays typed."""
    return pd.DataFrame({name: pd.Series(dtype="object") for name in OUTPUT_COLUMNS})


def _to_wgs84(frame: pd.DataFrame, analysis_crs: str) -> tuple[np.ndarray, np.ndarray]:
    """Cell centres as lon/lat degrees, rounded like the published grid."""
    points = gpd.GeoSeries(
        gpd.points_from_xy(frame["x"].to_numpy(), frame["y"].to_numpy()), crs=analysis_crs
    ).to_crs("OGC:CRS84")
    return np.round(points.x.to_numpy(), 6), np.round(points.y.to_numpy(), 6)


def load_grid(
    *,
    grid_path: str | Path | None = None,
    aoi_path: str | Path | None = None,
    analysis_crs: str = ANALYSIS_CRS,
    grid_size_m: float = GRID_SIZE_M,
) -> tuple[pd.DataFrame | None, str, list[str]]:
    """Return ``(grid frame, provenance label, warnings)``.

    Prefers the published public grid so ``gx, gy, x, y`` match the numbers
    already published for population; falls back to the AOI bounds.
    """
    warnings: list[str] = []
    path = Path(grid_path) if grid_path is not None else latest_public_grid()
    if path is not None and Path(path).is_file():
        published = pd.read_parquet(path)
        if {"gx", "gy", "x", "y"}.issubset(published.columns):
            frame = published[["gx", "gy", "x", "y"]].astype(
                {"gx": "int64", "gy": "int64", "x": "float64", "y": "float64"}
            )
            if "geometry_wkt" in published.columns:
                # The published lon/lat are authoritative: they are what any
                # existing consumer has already stored.
                points = gpd.GeoSeries.from_wkt(published["geometry_wkt"]).set_crs("OGC:CRS84")
                frame["lon"] = points.x.to_numpy()
                frame["lat"] = points.y.to_numpy()
            else:
                frame["lon"], frame["lat"] = _to_wgs84(frame, analysis_crs)
            return frame.reset_index(drop=True), f"published_grid:{Path(path).name}", warnings
        warnings.append(
            f"{path} has no gx/gy/x/y columns, so the grid is derived from the AOI instead."
        )

    warnings.append(
        "No published 1 km population grid was found, so the grid is derived "
        "from the AOI bounding box. Its gx/gy will not match the published "
        "population grid ids."
    )
    aoi = Path(aoi_path) if aoi_path is not None else AOI_FILE
    if not aoi.is_file():
        warnings.append(
            f"No AOI geometry at {aoi}, so no grid can be derived and the index is unavailable."
        )
        return None, "unavailable", warnings

    clip = gpd.read_parquet(aoi).to_crs(analysis_crs).geometry.union_all()
    minx, miny, maxx, maxy = (float(v) for v in clip.bounds)
    gx = np.arange(int((maxx - minx) // grid_size_m) + 1)
    gy = np.arange(int((maxy - miny) // grid_size_m) + 1)
    cols, rows = np.meshgrid(gx, gy, indexing="xy")
    xs = minx + (cols.ravel() + 0.5) * grid_size_m
    ys = miny + (rows.ravel() + 0.5) * grid_size_m
    inside = shapely.contains_xy(clip, xs, ys)

    frame = pd.DataFrame(
        {
            "gx": cols.ravel()[inside].astype("int64"),
            "gy": rows.ravel()[inside].astype("int64"),
            "x": xs[inside],
            "y": ys[inside],
        }
    )
    frame["lon"], frame["lat"] = _to_wgs84(frame, analysis_crs)
    return frame.reset_index(drop=True), "derived_from_aoi_bounds", warnings


# --------------------------------------------------------------------------
# layers
# --------------------------------------------------------------------------


@dataclass
class Layer:
    """One staged input layer, or the recorded reason it is unavailable."""

    name: str
    geoms: np.ndarray | None = None
    table: pd.DataFrame | None = None
    record: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.geoms is not None and len(self.geoms) > 0


def load_layer(path: str | Path, name: str) -> Layer:
    """Load a staged MitrEarth layer's WKT column, or record why it is absent.

    A missing or unreadable input is a recorded unavailability, never an
    exception: a partial index with a stated gap is more useful than none.
    """
    path = Path(path)
    if not path.is_file():
        return Layer(name, record={"status": "missing", "source_file": path.name})
    try:
        frame = pd.read_parquet(path)
    except Exception as error:  # unreadable parquet, schema drift, partial write
        return Layer(
            name,
            record={"status": "unreadable", "source_file": path.name, "error": str(error)},
        )
    if "geometry_wkt" not in frame.columns:
        return Layer(name, record={"status": "no_geometry_column", "source_file": path.name})

    geoms = shapely.from_wkt(frame["geometry_wkt"].to_numpy())
    keep = ~shapely.is_missing(geoms) & ~shapely.is_empty(geoms)
    record = {
        "status": "ok",
        "source_file": path.name,
        "rows_total": int(len(frame)),
        "rows_usable": int(keep.sum()),
        "rows_discarded_geometry": int((~keep).sum()),
        "sha256": sha256_file(path),
    }
    for column in ("STREAM_ID", "OBJECTID"):
        if column in frame.columns:
            record[f"unique_{column.lower()}"] = int(frame[column].nunique())
    if keep.any():
        usable = geoms[keep]
        total_length_km = float(shapely.length(usable).sum()) / 1000.0
        total_area_km2 = float(shapely.area(usable).sum()) / 1e6
        if total_length_km > 0:
            record["length_km"] = round(total_length_km, 3)
        if total_area_km2 > 0:
            record["area_km2"] = round(total_area_km2, 3)
    return Layer(
        name,
        geoms=geoms[keep],
        table=frame[keep].reset_index(drop=True),
        record=record,
    )


def clip_lengths(geoms: np.ndarray | None, targets: np.ndarray) -> np.ndarray:
    """Total length of ``geoms`` inside each target geometry, vectorised.

    A single tree query followed by one vectorised intersection beats a
    per-cell Python loop by orders of magnitude, and intersecting (rather than
    testing) is what keeps a channel running along a cell edge from being
    counted in full.
    """
    total = np.zeros(len(targets), dtype="float64")
    if geoms is None or len(geoms) == 0 or len(targets) == 0:
        return total
    pairs = STRtree(geoms).query(targets, predicate="intersects")
    if pairs.size == 0:
        return total
    pieces = shapely.intersection(targets[pairs[0]], geoms[pairs[1]])
    lengths = np.nan_to_num(shapely.length(pieces), nan=0.0)
    return np.bincount(pairs[0], weights=lengths, minlength=len(targets))


def nearest_distance(geoms: np.ndarray | None, points: np.ndarray) -> np.ndarray:
    """Distance from each point to the nearest geometry, via one tree call."""
    if geoms is None or len(geoms) == 0 or len(points) == 0:
        return np.full(len(points), np.inf)
    nearest = STRtree(geoms).nearest(points)
    out = np.full(len(points), np.inf)
    valid = nearest >= 0
    out[valid] = shapely.distance(points[valid], geoms[nearest[valid]])
    return out


def intersects_any(targets: np.ndarray, geoms: np.ndarray | None) -> np.ndarray:
    """Boolean per target: does it intersect any of ``geoms``?"""
    hit = np.zeros(len(targets), dtype=bool)
    if geoms is None or len(geoms) == 0 or len(targets) == 0:
        return hit
    pairs = STRtree(geoms).query(targets, predicate="intersects")
    if pairs.size:
        hit[pairs[0]] = True
    return hit


def _nullable_bool(values: np.ndarray, known: bool) -> pd.Series:
    """A boolean column where an unavailable layer yields NA, never False."""
    if known:
        return pd.Series(values.astype(bool))
    return pd.Series(np.full(len(values), np.nan)).astype("boolean")


# --------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------


def minmax(values: np.ndarray) -> np.ndarray:
    """Scale to 0-1, preserving NaN.

    A degenerate range yields 0.5, not 0: with no variation across the AOI,
    "absence" is undetermined, and 0 would claim every cell drains as well as
    the best-drained one.
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.full_like(values, np.nan)
    lo, hi = float(finite.min()), float(finite.max())
    if hi - lo <= 1e-12:
        return np.full_like(values, 0.5)
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def band_for(score: float) -> str:
    """Band label for one score, using the documented cut points."""
    for label, _, high in BANDS:
        if score < high:
            return label
    return BANDS[-1][0]


def _band_series(scores: np.ndarray) -> np.ndarray:
    labels = np.array([label for label, _, _ in BANDS], dtype=object)
    # Bands are [low, high), so a score sitting exactly on an edge belongs to
    # the band that starts there. searchsorted with side="left" returns the
    # first edge >= the score, which puts every value inside a band into the
    # NEXT band up: a score of 0.05 would be labelled 'moderate' when the
    # declared moderate band starts at 0.25. Using side="right" and stepping
    # back one gives [low, high) at the edges as well as between them.
    edges = np.array([low for _, low, _ in BANDS], dtype="float64")
    index = np.searchsorted(edges, scores, side="right") - 1
    index = np.clip(index, 0, len(labels) - 1)
    return labels[index]


def combine_components(components: dict[str, np.ndarray]) -> np.ndarray:
    """Weighted mean over the components that exist, clipped to 0-1.

    A component absent for every cell means its input layer was unavailable;
    it is dropped for all cells, so the denominator stays shared and cells
    remain comparable with each other.
    """
    size = len(next(iter(components.values())))
    total = np.zeros(size, dtype="float64")
    weight = 0.0
    for name, w in COMPONENT_WEIGHTS.items():
        values = components[name]
        usable = np.isfinite(values)
        if not usable.any():
            continue
        total += w * np.where(usable, values, 0.0)
        weight += w
    if weight <= 0:
        return np.full(size, np.nan)
    return np.clip(total / weight, 0.0, 1.0)


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------


def build_drainage_index(
    *,
    grid_path: str | Path | None = None,
    aoi_path: str | Path | None = None,
    curated_dir: str | Path = MITREARTH_DIR,
    analysis_crs: str = ANALYSIS_CRS,
    grid_size_m: float = GRID_SIZE_M,
) -> DrainageResult:
    """Build the drainage-discharge screening index for every grid cell."""
    curated = Path(curated_dir)
    inputs: dict[str, Any] = {}
    warnings: list[str] = []

    grid, grid_source, grid_warnings = load_grid(
        grid_path=grid_path, aoi_path=aoi_path,
        analysis_crs=analysis_crs, grid_size_m=grid_size_m,
    )
    warnings.extend(grid_warnings)
    if grid is None:
        return DrainageResult(
            frame=empty_frame(),
            status="unavailable",
            grid_source=grid_source,
            inputs={**inputs, "grid": {"status": "unavailable", "source": grid_source}},
            warnings=warnings + [
                "The drainage screening index is UNAVAILABLE: no grid could be built, "
                "so no cell was scored. Nothing here may be inferred about any place."
            ],
        )
    inputs["grid"] = {"status": "ok", "source": grid_source, "rows": int(len(grid))}

    n_cells = len(grid)
    half = grid_size_m / 2.0
    xs = grid["x"].to_numpy()
    ys = grid["y"].to_numpy()
    centres = shapely.points(xs, ys)
    cells = shapely.box(xs - half, ys - half, xs + half, ys + half)
    cell_area_km2 = (grid_size_m / 1000.0) ** 2

    # ---- mapped drainage -------------------------------------------------
    drainage = load_layer(curated / DRAINAGE_FILE, "drainage_system")
    inputs["drainage_system"] = drainage.record
    if drainage.available:
        drainage_m = clip_lengths(drainage.geoms, cells)
        distance = nearest_distance(drainage.geoms, centres)
        density = drainage_m / cell_area_km2
    else:
        drainage_m = np.full(n_cells, np.nan)
        distance = np.full(n_cells, np.inf)
        density = np.full(n_cells, np.nan)
        warnings.append(
            f"The mapped drainage layer is unavailable ({drainage.record.get('status')}). "
            "Drainage-dependent columns are null for every cell, not zero: 'no map "
            "record' is not 'no drainage'."
        )

    # Beyond the search radius the distance is unknown, so the field is null.
    # The component, not the field, is scored at the radius; see the docstring.
    within = np.isfinite(distance) & (distance <= DISTANCE_CUTOFF_M)
    distance_field = np.where(within, distance, np.nan)
    distance_component = np.where(
        np.isfinite(distance), np.minimum(distance, DISTANCE_CUTOFF_M) / DISTANCE_CUTOFF_M, 1.0
    )

    # ---- mapped overflow-flood paths -------------------------------------
    overflow = load_layer(curated / OVERFLOW_FILE, "overflow_flood")
    inputs["overflow_flood"] = overflow.record
    in_overflow = _nullable_bool(intersects_any(cells, overflow.geoms), overflow.available)
    if not overflow.available:
        warnings.append(
            f"The mapped overflow-flood path layer is unavailable "
            f"({overflow.record.get('status')}), so `in_overflow_path` is unknown "
            "for every cell rather than false."
        )

    # ---- flood-susceptible villages --------------------------------------
    villages = load_layer(curated / VILLAGE_FILE, "flood_susceptible_village")
    inputs["flood_susceptible_village"] = villages.record
    has_village = np.zeros(n_cells, dtype=bool)
    if villages.available:
        # Tree over the cells, queried with the village points under a
        # ``within`` predicate: a pair is (village index, cell index), so the
        # cell in column 1 is the one the village falls inside.
        pairs = STRtree(cells).query(villages.geoms, predicate="within")
        if pairs.size:
            has_village[pairs[1]] = True
    susceptible = _nullable_bool(has_village, villages.available)
    if not villages.available:
        warnings.append(
            f"The flood-susceptible village layer is unavailable "
            f"({villages.record.get('status')}), so `susceptible_village` is unknown "
            "for every cell rather than false."
        )

    # ---- drainage basins -------------------------------------------------
    basins = load_layer(curated / BASIN_FILE, "drainage_basin")
    inputs["drainage_basin"] = basins.record
    basin_id = np.full(n_cells, None, dtype=object)
    basin_density = np.full(n_cells, np.nan)
    if basins.available:
        stream_ids = (
            basins.table["STREAM_ID"].to_numpy()
            if basins.table is not None and "STREAM_ID" in basins.table.columns
            else np.arange(len(basins.geoms))
        )
        # STREAM_ID repeats across the 137 mapped polygons, so the id carries
        # the row too and stays unique and traceable.
        basin_ids = np.array(
            [f"bas_{int(s)}_{i:03d}" for i, s in enumerate(stream_ids)], dtype=object
        )
        area_km2 = shapely.area(basins.geoms) / 1e6
        basin_length_m = (
            clip_lengths(drainage.geoms, basins.geoms) if drainage.available
            else np.full(len(basins.geoms), np.nan)
        )
        with np.errstate(invalid="ignore", divide="ignore"):
            per_basin_km_per_km2 = np.where(
                area_km2 > 0, (basin_length_m / 1000.0) / area_km2, np.nan
            )

        # A cell centre inside nested basins is assigned to the smallest, so
        # the choice is deterministic and takes the most specific basin.
        pairs = STRtree(basins.geoms).query(centres, predicate="intersects")
        if pairs.size:
            order = np.lexsort((pairs[1], area_km2[pairs[1]], pairs[0]))
            rows = pairs[0][order]
            first = np.ones(rows.shape, dtype=bool)
            first[1:] = rows[1:] != rows[:-1]
            cells_matched = rows[first]
            basins_matched = pairs[1][order][first]
            basin_id[cells_matched] = basin_ids[basins_matched]
            basin_density[cells_matched] = per_basin_km_per_km2[basins_matched]
    else:
        warnings.append(
            f"The drainage basin layer is unavailable ({basins.record.get('status')}), "
            "so `basin_id` and `basin_drainage_density` are null for every cell."
        )

    # ---- the index -------------------------------------------------------
    def _flag_half(column: pd.Series) -> np.ndarray:
        """0.5 per known flag, NaN where that layer is unavailable."""
        known = column.notna().to_numpy()
        return np.where(known, 0.5 * column.fillna(False).to_numpy(), np.nan)

    stacked = np.vstack([_flag_half(in_overflow), _flag_half(susceptible)])
    known_terms = np.isfinite(stacked).sum(axis=0)
    # If neither flag layer is available the term is unknown, so it is dropped
    # from the weighted mean. Defaulting it to 1.0 would assert maximum hazard
    # for a missing input, which is the one thing a null exists to prevent.
    discharge_flag = np.where(
        known_terms > 0,
        np.nansum(np.nan_to_num(stacked), axis=0) / np.where(known_terms > 0, known_terms, 1),
        np.nan,
    )

    components = {
        "density_absence": 1.0 - minmax(density),
        "distance_absence": distance_component,
        "discharge_flag": discharge_flag,
    }
    risk = combine_components(components)
    if not np.isfinite(risk).any():
        warnings.append(
            "No cell could be scored: every index component was unavailable. The "
            "index is published as null throughout rather than as 0."
        )

    frame = pd.DataFrame(
        {
            "cell_id": [f"dr_{g}_{r}" for g, r in zip(grid["gx"].to_numpy(), grid["gy"].to_numpy())],
            "gx": grid["gx"].to_numpy(),
            "gy": grid["gy"].to_numpy(),
            "x": xs,
            "y": ys,
            "lon": grid["lon"].to_numpy(),
            "lat": grid["lat"].to_numpy(),
            "cell_area_km2": cell_area_km2,
            "drainage_m": np.where(np.isfinite(drainage_m), drainage_m, np.nan),
            # metres of mapped channel per km2, following the project schema
            # name; the unit is m/km2 and is stated here so it cannot be
            # misread as km/km2.
            "drainage_km_per_km2": np.where(np.isfinite(density), density, np.nan),
            "distance_to_drainage_m": distance_field,
            "in_overflow_path": in_overflow,
            "basin_id": pd.Series(basin_id, dtype="object"),
            "basin_drainage_density": basin_density,
            "susceptible_village": susceptible,
            "index_components": [
                {name: (None if not np.isfinite(value) else round(float(value), 6))
                 for name, value in zip(components, values)}
                for values in zip(*components.values())
            ],
            "risk_index": np.where(np.isfinite(risk), np.round(risk, 6), np.nan),
            "index_inputs_complete": np.isfinite(distance_field)
            & np.isfinite(density)
            & (known_terms > 0),
        }
    )
    frame["risk_band"] = _band_series(np.nan_to_num(frame["risk_index"].to_numpy(), nan=0.0))
    frame.loc[~np.isfinite(frame["risk_index"].to_numpy()), "risk_band"] = None
    frame["source_role"] = SOURCE_ROLE
    frame = frame[list(OUTPUT_COLUMNS)]

    return DrainageResult(
        frame=frame,
        status="ok",
        grid_source=grid_source,
        inputs=inputs,
        warnings=warnings,
        summary=summarise(frame, grid_source=grid_source, inputs=inputs),
    )


def summarise(
    frame: pd.DataFrame, *, grid_source: str, inputs: dict[str, Any]
) -> dict[str, Any]:
    """Descriptive statistics for the provenance record. No interpretation."""
    risk = frame["risk_index"].dropna()
    bands = frame["risk_band"].value_counts()
    return {
        "grid_source": grid_source,
        "rows": int(len(frame)),
        "rows_scored": int(risk.size),
        "drainage_length_km_in_grid": (
            round(float(frame["drainage_m"].sum()) / 1000.0, 3)
            if frame["drainage_m"].notna().any() else None
        ),
        "risk_index": {
            "min": round(float(risk.min()), 6) if risk.size else None,
            "median": round(float(risk.median()), 6) if risk.size else None,
            "mean": round(float(risk.mean()), 6) if risk.size else None,
            "max": round(float(risk.max()), 6) if risk.size else None,
        },
        "bands": {label: int(bands.get(label, 0)) for label, _, _ in BANDS},
        "bands_note": (
            "Cut points are fixed quarters of the 0-1 scale, not quantiles of "
            "this AOI, so the band shares are unequal by design and a band is "
            "not a percentile rank. Read it as a position on the scale."
        ),
        "band_shares": {
            label: round(int(bands.get(label, 0)) / len(frame), 4) if len(frame) else None
            for label, _, _ in BANDS
        },
        "cells_without_drainage_within_cutoff": int(frame["distance_to_drainage_m"].isna().sum()),
        "cells_with_null_basin": int(frame["basin_id"].isna().sum()),
        "cells_in_overflow_path": int(frame["in_overflow_path"].fillna(False).astype(bool).sum()),
        "cells_with_susceptible_village": int(
            frame["susceptible_village"].fillna(False).astype(bool).sum()
        ),
        "cells_with_complete_inputs": int(frame["index_inputs_complete"].sum()),
        "basins_covering_grid": int(frame["basin_id"].nunique()),
        "inputs_status": {name: detail.get("status") for name, detail in inputs.items()},
    }
