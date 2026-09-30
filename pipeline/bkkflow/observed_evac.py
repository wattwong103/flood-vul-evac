"""City-scale connectivity screening under OBSERVED water presence.

Why this exists
---------------
The city run had no hazard layer, so it had no evacuation analysis. Depth is
unavailable from every reachable source, but *extent* is not: the JRC Global
Surface Water record measures where water was present in a given year. That
supports a real connectivity question even though it cannot support a depth
question.

What this computes
------------------
For a chosen observed year, which roads and paths are underwater, which
population cells are exposed, and whether each exposed population can reach a
designated destination on foot when those ways are removed from the network.

What this is NOT
----------------
This is **not** an evacuation simulation of a flood event. A yearly Landsat
classification says a cell held water at some point in a year. It carries no
depth, no duration, no flow direction, and no timing, so this module answers:

    "If the ways that held water that year were unusable, who could still
     reach a destination, and how far away was it?"

That is a **screening** result about network connectivity under a mapped
condition. It is not a forecast, not an evacuation time, and not advice.

Two further limits are stated on the output rather than glossed:

* Water is treated as impassable at any depth. A puddle and a metre of water
  are the same here, which is deliberately conservative and wrong in detail.
* Destinations are unverified OSM tags with no capacity, so "reaches a
  destination" means "reaches the vicinity of somewhere tagged as a
  destination", not "reaches usable shelter".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from .city_network import CityRoutingIndex
from .util import CURATED_DIR, ensure_dir, utc_now_iso, write_json

DESIGNATED_DESTINATIONS = 150
SNAP_TOLERANCE_M = 700.0
CLEARANCE_THRESHOLDS_MIN = (15.0, 30.0, 60.0, 120.0)

SEVERITY_TEXT = (
    "Connectivity screening under OBSERVED water presence. Not an evacuation "
    "simulation: the hazard is a yearly Landsat water classification, so it "
    "carries no depth, duration, flow direction or timing. Water is treated as "
    "impassable at any depth, which is conservative and wrong in detail. "
    "Destinations are unverified OSM tags carrying no capacity, so arrival "
    "means arriving near a tagged destination, not reaching usable shelter."
)


@dataclass
class ScreeningResult:
    year: int
    water_cells: int
    closed_edges: int
    total_edges: int
    exposed_cells: int
    exposed_population: float
    reachable_population: float
    unreachable_population: float
    no_network_access_cells: int
    clearance_minutes: dict[str, float | None]
    thresholds: dict[str, float]
    designated_destinations: int
    elapsed_seconds: float
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_role": "screening_index",
            "hazard_role": "observed",
            "year": self.year,
            "measures": "network connectivity under observed water presence",
            "is_evacuation_simulation": False,
            "severity_note": SEVERITY_TEXT,
            "water_cells": self.water_cells,
            "closed_edges": self.closed_edges,
            "total_edges": self.total_edges,
            "closed_edge_share": round(self.closed_edges / max(self.total_edges, 1), 6),
            "exposed_cells": self.exposed_cells,
            "exposed_population": round(self.exposed_population, 2),
            "reachable_population": round(self.reachable_population, 2),
            "unreachable_population": round(self.unreachable_population, 2),
            "reachable_share_of_exposed": round(
                self.reachable_population / max(self.exposed_population, 1e-9), 6
            ),
            "no_network_access_cells": self.no_network_access_cells,
            "clearance_minutes": self.clearance_minutes,
            "threshold_minutes_reached": self.thresholds,
            "designated_destinations": self.designated_destinations,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "warnings": self.warnings,
        }


def latest_run_dir() -> Path:
    """The newest run directory, for artefacts written per run.

    Network edges and the population grid belong to a run, not to the shared
    curated store, so a screening has to be explicit about which run it used.
    """
    from .util import RUNS_DIR

    candidates = [
        path
        for path in RUNS_DIR.glob("*")
        if (path / "network_edges.parquet").is_file()
    ]
    if not candidates:
        raise FileNotFoundError("no run with network_edges.parquet; execute a city run first")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _load(path) -> gpd.GeoDataFrame | None:
    from pathlib import Path

    from shapely import wkt as shapely_wkt

    target = Path(path)
    if not target.is_file():
        return None
    frame = pd.read_parquet(target)
    if "geometry_wkt" in frame.columns:
        frame["geometry"] = frame["geometry_wkt"].map(shapely_wkt.loads)
        return gpd.GeoDataFrame(frame, geometry="geometry", crs="EPSG:32647")
    if "lon" in frame.columns and "lat" in frame.columns:
        # Some curated layers publish lon/lat instead of WKT. Those columns are
        # WGS84 degrees, so the frame must be declared geographic; labelling
        # them as the analysis CRS puts every point in the wrong place.
        return gpd.GeoDataFrame(
            frame,
            geometry=gpd.points_from_xy(frame["lon"], frame["lat"]),
            crs="OGC:CRS84",
        )
    return frame


WATER_MASK_CACHE: dict[int, Any] = {}


def water_mask(year: int):
    """Return (mask, transform, crs) for a year at the SOURCE 30 m resolution.

    Aggregating water to 1 km before testing which roads are affected destroys
    the very thing the test needs: inside a 1 km cell the water may be a canal
    with dry roads either side of it. Deciding closures from cell centres closed
    87% of the city, which is an artefact of the aggregation rather than a
    finding. The 30 m classification is the resolution at which "is this road
    wet" is a meaningful question.
    """
    if year in WATER_MASK_CACHE:
        return WATER_MASK_CACHE[year]

    from pathlib import Path as _Path

    import rasterio
    from rasterio.mask import mask as rio_mask

    from .aoi import load_aoi
    from .sources import gsw as gsw_module

    aoi = load_aoi("bangkok-bma")
    bounds = tuple(float(value) for value in aoi.geometry.union_all().bounds)
    path = _Path("data/staged/gsw") / gsw_module.tile_name_for(year, bounds)
    if not path.is_file():
        WATER_MASK_CACHE[year] = None
        return None
    with rasterio.open(path) as dataset:
        data, transform = rio_mask(
            dataset,
            [aoi.geometry.union_all()],
            crop=True,
            filled=True,
            nodata=gsw_module.CODE_NO_DATA_LAND,
        )
        crs = dataset.crs
    result = (data[0] == gsw_module.CODE_WATER, transform, crs)
    WATER_MASK_CACHE[year] = result
    return result


def edges_in_water(
    edges: gpd.GeoDataFrame, year: int, samples_per_edge: int = 5
) -> np.ndarray:
    """Flag edges that pass through observed water, sampled along their length.

    Several samples per edge catch a short flooded section that the endpoints
    alone would miss. Returns a boolean array aligned with ``edges``.
    """
    import shapely
    from rasterio.transform import rowcol

    masked = water_mask(year)
    if masked is None:
        return np.zeros(len(edges), dtype=bool)
    mask, transform, crs = masked

    from pyproj import Transformer

    source_crs = str(edges.crs) if edges.crs is not None else "EPSG:32647"
    to_mask = Transformer.from_crs(source_crs, crs, always_xy=True)

    geometries = np.asarray(edges.geometry.values, dtype=object)
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    for fraction in np.linspace(0.0, 1.0, samples_per_edge):
        points = shapely.get_coordinates(
            shapely.line_interpolate_point(geometries, fraction)
        )
        xs.append(points[:, 0])
        ys.append(points[:, 1])
    mask_x, mask_y = to_mask.transform(np.concatenate(xs), np.concatenate(ys))
    rows, cols = rowcol(transform, mask_x, mask_y)
    rows = np.clip(np.asarray(rows, dtype="int64"), 0, mask.shape[0] - 1)
    cols = np.clip(np.asarray(cols, dtype="int64"), 0, mask.shape[1] - 1)
    wet = mask[rows, cols].reshape(len(edges), samples_per_edge)
    return wet.any(axis=1)


def _water_cell_geometries(year: int) -> gpd.GeoDataFrame:
    frame = _load(CURATED_DIR / "city" / "observed_water_cells.parquet")
    if frame is None:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:32647")
    selected = frame[frame["year"] == year]
    if selected.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:32647")
    return gpd.GeoDataFrame(selected, geometry=gpd.points_from_xy(selected["x"], selected["y"]), crs="EPSG:32647")


def select_designated_destinations(
    destinations: gpd.GeoDataFrame, count: int
) -> gpd.GeoDataFrame:
    """Pick a spread-out set of destination candidates.

    Nearest-neighbour routing over all 1,400 candidates would need a travel-time
    field per candidate, which is not affordable city-wide. A smaller spatially
    spread set keeps the computation to a few dozen passes and is recorded in
    the output so the choice is visible rather than hidden.
    """
    if destinations.empty:
        return destinations
    frame = destinations.copy()
    if frame.crs is not None and not str(frame.crs).upper().startswith("EPSG:32647"):
        # The spatial thinning below buckets in whole metres, which only makes
        # sense once the points are in the projected analysis CRS.
        frame = frame.to_crs("EPSG:32647")
    frame["cx"] = frame.geometry.x
    frame["cy"] = frame.geometry.y
    if "verified" in frame.columns:
        frame = frame[~frame["verified"].astype(bool)]
    # Spatially thin the candidates by grid cell so the set covers the city.
    frame["bucket"] = (frame["cx"] // 1000).astype("int64").astype(str) + "_" + (
        frame["cy"] // 1000
    ).astype("int64").astype(str)
    frame = frame.drop_duplicates(subset="bucket")
    if len(frame) > count:
        step = max(len(frame) // count, 1)
        frame = frame.iloc[::step].head(count)
    return frame


def run_connectivity_screening(
    *,
    year: int = 2012,
    analysis_crs: str = "EPSG:32647",
    designated: int = DESIGNATED_DESTINATIONS,
) -> ScreeningResult:
    started = time.time()
    warnings: list[str] = []

    run_dir = latest_run_dir()
    edges = _load(run_dir / "network_edges.parquet")
    grid = pd.read_parquet(run_dir / "population_grid_1km.parquet")
    water = _water_cell_geometries(year)
    destinations = _load(CURATED_DIR / "city" / "destinations.parquet")

    if edges is None:
        return ScreeningResult(
            year=year, water_cells=0, closed_edges=0, total_edges=0, exposed_cells=0,
            exposed_population=0.0, reachable_population=0.0, unreachable_population=0.0,
            no_network_access_cells=0, clearance_minutes={}, thresholds={},
            designated_destinations=0, elapsed_seconds=time.time() - started,
            warnings=["no network edges staged"],
        )
    if water.empty:
        warnings.append(
            f"no observed water cells for {year}; the screening would have no hazard"
        )
    if destinations is None:
        warnings.append("no destination candidates staged; reachability cannot be assessed")

    # Ways that touched observed water are removed from the network entirely.
    if not water.empty and "geometry_wkt" in edges.columns:
        from shapely import wkt as shapely_wkt

        edges = edges.copy()
        edges["geometry"] = edges["geometry_wkt"].map(shapely_wkt.loads)
        edges = gpd.GeoDataFrame(edges, geometry="geometry", crs="EPSG:32647")
        closed_mask = edges_in_water(edges, year)
    else:
        closed_mask = np.zeros(len(edges), dtype=bool)
    closed_edges = int(closed_mask.sum())
    total_edges = int(len(edges))

    # Build the routing graph with those ways absent, rather than deleting them
    # afterwards: parallel ways collapse to one edge, so removing after the fact
    # would close connections that are still open on another way.
    open_mask = edges["walk_allowed"].to_numpy() & ~closed_mask
    index = CityRoutingIndex(
        edges,
        open_mask,
        edges["speed_walk_mps"].fillna(1.25).to_numpy(),
    )

    targets = (
        select_designated_destinations(destinations, designated)
        if destinations is not None
        else gpd.GeoDataFrame(geometry=[], crs=analysis_crs)
    )

    # One travel-time field per designated destination.
    fields: list[np.ndarray] = []
    used = 0
    for point in targets.geometry:
        node = index.nearest_node(point.x, point.y, index.coords)
        if node is None:
            continue
        costs, _ = index.dijkstra(node, cutoff=60 * 60 * 3)
        fields.append(costs)
        used += 1
    if not fields:
        warnings.append("no designated destination could be snapped to the network")
        matrix = np.zeros((0, index.node_count))
    else:
        matrix = np.vstack(fields)

    # Exposed population: cells that hold observed water.
    water_points = water.geometry.values
    exposed = np.zeros(len(grid), dtype=bool)
    if len(water_points) and "x" in grid.columns:
        from scipy.spatial import cKDTree

        tree_points = np.column_stack([np.asarray([p.x for p in water_points]), np.asarray([p.y for p in water_points])])
        lookup = cKDTree(tree_points)
        distance, _ = lookup.query(np.column_stack([grid["x"].to_numpy(), grid["y"].to_numpy()]))
        # A 1 km cell is exposed if its centre is within half a cell diagonal.
        exposed = distance <= 707.0

    cell_points = np.column_stack([grid["x"].to_numpy(), grid["y"].to_numpy()])
    nodes = np.array(
        [index.nearest_node(x, y, index.coords) or -1 for x, y in cell_points], dtype="int64"
    )
    no_access = int((nodes < 0).sum())
    valid = nodes >= 0

    if matrix.size:
        best = matrix[:, nodes].min(axis=0) if valid.any() else np.zeros(len(grid))
    else:
        best = np.full(len(grid), np.inf)

    reachable = valid & np.isfinite(best)
    population = grid["pop"].to_numpy(dtype="float64")
    exposed_population = float(population[exposed].sum())
    reachable_population = float(population[exposed & reachable].sum())
    unreachable_population = float(exposed_population - reachable_population)

    minutes = np.where(reachable, best / 60.0, np.inf)
    clearance: dict[str, float | None] = {}
    for percentile in (5, 50, 95):
        values = minutes[exposed & reachable]
        clearance[f"p{percentile}"] = (
            round(float(np.percentile(values, percentile)), 2) if values.size else None
        )
    # The travel-time figures depend on how many designated destinations stand
    # in for the city: with too few, a median of ninety minutes measures
    # destination scarcity rather than flooding. The count is reported so the
    # dependence is visible instead of implied.
    if used < DESIGNATED_DESTINATIONS:
        warnings.append(
            f"only {used} designated destinations could be placed for a population of "
            f"{exposed_population:,.0f}; travel times depend on that choice"
        )
    thresholds = {
        f"within_{int(limit)}min": round(
            float(population[exposed & (minutes <= limit)].sum()), 2
        )
        for limit in CLEARANCE_THRESHOLDS_MIN
    }

    return ScreeningResult(
        year=year,
        water_cells=int(len(water)),
        closed_edges=closed_edges,
        total_edges=total_edges,
        exposed_cells=int(exposed.sum()),
        exposed_population=exposed_population,
        reachable_population=reachable_population,
        unreachable_population=unreachable_population,
        no_network_access_cells=no_access,
        clearance_minutes=clearance,
        thresholds=thresholds,
        designated_destinations=used,
        elapsed_seconds=time.time() - started,
        warnings=[*warnings, f"run: {run_dir.name}"],
    )


def compare_years(years: tuple[int, ...] = (2010, 2011, 2012, 2020)) -> dict[str, Any]:
    """Run the screening for several observed years, for a sensitivity view."""
    results = {}
    for year in years:
        results[str(year)] = run_connectivity_screening(year=year).as_dict()
    target = ensure_dir(CURATED_DIR / "city" / "connectivity")
    write_json(
        target / "connectivity_screening.json",
        {
            "measures": "network connectivity under observed water presence",
            "is_evacuation_simulation": False,
            "severity_note": SEVERITY_TEXT,
            "years": results,
            "written_at": utc_now_iso(),
        },
    )
    return results
