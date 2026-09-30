"""P1 — population: cells, control reconciliation and weighted synthetic people.

Design rules taken directly from the plan:

* ``population_cells`` holds a **resident baseline**: estimated usual residents
  on a 100 m grid. It is not a daytime or event-time population.
* Persons are **weighted**, not household-synthesised. Open sources support
  aggregate demographic totals but not Bangkok household relationships, so
  household membership, vehicle access and assistance need stay scenario
  variables.
* Agent identifiers are generated from the population version and the seed,
  never from a source row key.
* Absence of evidence yields an explicit ``unknown`` class, never an invented
  precise value.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask

STORAGE_CRS = "OGC:CRS84"


@dataclass
class PopulationQA:
    """Diagnostics that decide whether a population build may be published."""

    population_version: str
    status: str
    total_residents: float
    cell_count: int
    occupied_cell_count: int
    sparsity: float
    control_error: dict[str, Any] = field(default_factory=dict)
    demographics: dict[str, Any] = field(default_factory=dict)
    building_allocation: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "population_version": self.population_version,
            "status": self.status,
            "total_residents": self.total_residents,
            "cell_count": self.cell_count,
            "occupied_cell_count": self.occupied_cell_count,
            "sparsity": self.sparsity,
            "control_error": self.control_error,
            "demographics": self.demographics,
            "building_allocation": self.building_allocation,
            "warnings": self.warnings,
        }


def _stable_cell_id(population_version: str, row: int, col: int) -> str:
    digest = hashlib.sha256(f"{population_version}:{row}:{col}".encode("utf-8")).hexdigest()
    return f"cell_{digest[:16]}"


def build_population_cells(
    raster_path: str | Path,
    aoi_wgs84: gpd.GeoSeries | gpd.GeoDataFrame,
    *,
    population_version: str,
    analysis_crs: str,
    min_cell_population: float = 0.5,
) -> gpd.GeoDataFrame:
    """Vectorise a clipped count raster into a 100 m population cell table.

    The raster is read in its native CRS. Counts are never resampled, and each
    cell keeps its fractional count so aggregate reporting stays consistent
    with the source.
    """
    geometry = aoi_wgs84.geometry.iloc[0] if isinstance(aoi_wgs84, gpd.GeoDataFrame) else aoi_wgs84
    if geometry.geom_type == "MultiPolygon":
        geometry = max(geometry.geoms, key=lambda part: part.area)

    rows: list[dict[str, Any]] = []
    with rasterio.open(raster_path) as dataset:
        nodata = dataset.nodata if dataset.nodata is not None else 0
        source_crs = dataset.crs
        pixels = dataset.read(1)
        mask = geometry_mask([geometry], out_shape=pixels.shape, transform=dataset.transform, invert=True)
        values = np.where(mask, pixels, 0).astype("float64")
        values = np.where(np.isfinite(values), values, 0.0)
        values = np.where(values < 0, 0.0, values)

        # Cell polygons in raster map coordinates, then projected for area.
        from shapely.geometry import box

        ys, xs = np.nonzero(values > min_cell_population)
        cell_geoms = []
        for row_index, col_index in zip(ys, xs):
            # The affine transform maps pixel indices to map coordinates, which
            # is what the cell box needs. Inverting it would return indices.
            x0, y0 = dataset.transform * (col_index, row_index)
            x1, y1 = dataset.transform * (col_index + 1, row_index + 1)
            cell_geoms.append(box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))

        cells_wgs84 = gpd.GeoDataFrame(
            {
                "row": ys.astype(int),
                "col": xs.astype(int),
                "pop_count": values[ys, xs],
            },
            geometry=cell_geoms,
            crs=source_crs or STORAGE_CRS,
        )
        cells = cells_wgs84.to_crs(analysis_crs)
        cells["area_m2"] = cells.geometry.area
        cells["pop_density_per_m2"] = cells["pop_count"] / cells["area_m2"].replace(0, np.nan)
        cells["cell_id"] = [
            _stable_cell_id(population_version, int(row), int(col))
            for row, col in zip(cells["row"], cells["col"])
        ]
        cells["population_version"] = population_version
        cells = cells.to_crs(STORAGE_CRS)
        # Cell centre in degrees: the cell is a rectangle, so the midpoint of
        # its bounds is the centre and avoids a geographic-CRS centroid.
        cells["lon"] = (cells.geometry.bounds.minx + cells.geometry.bounds.maxx) / 2.0
        cells["lat"] = (cells.geometry.bounds.miny + cells.geometry.bounds.maxy) / 2.0
        cells["source_crs"] = str(source_crs)
        cells["source_nodata"] = float(nodata) if nodata is not None else 0.0

    return cells[
        [
            "cell_id",
            "population_version",
            "pop_count",
            "area_m2",
            "pop_density_per_m2",
            "lon",
            "lat",
            "row",
            "col",
            "source_crs",
            "source_nodata",
            "geometry",
        ]
    ].reset_index(drop=True)


def reconcile_to_controls(
    cells: gpd.GeoDataFrame,
    controls: pd.DataFrame,
    *,
    key_column: str = "cell_id",
    group_column: str = "control_group",
    tolerance: float = 0.05,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    """Rescale cell counts inside each control group to its published total.

    Scaling is multiplicative and confined to a group, so relative spatial
    structure from WorldPop survives while the aggregate matches the
    administrative control. Cells absent from a control group keep their
    original value and are reported as uncontrolled.
    """
    working = cells.copy()
    working["pop_scaled"] = working["pop_count"].astype("float64")
    working["control_group"] = pd.NA
    working["control_scaled"] = False

    report: dict[str, Any] = {
        "method": "multiplicative constrained scaling by control group",
        "tolerance": tolerance,
        "groups": [],
        "uncontrolled_total": 0.0,
    }

    if controls.empty:
        report["uncontrolled_total"] = float(working["pop_count"].sum())
        report["status"] = "no_controls_available"
        return working, report

    # Drop any previous control columns before merging: the incoming control
    # table uses the same names, and pandas would silently suffix them into
    # control_group_x / control_group_y and break the group lookup.
    control_columns = {"control_group", "control_scaled", "control_key", "control_population", "factor"}
    base = working.drop(columns=[c for c in control_columns if c in working.columns], errors="ignore")

    joined = base.merge(controls, left_on=key_column, right_on="control_key", how="left")
    matched = joined[joined[group_column].notna()].copy()
    unmatched = joined[joined[group_column].isna()].copy()
    matched["factor"] = np.nan

    for group, block in matched.groupby(group_column, dropna=True):
        target = float(block["control_population"].iloc[0])
        current = float(block["pop_count"].sum())
        factor = target / current if current > 0 else 0.0
        matched.loc[block.index, "factor"] = factor
        report["groups"].append(
            {
                "group": str(group),
                "worldpop_total": round(current, 3),
                "control_total": round(target, 3),
                "factor": round(factor, 6),
                "absolute_error": round(abs(target - current), 3),
                "relative_error": round(abs(target - current) / target, 6) if target else None,
            }
        )

    if matched.empty:
        report["uncontrolled_total"] = round(float(joined["pop_count"].sum()), 3)
        report["status"] = "no_matched_controls"
    else:
        matched["pop_scaled"] = matched["pop_count"] * matched["factor"].astype("float64")
        matched["control_scaled"] = True
    unmatched["control_group"] = pd.NA
    unmatched["control_scaled"] = False
    unmatched["factor"] = np.nan

    rebuilt = pd.concat([matched, unmatched], ignore_index=True)
    rebuilt = gpd.GeoDataFrame(rebuilt, geometry="geometry", crs=working.crs)
    report["uncontrolled_total"] = round(float(unmatched["pop_count"].sum()), 3)
    report["status"] = "scaled" if not matched.empty else "no_matched_controls"
    return rebuilt, report


def assign_demographics(
    cells: pd.DataFrame,
    *,
    sex_shares: dict[str, float] | None,
    age_bands: dict[str, float] | None,
) -> pd.DataFrame:
    """Attach demographic classes to cells from approved aggregate marginals.

    When an age structure source has not passed the licence gate, ``age_band``
    is set to ``unknown`` for every person. That is a deliberate, visible gap:
    the alternative would be an invented age distribution presented as data.
    """
    if sex_shares:
        male = float(sex_shares.get("male", 0.5))
        female = float(sex_shares.get("female", 0.5))
        total = male + female or 1.0
        male, female = male / total, female / total
    else:
        male, female = 0.5, 0.5

    if age_bands:
        bands = list(age_bands.items())
        band_labels = [label for label, _ in bands]
        band_weights = np.array([weight for _, weight in bands], dtype="float64")
        band_weights = band_weights / band_weights.sum()
    else:
        band_labels, band_weights = ["unknown"], np.array([1.0])

    records = []
    for row in cells.itertuples():
        cell_total = float(row.pop_scaled)
        if cell_total <= 0:
            continue
        remaining = cell_total
        for index, (label, share) in enumerate(zip(band_labels, band_weights)):
            for sex_code, sex_share in (("F", female), ("M", male)):
                value = cell_total * float(share) * float(sex_share)
                if value <= 0:
                    continue
                is_last = index == len(band_labels) - 1 and sex_code == "M"
                weight = remaining if is_last else value
                remaining -= weight
                if weight <= 0:
                    continue
                records.append(
                    {
                        "cell_id": row.cell_id,
                        "age_band": label,
                        "sex_code": sex_code,
                        "weight": weight,
                    }
                )
    return pd.DataFrame.from_records(records)


def make_weighted_persons(
    cells: gpd.GeoDataFrame,
    demographics: pd.DataFrame,
    *,
    population_version: str,
    seed: int,
    mobility_profiles: tuple[dict[str, Any], ...],
) -> pd.DataFrame:
    """Create the weighted synthetic person table.

    Each row represents ``weight`` people. Identifiers are derived from the
    population version, the cell and the seed, so a rerun with the same
    configuration reproduces identical identifiers and the table carries no
    source row key.
    """
    if not mobility_profiles:
        raise ValueError("at least one mobility profile is required")

    profile_labels = [profile["label"] for profile in mobility_profiles]
    profile_shares = np.array([float(profile.get("share", 0.0)) for profile in mobility_profiles])
    if profile_shares.sum() <= 0:
        profile_shares = np.ones(len(mobility_profiles)) / len(mobility_profiles)
    profile_shares = profile_shares / profile_shares.sum()

    geometry_lookup = {
        row.cell_id: (row.lon, row.lat, row.pop_density_per_m2)
        for row in cells.itertuples()
    }

    rng = np.random.default_rng(seed)
    records: list[dict[str, Any]] = []
    for index, row in enumerate(demographics.itertuples()):
        lon, lat, density = geometry_lookup[row.cell_id]
        profile_index = int(rng.choice(len(profile_labels), p=profile_shares))
        profile = mobility_profiles[profile_index]
        digest = hashlib.sha256(
            f"{population_version}|{seed}|{row.cell_id}|{row.age_band}|{row.sex_code}".encode("utf-8")
        ).hexdigest()
        records.append(
            {
                "person_id": f"p_{digest[:20]}",
                "population_version": population_version,
                "weight": float(row.weight),
                "age_band": row.age_band,
                "sex_code": row.sex_code,
                "home_cell_id": row.cell_id,
                "home_building_id": None,
                "home_admin_id": None,
                "lon": lon,
                "lat": lat,
                "pop_density_per_m2": density,
                "mobility_profile": profile["label"],
                "mobility_profile_source": profile.get("source", "scenario"),
                # Assistance need and vehicle access are scenario fields: no
                # approved Bangkok source exists, so their provenance is
                # recorded rather than implied.
                "assistance_need": bool(float(profile.get("assistance_share", 0.0)) > 0),
                "assistance_need_source": "scenario",
                "vehicle_access": profile.get("vehicle_access", "none"),
                "vehicle_access_source": "scenario",
                "seed_row_index": index,
            }
        )
    return pd.DataFrame.from_records(records)


def sample_representative_agents(
    persons: pd.DataFrame, *, max_agents: int, seed: int
) -> pd.DataFrame:
    """Draw a representative weighted sample for activity/trajectory generation.

    Routing every weighted person is unnecessary and slow. The sample keeps
    each row's ``weight`` so aggregate results can be re-expanded, and the
    sampling factor is recorded in the run manifest.
    """
    if len(persons) <= max_agents:
        return persons.copy().assign(sampled=False)
    rng = np.random.default_rng(seed)
    take = rng.choice(len(persons), size=max_agents, replace=False)
    subset = persons.iloc[np.sort(take)].copy()
    subset["sampled"] = True
    return subset


def population_summary(persons: pd.DataFrame, cells: gpd.GeoDataFrame) -> dict[str, Any]:
    """Headline resident totals used by the API and the population page."""
    total = float(persons["weight"].sum())
    return {
        "total_weighted_residents": total,
        "weighted_person_records": int(len(persons)),
        "cells": int(len(cells)),
        "occupied_cells": int((cells["pop_count"] > 0).sum()),
        "sex_split": {
            str(sex): round(float(group["weight"].sum()), 2)
            for sex, group in persons.groupby("sex_code")
        },
        "age_bands": {
            str(band): round(float(group["weight"].sum()), 2)
            for band, group in persons.groupby("age_band")
        },
        "mobility_profiles": {
            str(label): round(float(group["weight"].sum()), 2)
            for label, group in persons.groupby("mobility_profile")
        },
    }
