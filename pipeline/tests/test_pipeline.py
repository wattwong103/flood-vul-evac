"""Unit tests for the BKK/FLOW pipeline.

These cover the decisions that would silently corrupt a result if they broke:
the licence gate, population reconciliation, impedance monotonicity, closure
thresholds, refuge separation, and state conservation. They do not need network
access or the staged pilot data.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import buildings, evacuation, flood, manifest, mobility, network, population  # noqa: E402
from bkkflow.sources.registry import LicenceGateError, SourceRegistry  # noqa: E402
from bkkflow.util import stable_hash  # noqa: E402


# --------------------------------------------------------------------------
# licence gate
# --------------------------------------------------------------------------


def _registry() -> SourceRegistry:
    return SourceRegistry(
        {
            "registry_version": "test",
            "country": "Thailand",
            "sources": [
                {
                    "source_id": "ok-source",
                    "agency": "A",
                    "dataset": "D",
                    "model_role": "R",
                    "resource_url": "https://example.org",
                    "licence": "CC BY 4.0",
                    "status": "approved",
                },
                {
                    "source_id": "verify-source",
                    "agency": "B",
                    "dataset": "D",
                    "model_role": "R",
                    "resource_url": "https://example.org",
                    "licence": "unspecified",
                    "status": "verify",
                },
                {
                    "source_id": "rejected-source",
                    "agency": "C",
                    "dataset": "D",
                    "model_role": "R",
                    "resource_url": "https://example.org",
                    "licence": "proprietary",
                    "status": "rejected",
                },
            ],
        }
    )


def test_licence_gate_allows_approved_only() -> None:
    registry = _registry()
    resolved = registry.require_approved(["ok-source"])
    assert [source.source_id for source in resolved] == ["ok-source"]


@pytest.mark.parametrize("source_id", ["verify-source", "rejected-source"])
def test_licence_gate_blocks_unapproved(source_id: str) -> None:
    with pytest.raises(LicenceGateError) as error:
        _registry().require_approved(["ok-source", source_id])
    assert source_id in str(error.value)


def test_licence_gate_blocks_unknown_source() -> None:
    with pytest.raises(LicenceGateError):
        _registry().require_approved(["not-registered"])


def test_registry_rejects_duplicate_source_ids() -> None:
    payload = {
        "registry_version": "test",
        "country": "Thailand",
        "sources": [
            {
                "source_id": "duplicate",
                "resource_url": "https://example.org/one",
                "licence": "CC BY 4.0",
                "status": "approved",
            },
            {
                "source_id": "duplicate",
                "resource_url": "https://example.org/two",
                "licence": "CC BY 4.0",
                "status": "approved",
            },
        ],
    }

    with pytest.raises(ValueError, match="duplicate source_id"):
        SourceRegistry(payload)


# --------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------


def test_stable_hash_is_order_independent() -> None:
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"b": 2, "a": 1})
    assert stable_hash({"a": 1}) != stable_hash({"a": 2})


# --------------------------------------------------------------------------
# population
# --------------------------------------------------------------------------


def _cells() -> gpd.GeoDataFrame:
    geometry = [box(0, 0, 100, 100), box(100, 0, 200, 100), box(0, 100, 100, 200)]
    frame = gpd.GeoDataFrame(
        {
            "cell_id": ["c1", "c2", "c3"],
            "population_version": ["v"] * 3,
            "pop_count": [100.0, 200.0, 300.0],
            "area_m2": [10_000.0] * 3,
            "pop_density_per_m2": [0.01, 0.02, 0.03],
            "lon": [0.0005, 0.0015, 0.0005],
            "lat": [0.0005, 0.0005, 0.0015],
            "geometry": geometry,
        },
        crs="EPSG:3857",
    )
    return frame


def test_reconcile_rescales_to_control_total() -> None:
    cells = _cells()
    controls = pd.DataFrame(
        {
            "control_key": ["c1", "c2", "c3"],
            "control_group": ["g", "g", "g"],
            "control_population": [700.0, 700.0, 700.0],
        }
    )
    scaled, report = population.reconcile_to_controls(cells, controls)
    assert report["status"] == "scaled"
    assert abs(float(scaled["pop_scaled"].sum()) - 700.0) < 1e-6
    # Relative structure from the source surface must survive rescaling.
    ratios = scaled["pop_scaled"] / scaled["pop_count"]
    assert ratios.nunique() == 1


def test_reconcile_leaves_cells_without_controls_untouched() -> None:
    cells = _cells()
    controls = pd.DataFrame(
        {"control_key": ["c1"], "control_group": ["g"], "control_population": [100.0]}
    )
    scaled, report = population.reconcile_to_controls(cells, controls)
    assert report["uncontrolled_total"] == pytest.approx(500.0)
    row = scaled[scaled["cell_id"] == "c3"].iloc[0]
    assert row["pop_scaled"] == pytest.approx(300.0)
    assert bool(row["control_scaled"]) is False


def test_reconcile_without_controls_reports_gap() -> None:
    scaled, report = population.reconcile_to_controls(_cells(), pd.DataFrame())
    assert report["status"] == "no_controls_available"
    assert float(scaled["pop_scaled"].sum()) == pytest.approx(600.0)


def test_demographics_without_age_source_is_unknown() -> None:
    cells = _cells()
    cells["pop_scaled"] = cells["pop_count"]
    demographics = population.assign_demographics(
        cells, sex_shares={"male": 0.5, "female": 0.5}, age_bands=None
    )
    assert set(demographics["age_band"]) == {"unknown"}
    assert demographics["weight"].sum() == pytest.approx(600.0, rel=1e-9)
    assert set(demographics["sex_code"]) == {"M", "F"}


def test_demographics_preserve_total_regardless_of_sex_split() -> None:
    cells = _cells()
    cells["pop_scaled"] = cells["pop_count"]
    for male in (0.4, 0.5, 0.6):
        demographics = population.assign_demographics(cells, sex_shares={"male": male, "female": 1 - male}, age_bands=None)
        assert demographics["weight"].sum() == pytest.approx(600.0, rel=1e-9)


def test_weighted_persons_are_reproducible_and_synthetic() -> None:
    cells = _cells()
    cells["pop_scaled"] = cells["pop_count"]
    demographics = population.assign_demographics(cells, sex_shares={"male": 0.5, "female": 0.5}, age_bands=None)
    profiles = ({"label": "walk_only", "share": 1.0, "vehicle_access": "none"},)
    first = population.make_weighted_persons(
        cells, demographics, population_version="v1", seed=7, mobility_profiles=profiles
    )
    second = population.make_weighted_persons(
        cells, demographics, population_version="v1", seed=7, mobility_profiles=profiles
    )
    assert first["person_id"].tolist() == second["person_id"].tolist()
    assert first["person_id"].str.match(r"^p_[0-9a-f]{20}$").all()
    # A different population version must not reproduce the same identifiers.
    other = population.make_weighted_persons(
        cells, demographics, population_version="v2", seed=7, mobility_profiles=profiles
    )
    assert other["person_id"].tolist() != first["person_id"].tolist()


def test_sample_keeps_weights_and_caps_rows() -> None:
    persons = pd.DataFrame(
        {
            "person_id": [f"p_{index:020d}" for index in range(50)],
            "weight": np.linspace(1.0, 10.0, 50),
        }
    )
    sample = population.sample_representative_agents(persons, max_agents=10, seed=3)
    assert len(sample) == 10
    assert "weight" in sample.columns
    assert sample["sampled"].all()


# --------------------------------------------------------------------------
# flood impedance
# --------------------------------------------------------------------------


def test_speed_factor_is_monotonic_and_bounded() -> None:
    thresholds = flood.THRESHOLD_SETS["bkk-demo-thresholds-v0.1"][mobility.MODE_WALK]
    depths = np.linspace(0, 1.0, 200)
    factors = [flood.speed_factor(float(depth), thresholds) for depth in depths]
    assert all(0.0 <= value <= 1.0 for value in factors)
    assert all(a >= b - 1e-12 for a, b in zip(factors, factors[1:]))


def test_speed_factor_closes_at_threshold() -> None:
    thresholds = flood.THRESHOLD_SETS["bkk-demo-thresholds-v0.1"][mobility.MODE_WALK]
    assert flood.speed_factor(0.0, thresholds) == 1.0
    assert flood.speed_factor(thresholds["closed_depth_m"], thresholds) == 0.0
    assert flood.speed_factor(thresholds["closed_depth_m"] + 0.5, thresholds) == 0.0


def test_vehicle_threshold_is_stricter_than_walking() -> None:
    sets = flood.THRESHOLD_SETS["bkk-demo-thresholds-v0.1"]
    assert sets[mobility.MODE_CAR]["closed_depth_m"] < sets[mobility.MODE_WALK]["closed_depth_m"]


def test_hydrograph_rises_and_recedes() -> None:
    scenario = flood.FloodScenario(
        scenario_id="t", severity="moderate", start_time_s=0, peak_time_s=3600, end_time_s=7200
    )
    assert flood.hydrograph_multiplier(0, scenario) == 0.0
    assert flood.hydrograph_multiplier(3600, scenario) == pytest.approx(1.0)
    assert flood.hydrograph_multiplier(7200, scenario) == 0.0
    assert flood.hydrograph_multiplier(1800, scenario) == pytest.approx(0.5)
    mid = flood.hydrograph_multiplier(5400, scenario)
    assert 0.0 < mid < 1.0


def test_dry_scenario_sampler_returns_zero() -> None:
    empty = gpd.GeoDataFrame({"x": [], "y": [], "peak_depth_m": [], "cell_id": []})
    sample = flood._surface_sampler(empty)
    assert sample(0.0, 0.0) == (0.0, None)


# --------------------------------------------------------------------------
# buildings: height is not refuge status
# --------------------------------------------------------------------------


def _buildings_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "osm_id": [1, 2, 3],
            "osm_type": ["way"] * 3,
            "building": ["yes", "house", "school"],
            "amenity": [None, None, "shelter"],
            "height": ["151 m", None, None],
            "building:levels": [None, "3", None],
            "geometry": [box(100.500, 13.720, 100.5001, 13.7201), box(100.501, 13.720, 100.5011, 13.7201), box(100.502, 13.720, 100.5021, 13.7201)],
        },
        crs="OGC:CRS84",
    )


def test_height_precedence_prefers_tagged_over_levels() -> None:
    aoi = gpd.GeoDataFrame(geometry=[box(100.49, 13.70, 100.52, 13.74)], crs="OGC:CRS84")
    table = buildings.build_building_table(
        _buildings_frame(), aoi_frame=aoi, analysis_crs="EPSG:32647", building_version="v"
    )
    tagged = table[table["height_source"] == "osm_height"]
    assert len(tagged) == 1
    assert tagged["height_m"].iloc[0] == pytest.approx(151.0)

    derived = table[table["height_source"] == "osm_building_levels"]
    assert len(derived) == 1
    assert derived["height_m"].iloc[0] == pytest.approx(9.0)  # 3 levels x 3.0 m
    assert derived["height_confidence"].iloc[0] == "derived_from_levels"

    unknown = table[table["height_source"] == "unknown"]
    assert unknown["height_m"].isna().all()


def test_height_parsing_handles_units() -> None:
    assert buildings._parse_height("30") == 30.0
    assert buildings._parse_height("132 m") == 132.0
    assert buildings._parse_height("100'") == pytest.approx(30.48)
    assert buildings._parse_height("no") is None
    assert buildings._parse_height(None) is None


def test_osc_shelter_tag_is_never_a_verified_refuge() -> None:
    aoi = gpd.GeoDataFrame(geometry=[box(100.49, 13.70, 100.52, 13.74)], crs="OGC:CRS84")
    table = buildings.build_building_table(
        _buildings_frame(), aoi_frame=aoi, analysis_crs="EPSG:32647", building_version="v"
    )
    assert not table["refuge_verified"].any()
    candidates = table[table["refuge_status"] != "not_a_refuge"]
    assert len(candidates) == 1
    assert candidates["refuge_status"].iloc[0] == "osm_tagged_candidate_unverified"
    assert candidates["refuge_capacity"].isna().all()


def test_height_coverage_reports_unknowns() -> None:
    aoi = gpd.GeoDataFrame(geometry=[box(100.49, 13.70, 100.52, 13.74)], crs="OGC:CRS84")
    table = buildings.build_building_table(
        _buildings_frame(), aoi_frame=aoi, analysis_crs="EPSG:32647", building_version="v"
    )
    coverage = buildings.height_coverage(table)
    assert coverage["buildings"] == 3
    assert coverage["tagged_height"] == 1
    assert coverage["derived_from_levels"] == 1
    assert coverage["unknown_height"] == 1


# --------------------------------------------------------------------------
# network
# --------------------------------------------------------------------------


def _roads() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "osm_id": [1, 2, 3, 4],
            "osm_type": ["way"] * 4,
            "highway": ["residential", "footway", "primary", "service"],
            "geometry": [
                LineString([(100.500, 13.720), (100.501, 13.720)]),
                LineString([(100.501, 13.720), (100.502, 13.720)]),
                LineString([(100.500, 13.721), (100.502, 13.721)]),
                LineString([(100.500, 13.720), (100.500, 13.721)]),
            ],
        },
        crs="OGC:CRS84",
    )


def test_network_access_rules_differ_by_mode() -> None:
    build = network.build_network(
        _roads(), analysis_crs="EPSG:32647", network_version="t"
    )
    edges = build.edges
    assert edges["walk_allowed"].all()
    # Footways are not drivable; primary roads are.
    assert not edges.loc[edges["highway"] == "footway", "vehicle_allowed"].any()
    assert edges.loc[edges["highway"] == "primary", "vehicle_allowed"].all()


def test_edge_ids_are_geometry_derived_and_stable() -> None:
    first = network.build_network(_roads(), analysis_crs="EPSG:32647", network_version="t")
    second = network.build_network(_roads().iloc[::-1], analysis_crs="EPSG:32647", network_version="t")
    assert set(first.edges["edge_id"]) == set(second.edges["edge_id"])


def test_closed_way_becomes_a_routable_line() -> None:
    frame = gpd.GeoDataFrame(
        {
            "osm_id": [1],
            "osm_type": ["way"],
            "highway": ["pedestrian"],
            "geometry": [box(100.500, 13.720, 100.501, 13.721)],
        },
        crs="OGC:CRS84",
    )
    build = network.build_network(frame, analysis_crs="EPSG:32647", network_version="t")
    assert len(build.edges) >= 1


# --------------------------------------------------------------------------
# routing graph respects closures at build time
# --------------------------------------------------------------------------


def _routing_edges(records: list[dict]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:32647")


def test_excluded_edges_are_absent_from_the_routing_graph() -> None:
    build = network.build_network(_roads(), analysis_crs="EPSG:32647", network_version="t")
    closed = set(build.edges.loc[build.edges["highway"] == "primary", "edge_id"])
    full = mobility.build_routing_graph(build.edges, mobility.MODE_CAR)
    reduced = mobility.build_routing_graph(
        build.edges, mobility.MODE_CAR, excluded_edge_ids=closed
    )
    assert reduced.number_of_edges() < full.number_of_edges()
    remaining = {data["edge_id"] for _, _, data in reduced.edges(data=True)}
    assert not (remaining & closed)


def test_flood_multiplier_changes_cost_and_speed_attributes() -> None:
    edges = _routing_edges([
        {
            "edge_id": "slow",
            "u": 0,
            "v": 1,
            "highway": "residential",
            "length_m": 100.0,
            "speed_walk_mps": 2.0,
            "speed_vehicle_mps": 10.0,
            "geometry": LineString([(0.0, 0.0), (100.0, 0.0)]),
        }
    ])

    graph = mobility.build_routing_graph(
        edges, mobility.MODE_WALK, speed_multipliers={"slow": 0.5}
    )

    edge = graph[0][1]
    assert edge["cost"] == pytest.approx(100.0)
    assert edge["dry_speed_mps"] == pytest.approx(2.0)
    assert edge["speed_multiplier"] == pytest.approx(0.5)
    assert edge["speed_mps"] == pytest.approx(1.0)


def test_zero_flood_multiplier_removes_edge() -> None:
    edges = _routing_edges(
        [
            {
                "edge_id": "closed",
                "u": 0,
                "v": 1,
                "highway": "residential",
                "length_m": 80.0,
                "speed_walk_mps": 2.0,
                "speed_vehicle_mps": 10.0,
                "geometry": LineString([(0.0, 0.0), (80.0, 0.0)]),
            },
            {
                "edge_id": "open-parallel",
                "u": 0,
                "v": 1,
                "highway": "residential",
                "length_m": 100.0,
                "speed_walk_mps": 1.0,
                "speed_vehicle_mps": 10.0,
                "geometry": LineString([(0.0, 0.0), (100.0, 0.0)]),
            },
        ]
    )

    graph = mobility.build_routing_graph(
        edges,
        mobility.MODE_WALK,
        speed_multipliers={"closed": 0.0, "open-parallel": 1.0},
    )

    assert graph.number_of_edges() == 1
    assert graph[0][1]["edge_id"] == "open-parallel"


@pytest.mark.parametrize("multiplier", [-0.1, 1.1, np.nan])
def test_flood_multiplier_rejects_values_outside_closed_open_domain(
    multiplier: float,
) -> None:
    edges = _routing_edges([
        {
            "edge_id": "invalid",
            "u": 0,
            "v": 1,
            "highway": "residential",
            "length_m": 100.0,
            "speed_walk_mps": 1.0,
            "speed_vehicle_mps": 10.0,
            "geometry": LineString([(0.0, 0.0), (100.0, 0.0)]),
        }
    ])

    with pytest.raises(ValueError, match="between 0 and 1"):
        mobility.build_routing_graph(
            edges, mobility.MODE_WALK, speed_multipliers={"invalid": multiplier}
        )


def test_flood_multiplier_must_cover_every_routable_edge() -> None:
    edges = _routing_edges([
        {
            "edge_id": "missing",
            "u": 0,
            "v": 1,
            "highway": "residential",
            "length_m": 100.0,
            "speed_walk_mps": 1.0,
            "speed_vehicle_mps": 10.0,
            "geometry": LineString([(0.0, 0.0), (100.0, 0.0)]),
        }
    ])

    with pytest.raises(ValueError, match="missing speed multiplier"):
        mobility.build_routing_graph(
            edges, mobility.MODE_WALK, speed_multipliers={}
        )


def test_route_selection_uses_flood_adjusted_cost() -> None:
    edges = _routing_edges([
        {
            "edge_id": "direct",
            "u": 0,
            "v": 1,
            "highway": "residential",
            "length_m": 100.0,
            "speed_walk_mps": 1.0,
            "speed_vehicle_mps": 10.0,
            "geometry": LineString([(0.0, 0.0), (100.0, 0.0)]),
        },
        {
            "edge_id": "detour-a",
            "u": 0,
            "v": 2,
            "highway": "residential",
            "length_m": 60.0,
            "speed_walk_mps": 1.0,
            "speed_vehicle_mps": 10.0,
            "geometry": LineString([(0.0, 0.0), (50.0, 50.0)]),
        },
        {
            "edge_id": "detour-b",
            "u": 2,
            "v": 1,
            "highway": "residential",
            "length_m": 60.0,
            "speed_walk_mps": 1.0,
            "speed_vehicle_mps": 10.0,
            "geometry": LineString([(50.0, 50.0), (100.0, 0.0)]),
        },
    ])
    multipliers = {"direct": 0.2, "detour-a": 1.0, "detour-b": 1.0}
    index = mobility.NetworkIndex(
        mobility.build_routing_graph(
            edges, mobility.MODE_WALK, speed_multipliers=multipliers
        ),
        "EPSG:32647",
    )

    path, cost = index.route(0, 1)

    assert path == [0, 2, 1]
    assert cost == pytest.approx(120.0)


def test_parallel_edge_selection_keeps_adjusted_winner_attributes() -> None:
    edges = _routing_edges([
        {
            "edge_id": "dry-fast",
            "u": 0,
            "v": 1,
            "highway": "residential",
            "length_m": 100.0,
            "speed_walk_mps": 2.0,
            "speed_vehicle_mps": 10.0,
            "geometry": LineString([(0.0, 0.0), (100.0, 0.0)]),
        },
        {
            "edge_id": "wet-fast",
            "u": 0,
            "v": 1,
            "highway": "residential",
            "length_m": 90.0,
            "speed_walk_mps": 1.0,
            "speed_vehicle_mps": 10.0,
            "geometry": LineString([(0.0, 0.0), (90.0, 0.0)]),
        },
    ])
    graph = mobility.build_routing_graph(
        edges,
        mobility.MODE_WALK,
        speed_multipliers={"dry-fast": 0.2, "wet-fast": 1.0},
    )

    edge = graph[0][1]
    assert edge["edge_id"] == "wet-fast"
    assert edge["cost"] == pytest.approx(90.0)
    assert edge["length_m"] == pytest.approx(90.0)
    assert edge["dry_speed_mps"] == pytest.approx(1.0)
    assert edge["speed_multiplier"] == pytest.approx(1.0)
    assert edge["speed_mps"] == pytest.approx(1.0)


def test_routing_graph_nodes_carry_coordinates() -> None:
    build = network.build_network(_roads(), analysis_crs="EPSG:32647", network_version="t")
    graph = mobility.build_routing_graph(build.edges, mobility.MODE_WALK)
    assert all("x" in data and "y" in data for _, data in graph.nodes(data=True))


def test_network_index_snaps_and_routes() -> None:
    build = network.build_network(_roads(), analysis_crs="EPSG:32647", network_version="t")
    index = mobility.NetworkIndex(
        mobility.build_routing_graph(build.edges, mobility.MODE_WALK), "EPSG:32647"
    )
    # Snap to a node that actually exists in the projected graph.
    origin_xy = next(iter(index.graph.nodes(data=True)))[1]
    node = index.snap(origin_xy["x"], origin_xy["y"])
    assert node is not None
    path, cost = index.route(node, node)
    assert path == [node] and cost == 0.0
    # Far outside the network there is no snap target.
    assert index.snap(1e7, 1e7) is None


# --------------------------------------------------------------------------
# evacuation state machine
# --------------------------------------------------------------------------


def _cohort(rows: int = 10) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "person_id": [f"p_{index:020d}" for index in range(rows)],
            "weight": [10.0] * rows,
            "lon": [0.0] * rows,
            "lat": [0.0] * rows,
            "x": [0.0] * rows,
            "y": [0.0] * rows,
            "exposed": [True] * rows,
            "in_order_area": [True] * rows,
        }
    )


def _destinations() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [{"dest_id": "d1", "x": 100.0, "y": 0.0, "capacity": 50, "verified": False}],
        geometry=[Point(100.0, 0.0)],
        crs="EPSG:32647",
    )


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        (pd.DataFrame({"state": ["arrived"] * 3 + ["route_failed"],
                       "event_time_s": [2100, 900, 1500, -1],
                       "weight": [0.49, 0.02, 0.49, -5]}),
         {"p5": 20.0, "median": 20.0, "p95": 30.0}),
        (pd.DataFrame({"state": ["arrived"] * 4,
                       "event_time_s": [1800, 900, 1500, 1500],
                       "weight": [0.4, 0.1, 0.2, 0.3]}),
         {"p5": 10.0, "median": 20.0, "p95": 25.0}),
        (pd.DataFrame({"state": ["arrived"] * 3,
                       "event_time_s": [900, 1500, 2100], "weight": [0.3, 0.1, 0.2]}),
         {"p5": 10.0, "median": 10.0, "p95": 30.0}),
        (pd.DataFrame({"state": ["route_failed"], "event_time_s": [np.nan],
                       "weight": [0.0]}),
         {"p5": None, "median": None, "p95": None}),
    ],
)
def test_weighted_clearance_inverse_ecdf_ties_and_no_arrivals(states, expected) -> None:
    assert evacuation.weighted_clearance_minutes(states, warning_time_s=300) == expected


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        *[("weight", value, "arrived weight") for value in (0, -1, np.nan, np.inf, "bad")],
        *[("event_time_s", value, "clearance") for value in (299, np.nan, np.inf, "bad")],
    ],
)
def test_weighted_clearance_rejects_invalid_arrived_values(column, value, message) -> None:
    data = {"state": ["arrived"], "event_time_s": [600.0], "weight": [1.0]}
    data[column] = [value]
    with pytest.raises(ValueError, match=message):
        evacuation.weighted_clearance_minutes(pd.DataFrame(data), warning_time_s=300.0)


def test_every_cohort_member_reaches_exactly_one_terminal_state() -> None:
    cohort = _cohort(20)
    scenario = evacuation.EvacuationScenario(
        scenario_id="t", warning_time_s=600, warning_reach=1.0, compliance=1.0,
        preparation_delay_mean_s=0.0, preparation_delay_sd_s=0.0,
    )
    states, outcomes = evacuation.simulate_evacuation(
        cohort,
        destinations=_destinations(),
        route_lookup=lambda *args: (60.375, 500.0, ["e1", "e2"]),
        scenario=scenario,
        seed=1,
    )
    conservation = evacuation.check_conservation(states, 200.0)
    assert conservation["passed"], conservation
    assert set(states["state"]) <= set(evacuation.TERMINAL_STATES)
    assert outcomes["cohort_weighted"] == pytest.approx(200.0)
    expected = evacuation.weighted_clearance_minutes(states, warning_time_s=600.0)
    assert outcomes["clearance_time_minutes"] == expected
    reconstructed = (float(states.loc[states["state"] == "arrived", "event_time_s"].iloc[0]) - 600) / 60
    assert abs(reconstructed - expected["median"]) < 0.01


def test_capacity_creates_overflow_not_silent_loss() -> None:
    cohort = _cohort(20)  # 200 people represented
    scenario = evacuation.EvacuationScenario(scenario_id="t", warning_time_s=0)
    states, outcomes = evacuation.simulate_evacuation(
        cohort,
        destinations=_destinations(),  # capacity 50
        route_lookup=lambda *args: (600.0, 500.0, ["e1"]),
        scenario=scenario,
        seed=1,
    )
    assert outcomes["arrived_weighted"] <= 50.0
    assert outcomes["unserved_weighted"] > 0
    assert "shelter_full" in states["state"].tolist()
    assert outcomes["destinations"][0]["remaining"] == 0


def test_zero_compliance_means_nobody_departs() -> None:
    cohort = _cohort(10)
    scenario = evacuation.EvacuationScenario(
        scenario_id="t", warning_time_s=0, compliance=0.0, warning_reach=1.0
    )
    states, outcomes = evacuation.simulate_evacuation(
        cohort,
        destinations=_destinations(),
        route_lookup=lambda *args: (600.0, 500.0, []),
        scenario=scenario,
        seed=1,
    )
    assert set(states["state"]) == {"did_not_depart"}
    assert set(states["reason"]) == {"not_compliant"}
    assert outcomes["arrived_weighted"] == 0.0


def test_unreachable_people_are_route_failed_not_dropped() -> None:
    cohort = _cohort(10)
    scenario = evacuation.EvacuationScenario(
        scenario_id="t", warning_time_s=0, compliance=1.0, warning_reach=1.0
    )
    states, _ = evacuation.simulate_evacuation(
        cohort,
        destinations=_destinations(),
        route_lookup=lambda *args: None,
        scenario=scenario,
        seed=1,
    )
    assert set(states["state"]) == {"route_failed"}
    assert set(states["reason"]) == {"no_path_under_closure"}


def _eligible_people(rows: int = 8) -> pd.DataFrame:
    return pd.DataFrame({"person_id": [f"p_{i}" for i in range(rows)],
                         "weight": [i + 0.5 for i in range(rows)],
                         "lon": [100.5 + i * 0.0001 for i in range(rows)],
                         "lat": [13.7] * rows})


def test_dry_and_wet_share_fixed_cohort_while_exposure_stays_separate() -> None:
    persons = _eligible_people()
    persons.loc[7, "lon"] = 100.6  # flooded and present, but outside the order area
    common = {"aoi_id": "aoi-a", "seed": 29092026, "max_agents": 1200}
    dry, dry_meta = evacuation.select_cohort(
        persons, surface_depth_at=lambda *_: 9.0, scenario_time_s=0,
        min_depth_m=0.0, **common)
    wet, wet_meta = evacuation.select_cohort(
        persons, surface_depth_at=lambda lon, _: 0.5 if lon > 100.55 else 0.0,
        scenario_time_s=0, min_depth_m=0.15, expected_metadata=dry_meta, **common)
    columns = ["person_id", "order_id", "weight", "sampling_probability"]
    pd.testing.assert_frame_equal(dry[columns], wet[columns])
    assert dry_meta["cohort_digest"] == wet_meta["cohort_digest"]
    assert dry["exposed"].sum() == 0 and dry_meta["exposed_weighted"] == 0.0
    assert wet["exposed"].sum() == 0 and wet_meta["exposed_weighted"] == persons.loc[7, "weight"]
    assert wet_meta["present_weighted"] == dry_meta["present_weighted"] == persons["weight"].sum()
    assert persons.loc[7, "person_id"] not in set(wet["person_id"])
    assert len(wet) == len(dry) == len(persons) - 1


def test_fixed_cohort_sampling_is_deterministic_capped_and_aoi_scoped() -> None:
    persons = _eligible_people(20)
    sampled = population.sample_representative_agents(persons, max_agents=5, seed=29092026)
    kwargs = {"surface_depth_at": lambda *_: 0.0, "scenario_time_s": 0,
              "min_depth_m": 0.0, "seed": 29092026, "max_agents": 5,
              "sample_persons": sampled, "sampling_probability": 0.25}
    first, meta = evacuation.select_cohort(sampled, aoi_id="aoi-a", **kwargs)
    repeat, repeat_meta = evacuation.select_cohort(sampled, aoi_id="aoi-a", **kwargs)
    other, other_meta = evacuation.select_cohort(sampled, aoi_id="aoi-b", **kwargs)
    assert first["person_id"].tolist() == repeat["person_id"].tolist()
    assert len(first) == 5 and meta["sampling_probability"] == pytest.approx(0.25)
    assert meta["cohort_digest"] == repeat_meta["cohort_digest"]
    assert meta["cohort_digest"] != other_meta["cohort_digest"]
    assert set(first["order_id"]).isdisjoint(other["order_id"])
    with pytest.raises(ValueError, match="exceeds the declared upstream sample cap"):
        evacuation.select_cohort(
            persons, aoi_id="aoi-a", **{**kwargs, "sample_persons": persons})


def test_fixed_cohort_rejects_requested_digest_mismatch() -> None:
    persons = _eligible_people()
    sampled = population.sample_representative_agents(persons, max_agents=5, seed=29092026)
    common = {"surface_depth_at": lambda *_: 0.0, "scenario_time_s": 0,
              "min_depth_m": 0.0, "aoi_id": "aoi-a", "seed": 29092026,
              "max_agents": 5, "sample_persons": sampled,
              "sampling_probability": 0.625}
    _, reference = evacuation.select_cohort(sampled, **common)
    unchanged = reference.copy()
    changed = sampled.copy()
    changed.loc[0, "weight"] += 1
    for candidate, overrides in ((changed, {"sample_persons": changed}),
                                 (sampled, {"aoi_id": "aoi-b"}),
                                 (sampled, {"seed": 7}),
                                 (sampled, {"max_agents": 6})):
        with pytest.raises(ValueError, match="cohort mismatch"):
            evacuation.select_cohort(
                candidate, **{**common, **overrides}, expected_metadata=reference)
    assert reference == unchanged


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------


def test_manifest_component_shape() -> None:
    component = manifest.component("n", "1.0", {"k": 1})
    assert component == {"name": "n", "version": "1.0", "parameters": {"k": 1}}


def test_real_run_manifest_conforms_to_schema() -> None:
    """Any published run must validate against the committed JSON Schema."""
    runs_dir = manifest.REPO_ROOT / "runs"
    manifests = sorted(runs_dir.glob("*/manifest.json"), key=lambda path: path.stat().st_mtime)
    if not manifests:
        pytest.skip("no runs available")
    import json

    payload = json.loads(manifests[-1].read_text(encoding="utf-8"))
    assert manifest.validate_manifest(payload) == []
