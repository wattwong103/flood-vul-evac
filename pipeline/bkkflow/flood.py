"""F1/F2 — flood scenario surface, edge sampling and mode-specific impedance.

## What this module is honest about

This is a **declared scenario hazard**, not a hydraulic simulation and not an
observation. The GISTDA open-data host did not resolve from the build
environment, and no rainfall, river-stage or depth measurement passed the
project's licence gate, so there is no observed or physically modelled depth
here. Every row it produces carries ``source_role='scenario'``.

The spatial pattern is a distance-to-water decay: water features are the
flood source, and depth falls off with distance. That is a defensible
*illustrative* pattern for a demonstration run and an indefensible substitute
for a flood model. The manifest records this in its warnings, and the run stays
at ``demonstration``.

The impedance thresholds are engineering priors. They are versioned,
configurable, and tested as sensitivity parameters, and they are never
presented as universal safety facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

# Threshold sets are data, versioned with the run. A change must change the id.
THRESHOLD_SETS: dict[str, dict[int, dict[str, float]]] = {
    "bkk-demo-thresholds-v0.1": {
        # mode: 0 walk, 3 car
        0: {"slow_depth_m": 0.10, "half_depth_m": 0.25, "closed_depth_m": 0.50, "min_speed_factor": 0.0},
        3: {"slow_depth_m": 0.05, "half_depth_m": 0.15, "closed_depth_m": 0.30, "min_speed_factor": 0.0},
    },
}

SEVERITY_PRESETS = {
    # Without a terrain model the surface is a distance-to-water decay, so the
    # presets control the *width of the flooded corridor* rather than a basin
    # shape. They are calibrated to keep the flood adjacent to water, which is
    # the only structure the available inputs can support. This is a
    # demonstration scenario, not a calibrated flood model.
    "low": {"peak_depth_m": 0.30, "decay_length_m": 90.0, "duration_h": 3.0},
    "moderate": {"peak_depth_m": 0.55, "decay_length_m": 150.0, "duration_h": 4.0},
    "high": {"peak_depth_m": 0.95, "decay_length_m": 240.0, "duration_h": 6.0},
}


@dataclass
class FloodScenario:
    """A declared flood scenario: forcing, shape and timing."""

    scenario_id: str
    severity: str
    start_time_s: int
    peak_time_s: int
    end_time_s: int
    time_step_s: int = 300
    decay_length_m: float | None = None
    peak_depth_m: float | None = None
    duration_h: float | None = None
    observed_source_available: bool = False
    notes: list[str] = field(default_factory=list)

    def resolved(self) -> dict[str, float]:
        preset = SEVERITY_PRESETS[self.severity]
        return {
            "peak_depth_m": self.peak_depth_m if self.peak_depth_m is not None else preset["peak_depth_m"],
            "decay_length_m": (
                self.decay_length_m if self.decay_length_m is not None else preset["decay_length_m"]
            ),
            "duration_h": self.duration_h if self.duration_h is not None else preset["duration_h"],
        }

    def as_manifest_entry(self, model_version: str) -> dict[str, Any]:
        resolved = self.resolved()
        return {
            "model_name": "bkk-scenario-depth-decay",
            "model_version": model_version,
            "time_step_seconds": self.time_step_s,
            "parameters": {
                "scenario_id": self.scenario_id,
                "severity": self.severity,
                "source_role": "scenario",
                "peak_depth_m": resolved["peak_depth_m"],
                "decay_length_m": resolved["decay_length_m"],
                "duration_h": resolved["duration_h"],
                "start_time_s": self.start_time_s,
                "peak_time_s": self.peak_time_s,
                "end_time_s": self.end_time_s,
                "observed_source_available": self.observed_source_available,
                "notes": self.notes,
            },
        }


def build_depth_surface(
    water: gpd.GeoDataFrame,
    *,
    scenario: FloodScenario,
    analysis_crs: str,
    cell_size_m: float = 50.0,
    aoi_geometry: Any = None,
) -> gpd.GeoDataFrame:
    """Rasterise a scenario depth surface as a coarse cell table.

    The surface is built once at peak depth and then scaled through time by
    the hydrograph shape, so the spatial pattern is constant while the
    magnitude follows the scenario. It is clipped to the area of interest:
    water outside the pilot must not flood the pilot.
    """
    if water is None or water.empty:
        raise ValueError("a water layer is required to anchor a scenario depth surface")

    projected = water.to_crs(analysis_crs)
    clip_geometry = None
    if aoi_geometry is not None:
        # Normalise to a single shapely geometry in the analysis CRS. Passing a
        # GeoDataFrame through would align on its index and silently misfilter.
        source = aoi_geometry
        if hasattr(source, "to_crs") and getattr(source, "crs", None) is not None:
            source = source.to_crs(analysis_crs)
        if hasattr(source, "geometry"):
            geometry = source.geometry
            clip_geometry = (
                geometry.union_all() if hasattr(geometry, "union_all") else geometry.unary_union
            )
        else:
            clip_geometry = source
        if clip_geometry is None or clip_geometry.is_empty:
            raise ValueError("the area of interest produced an empty geometry")
        projected = projected[projected.geometry.intersects(clip_geometry)]
        if projected.empty:
            raise ValueError("no water feature intersects the area of interest")
    water_union = projected.geometry.union_all()
    if water_union.is_empty:
        raise ValueError("the water layer produced an empty geometry")

    # The grid spans the water features, intersected with the AOI when given.
    bounds = water_union.bounds
    if aoi_geometry is not None:
        bounds = (
            max(bounds[0], clip_geometry.bounds[0]),
            max(bounds[1], clip_geometry.bounds[1]),
            min(bounds[2], clip_geometry.bounds[2]),
            min(bounds[3], clip_geometry.bounds[3]),
        )
    minx, miny, maxx, maxy = bounds
    xs = np.arange(minx, maxx + cell_size_m, cell_size_m)
    ys = np.arange(miny, maxy + cell_size_m, cell_size_m)
    grid_x, grid_y = np.meshgrid(xs, ys)
    flat_x, flat_y = grid_x.ravel(), grid_y.ravel()

    points = gpd.GeoSeries(
        gpd.points_from_xy(flat_x, flat_y), crs=analysis_crs
    )

    resolved = scenario.resolved()
    decay = resolved["decay_length_m"]
    peak = resolved["peak_depth_m"]

    inside = points.intersects(water_union).to_numpy()
    distances = shapely.distance(points.to_numpy(), water_union)
    depth = peak * np.exp(-distances / max(decay, 1.0))
    depth[inside] = peak

    frame = gpd.GeoDataFrame(
        {
            "cell_id": [f"fc_{int(x)}_{int(y)}" for x, y in zip(flat_x, flat_y)],
            "x": flat_x,
            "y": flat_y,
            "distance_to_water_m": distances,
            "peak_depth_m": np.round(depth, 4),
            "source_role": "scenario",
        },
        geometry=points.to_numpy(),
        crs=analysis_crs,
    )
    frame = frame[frame["peak_depth_m"] > 0.01]
    if aoi_geometry is not None and len(frame):
        # The bounds intersection is a rectangle; the AOI is not. Clip properly.
        frame = frame[frame.geometry.intersects(clip_geometry)]
    return frame.reset_index(drop=True)


def hydrograph_multiplier(time_s: int, scenario: FloodScenario) -> float:
    """Depth scaling from 0 to 1 across the scenario window.

    A rise to the peak followed by a linear recession. It is a shape, not a
    measured hydrograph.
    """
    start, peak, end = scenario.start_time_s, scenario.peak_time_s, scenario.end_time_s
    if time_s <= start:
        return 0.0
    if time_s <= peak:
        span = max(peak - start, 1)
        return float((time_s - start) / span)
    if time_s >= end:
        return 0.0
    span = max(end - peak, 1)
    return float(max(0.0, 1.0 - (time_s - peak) / span))


def build_flood_slices(
    surface: gpd.GeoDataFrame, *, scenario: FloodScenario
) -> pd.DataFrame:
    """Expand the peak surface into time slices following the hydrograph."""
    records: list[dict[str, Any]] = []
    for time_s in range(scenario.start_time_s, scenario.end_time_s + 1, scenario.time_step_s):
        multiplier = hydrograph_multiplier(time_s, scenario)
        if multiplier <= 0:
            continue
        block = surface.copy()
        block["time_s"] = time_s
        block["depth_m"] = (block["peak_depth_m"] * multiplier).round(4)
        block["confidence"] = 0.0  # a scenario has no observational confidence
        block = block[block["depth_m"] > 0.01]
        records.append(block)
    if not records:
        return pd.DataFrame(columns=["time_s", "cell_id", "depth_m", "source_role", "confidence", "x", "y"])
    return pd.concat(records, ignore_index=True)


def _surface_sampler(surface: gpd.GeoDataFrame, sample_step_m: float = 25.0):
    """Return a nearest-cell lookup for the scenario surface.

    Cell centres are indexed in a KD-tree. Sampling a network is then a point
    query rather than a geometry intersection, which is the difference between
    seconds and minutes at pilot scale.
    """
    from scipy.spatial import cKDTree

    if surface is None or len(surface) == 0:
        # A dry baseline run has no surface. Sampling must return zero depth
        # rather than raise: "no water" is a valid state, not a failure.
        def sample(x: float, y: float) -> tuple[float, str | None]:
            return 0.0, None

        return sample

    coordinates = np.column_stack([surface["x"].to_numpy(), surface["y"].to_numpy()])
    tree = cKDTree(coordinates)
    depths = surface["peak_depth_m"].to_numpy()
    cell_ids = surface["cell_id"].to_numpy()

    def sample(x: float, y: float) -> tuple[float, str | None]:
        distance, index = tree.query([x, y])
        return float(depths[int(index)]), (str(cell_ids[int(index)]) if distance <= sample_step_m * 3 else None)

    return sample


def sample_edge_depths(
    edges: gpd.GeoDataFrame, surface: gpd.GeoDataFrame
) -> pd.DataFrame:
    """Sample maximum scenario depth along each network edge.

    An edge is impassable because of its *worst* point, not its average, so the
    maximum is used and the mean is kept for reporting.
    """
    sample = _surface_sampler(surface)
    records: list[dict[str, float]] = []

    for edge in edges.geometry:
        length = float(edge.length)
        steps = max(int(length // 25.0) + 1, 2)
        points = [edge.interpolate(fraction, normalized=True) for fraction in np.linspace(0.0, 1.0, steps)]
        values = [sample(point.x, point.y)[0] for point in points]
        records.append(
            {
                "max_depth_m": float(max(values)),
                "mean_depth_m": float(np.mean(values)),
            }
        )

    return pd.DataFrame(records, index=edges.index)


def build_building_exposure(
    buildings: gpd.GeoDataFrame, surface: gpd.GeoDataFrame
) -> pd.DataFrame:
    """Attach a maximum scenario depth to each building footprint."""
    sample = _surface_sampler(surface)
    records: list[dict[str, Any]] = []
    for building in buildings.itertuples():
        boundary = building.geometry
        parts = [boundary] if boundary.geom_type == "Polygon" else list(boundary.geoms)
        points = []
        for part in parts:
            points.append(part.representative_point())
            # Vertices, sampled: a footprint water crosses is flooded even when
            # its representative point is dry.
            coordinates = shapely.get_coordinates(part)
            if len(coordinates):
                step = max(len(coordinates) // 8, 1)
                points.extend(shapely.points(coordinates[::step]))
        depth = max((sample(point.x, point.y)[0] for point in points), default=0.0)
        records.append(
            {
                "building_id": building.building_id,
                "max_depth_m": round(depth, 4),
                "flooded": bool(depth >= 0.15),
            }
        )
    return pd.DataFrame.from_records(records)


def speed_factor(depth_m: float, thresholds: dict[str, float]) -> float:
    """Transparent impedance curve for one mode.

    piecewise linear between the slow, half and closed depths, monotone by
    construction so that deeper water never makes an edge faster.
    """
    if depth_m <= 0:
        return 1.0
    if depth_m >= thresholds["closed_depth_m"]:
        return 0.0
    if depth_m <= thresholds["slow_depth_m"]:
        return 1.0
    if depth_m <= thresholds["half_depth_m"]:
        span = max(thresholds["half_depth_m"] - thresholds["slow_depth_m"], 1e-6)
        return float(1.0 - 0.5 * (depth_m - thresholds["slow_depth_m"]) / span)
    span = max(thresholds["closed_depth_m"] - thresholds["half_depth_m"], 1e-6)
    return float(max(0.5 - 0.5 * (depth_m - thresholds["half_depth_m"]) / span, 0.0))


def build_edge_states(
    edges: gpd.GeoDataFrame,
    edge_depths: pd.DataFrame,
    *,
    scenario: FloodScenario,
    threshold_set_version: str,
    modes: tuple[int, ...] = (0, 3),
) -> pd.DataFrame:
    """Produce per-edge, per-time, per-mode closure and speed multipliers.

    Every row states the depth that produced it, the threshold set that judged
    it and the reason code, so a closure can always be traced back to a number.
    """
    thresholds = THRESHOLD_SETS[threshold_set_version]
    records: list[dict[str, Any]] = []

    for time_s in range(scenario.start_time_s, scenario.end_time_s + 1, scenario.time_step_s):
        multiplier = hydrograph_multiplier(time_s, scenario)
        for mode in modes:
            mode_thresholds = thresholds[mode]
            for edge_id, max_depth, mean_depth in zip(
                edges["edge_id"], edge_depths["max_depth_m"], edge_depths["mean_depth_m"]
            ):
                depth = round(float(max_depth) * multiplier, 4)
                mean_at_time = round(float(mean_depth) * multiplier, 4)
                # Compute from the rounded depth so the published row is
                # internally consistent: the stated depth and the stated
                # multiplier must correspond, or the provenance chain breaks.
                factor = round(speed_factor(depth, mode_thresholds), 4)
                closed = depth >= mode_thresholds["closed_depth_m"]
                reason = None
                if closed:
                    reason = f"depth_at_or_above_{mode_thresholds['closed_depth_m']}m_mode{mode}"
                elif factor < 1.0:
                    reason = f"depth_impedance_mode{mode}"
                records.append(
                    {
                        "edge_id": edge_id,
                        "time_s": time_s,
                        "mode": mode,
                        "depth_m": round(depth, 4),
                        "mean_depth_m": round(mean_at_time, 4),
                        "speed_multiplier": round(factor, 4),
                        "capacity_multiplier": round(max(factor, 0.0), 4),
                        "closed": bool(closed),
                        "threshold_set_version": threshold_set_version,
                        "reason_code": reason,
                    }
                )
    return pd.DataFrame.from_records(records)
