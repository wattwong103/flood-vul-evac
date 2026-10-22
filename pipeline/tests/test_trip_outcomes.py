"""Tests for trip outcomes under a flood (BKK-055d).

Every everyday trip is checked against the road states in force when it
departs: unaffected, detour (with the extra time), or no route. Trips outside
the flood window, and trips with no dry route, are counted apart, never as
flood effects. The road-state rule matches the API and site: closed only on a
stored closed flag; slowed at any speed reduction.

The test network is four nodes: a direct way 1-2-3 (200 m) and a detour
1-4-3 (about 283 m).
"""

from __future__ import annotations

import gc
import sys
import weakref
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import trip_outcomes  # noqa: E402

START, END = 64800, 79200
WALK, CAR = 0, 3
NODES = {1: (0.0, 0.0), 2: (100.0, 0.0), 3: (200.0, 0.0), 4: (100.0, 100.0)}
WALK_SPEED, CAR_SPEED = 1.0, 10.0
DETOUR_M = 2 * (100.0 ** 2 + 100.0 ** 2) ** 0.5


def _edges(lengths: dict[str, float] | None = None) -> gpd.GeoDataFrame:
    rows = []
    for edge_id, u, v in (("e12", 1, 2), ("e23", 2, 3), ("e14", 1, 4), ("e43", 4, 3)):
        line = LineString([NODES[u], NODES[v]])
        rows.append({
            "edge_id": edge_id, "u": u, "v": v, "highway": "residential",
            "length_m": (lengths or {}).get(edge_id, line.length),
            "speed_walk_mps": WALK_SPEED, "speed_vehicle_mps": CAR_SPEED, "geometry": line,
        })
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:32647")


def _trip(trip_id: str, mode: int, depart: int, *, status: str = "routed", purpose: str = "work") -> dict:
    speed = WALK_SPEED if mode == WALK else CAR_SPEED
    return {
        "trip_id": trip_id, "person_id": f"p_{trip_id}", "seq": 1, "origin_purpose": "home",
        "dest_purpose": purpose, "mode": mode, "depart_time_s": depart,
        "duration_s": int(round(200.0 / speed)) if status == "routed" else 0, "distance_m": 200.0,
        "origin_x": 0.0, "origin_y": 0.0, "dest_x": 200.0, "dest_y": 0.0, "weight": 2.5,
        "route_status": status, "failure_reason": None if status == "routed" else "no_path_under_closure",
    }


def _waypoints(trips: pd.DataFrame) -> pd.DataFrame:
    """Every routed trip took the direct way 1-2-3."""
    rows = []
    for trip in trips.itertuples():
        if trip.route_status != "routed":
            continue
        speed = WALK_SPEED if trip.mode == WALK else CAR_SPEED
        for seq, (node, edge) in enumerate(((1, "e12"), (2, "e23"), (3, None))):
            x, y = NODES[node]
            rows.append({"trip_id": trip.trip_id, "person_id": trip.person_id, "seq": seq,
                         "x": x, "y": y, "edge_id": edge, "cumulative_time_s": seq * 100.0 / speed,
                         "mode": trip.mode})
    return pd.DataFrame(rows)


def _states(overrides: dict[tuple[int, int, str], tuple[float, bool]] | None = None) -> pd.DataFrame:
    """Open roads at two state times; overrides map (time, mode, edge) to (speed, closed)."""
    rows = []
    for time_s in (START, START + 300):
        for mode in (WALK, CAR):
            for edge_id in ("e12", "e23", "e14", "e43"):
                speed, closed = (overrides or {}).get((time_s, mode, edge_id), (1.0, False))
                rows.append({"edge_id": edge_id, "time_s": time_s, "mode": mode, "depth_m": 0.0,
                             "speed_multiplier": speed, "capacity_multiplier": speed, "closed": closed,
                             "threshold_set_version": "bkk-demo-thresholds-v0.1", "reason_code": None})
    return pd.DataFrame(rows)


def _classify(trips: list[dict], states: pd.DataFrame, *, edges: gpd.GeoDataFrame | None = None,
              waypoints: pd.DataFrame | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(trips)
    result = trip_outcomes.classify_trip_outcomes(
        frame, _waypoints(frame) if waypoints is None else waypoints,
        _edges() if edges is None else edges, states, analysis_crs="EPSG:32647", window=(START, END),
    )
    return result.set_index("trip_id")


def test_a_closed_road_on_the_route_forces_a_detour_with_its_extra_time() -> None:
    states = _states({(START, WALK, "e23"): (0.0, True)})
    row = _classify([_trip("t1", WALK, START + 100)], states).loc["t1"]

    assert row["outcome"] == "detour"
    assert row["dry_time_s"] == pytest.approx(200.0 / WALK_SPEED)
    assert row["flood_time_s"] == pytest.approx(DETOUR_M / WALK_SPEED)
    assert row["extra_time_s"] == pytest.approx((DETOUR_M - 200.0) / WALK_SPEED)
    assert row["blocking_edge_id"] == "e23"
    assert row["state_time_s"] == START
    assert row["weight"] == pytest.approx(2.5)


def test_a_slowed_road_is_a_detour_when_the_way_round_is_quicker() -> None:
    # At half speed the direct way costs 300 m-equivalent, more than the 283 m detour.
    states = _states({(START, CAR, "e23"): (0.5, False)})
    row = _classify([_trip("t1", CAR, START + 100)], states).loc["t1"]

    assert row["outcome"] == "detour"
    assert row["flood_time_s"] == pytest.approx(DETOUR_M / CAR_SPEED)
    assert row["blocking_edge_id"] == "e23"


def test_no_open_way_is_no_route() -> None:
    states = _states({(START, WALK, "e23"): (0.0, True), (START, WALK, "e43"): (0.0, True)})
    row = _classify([_trip("t1", WALK, START + 100)], states).loc["t1"]

    assert row["outcome"] == "no_route"
    assert pd.isna(row["flood_time_s"])
    assert pd.isna(row["extra_time_s"])
    assert row["blocking_edge_id"] == "e23"
    # Every road at the destination is closed: the trip keeps its dry ends.
    assert row["no_route_reason"] == "destination_cut_off"


def test_no_route_between_open_ends_is_no_path() -> None:
    # 1 keeps e14 and 3 keeps e23, but 1-4 and 2-3 are no longer joined.
    states = _states({(START, WALK, "e12"): (0.0, True), (START, WALK, "e43"): (0.0, True)})
    row = _classify([_trip("t1", WALK, START + 100)], states).loc["t1"]

    assert row["outcome"] == "no_route"
    assert row["no_route_reason"] == "no_path"
    assert row["blocking_edge_id"] == "e12"


def test_a_closed_origin_is_named_as_such() -> None:
    states = _states({(START, WALK, "e12"): (0.0, True), (START, WALK, "e14"): (0.0, True)})
    row = _classify([_trip("t1", WALK, START + 100)], states).loc["t1"]

    assert row["outcome"] == "no_route"
    assert row["no_route_reason"] == "origin_cut_off"


def test_a_closed_road_is_named_before_an_earlier_slowed_one() -> None:
    states = _states({(START, WALK, "e12"): (0.5, False), (START, WALK, "e23"): (0.0, True)})
    row = _classify([_trip("t1", WALK, START + 100)], states).loc["t1"]

    assert row["outcome"] == "detour"
    assert row["blocking_edge_id"] == "e23"
    assert pd.isna(row["no_route_reason"])


def test_open_roads_leave_the_trip_unaffected() -> None:
    states = _states({(START, WALK, "e43"): (0.0, True)})  # closed, but not on the route
    row = _classify([_trip("t1", WALK, START + 100)], states).loc["t1"]

    assert row["outcome"] == "unaffected"
    assert row["extra_time_s"] == 0.0
    assert row["flood_time_s"] == pytest.approx(row["dry_time_s"])
    assert pd.isna(row["blocking_edge_id"])


def test_the_state_in_force_at_departure_is_used() -> None:
    # Closed only from START + 300; a trip leaving at START + 200 still goes direct.
    states = _states({(START + 300, WALK, "e23"): (0.0, True)})
    result = _classify([_trip("early", WALK, START + 200), _trip("late", WALK, START + 400)], states)

    assert result.loc["early", "outcome"] == "unaffected"
    assert result.loc["early", "state_time_s"] == START
    assert result.loc["late", "outcome"] == "detour"
    assert result.loc["late", "state_time_s"] == START + 300


def test_trips_outside_the_window_or_without_a_dry_route_are_counted_apart() -> None:
    result = _classify(
        [_trip("morning", WALK, 30000), _trip("failed", WALK, START + 100, status="unroutable")],
        _states({(START, WALK, "e23"): (0.0, True)}),
    )

    assert result.loc["morning", "outcome"] == "outside_flood_window"
    assert result.loc["failed", "outcome"] == "not_routed_dry"
    assert result["extra_time_s"].isna().all()


def test_every_trip_appears_once_with_its_purpose_and_cell() -> None:
    trips = [_trip("a", WALK, START + 100, purpose="education"), _trip("b", CAR, 30000)]
    result = _classify(trips, _states())

    assert sorted(result.index) == ["a", "b"]
    assert result.loc["a", "dest_purpose"] == "education"
    assert result.loc["a", "origin_cell"] == "g1km_0_0"
    assert set(trip_outcomes.OUTCOMES) >= set(result["outcome"])


@pytest.mark.parametrize(
    ("depart", "outcome"),
    [(START - 1, "outside_flood_window"), (START, "detour"), (END, "detour"), (END + 1, "outside_flood_window")],
)
def test_the_flood_window_includes_both_ends(depart: int, outcome: str) -> None:
    states = _states({(time, WALK, "e23"): (0.0, True) for time in (START, START + 300)})
    assert _classify([_trip("t1", WALK, depart)], states).loc["t1", "outcome"] == outcome


def test_an_equal_cost_way_round_is_not_a_detour() -> None:
    # Every road is 100.00245 m, so both ways cost 200.0049 s; the stored dry
    # time is rounded to 200.0 s, which must not read as a 0.005 s detour.
    edges = _edges({edge: 100.00245 for edge in ("e12", "e23", "e14", "e43")})
    row = _classify([_trip("t1", WALK, START + 100)], _states({(START, WALK, "e23"): (0.0, True)}),
                    edges=edges).loc["t1"]

    assert row["outcome"] == "unaffected"
    assert row["extra_time_s"] == 0.0


def test_the_table_keeps_its_column_types_whatever_the_outcomes() -> None:
    # One trip outside the window (no state time) and nothing blocked.
    result = _classify([_trip("in", WALK, START + 100), _trip("out", WALK, 30000)], _states()).reset_index()

    assert str(result["state_time_s"].dtype) == "Int64"
    for column in ("trip_id", "dest_purpose", "origin_cell", "outcome", "blocking_edge_id", "no_route_reason"):
        assert result[column].dtype == "string", column
    assert result["depart_time_s"].dtype == "int64"
    assert result["extra_time_s"].dtype == "float64"

    empty = trip_outcomes.classify_trip_outcomes(
        pd.DataFrame(columns=list(_trip("x", WALK, START))), _waypoints(pd.DataFrame()), _edges(), _states(),
        analysis_crs="EPSG:32647", window=(START, END),
    )
    assert list(empty.columns) == trip_outcomes.COLUMNS
    assert empty.dtypes.astype(str).to_dict() == result.dtypes.astype(str).to_dict()


def test_each_flooded_graph_is_built_once_and_released_before_the_next(monkeypatch) -> None:
    built: list[weakref.ref] = []
    build_graph = trip_outcomes.mobility_module.build_routing_graph

    def tracking_build(edges, mode, **kwargs):
        graph = build_graph(edges, mode, **kwargs)
        if kwargs.get("speed_multipliers") is not None:
            gc.collect()
            assert all(ref() is None for ref in built), "an earlier flooded graph is still held"
            built.append(weakref.ref(graph))
        return graph

    monkeypatch.setattr(trip_outcomes.mobility_module, "build_routing_graph", tracking_build)
    states = _states({(START, WALK, "e23"): (0.0, True), (START + 300, CAR, "e23"): (0.0, True)})
    # Trips arrive interleaved across the two (state time, mode) pairs.
    trips = [_trip("w1", WALK, START + 100), _trip("c1", CAR, START + 400),
             _trip("w2", WALK, START + 150), _trip("c2", CAR, START + 350)]
    result = _classify(trips, states)

    assert len(built) == 2
    assert list(result.index) == ["w1", "c1", "w2", "c2"]
    assert set(result["outcome"]) == {"detour"}


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [("closed", None, "closed flag"), ("closed", "false", "closed flag"),
     ("speed_multiplier", float("nan"), "speed")],
)
def test_an_unknown_road_state_is_refused_not_read_as_open(column: str, value: object, message: str) -> None:
    states = _states().astype({"closed": object})
    states.loc[(states["edge_id"] == "e12") & (states["mode"] == WALK), column] = value

    with pytest.raises(ValueError, match=message):
        _classify([_trip("t1", WALK, START + 100)], states)


def test_a_mode_with_no_road_states_is_refused() -> None:
    states = _states({(START, WALK, "e23"): (0.0, True)})
    states = states[states["mode"] == CAR]

    with pytest.raises(ValueError, match="no road states"):
        _classify([_trip("t1", WALK, START + 100)], states)


def test_a_routed_trip_without_waypoints_is_refused() -> None:
    trips = [_trip("t1", WALK, START + 100), _trip("t2", WALK, START + 100)]
    waypoints = _waypoints(pd.DataFrame(trips))

    with pytest.raises(ValueError, match="waypoints"):
        _classify(trips, _states(), waypoints=waypoints[waypoints["trip_id"] == "t1"])


def test_each_mode_uses_its_own_latest_state_time() -> None:
    # Walking was last stated at START; driving also at START + 300.
    states = _states({(START, WALK, "e23"): (0.0, True)})
    states = states[~((states["mode"] == WALK) & (states["time_s"] == START + 300))]
    row = _classify([_trip("t1", WALK, START + 400)], states).loc["t1"]

    assert row["state_time_s"] == START
    assert row["outcome"] == "detour"


def test_a_waypoint_chain_without_its_last_point_is_refused() -> None:
    trips = [_trip("t1", WALK, START + 100)]
    waypoints = _waypoints(pd.DataFrame(trips))

    with pytest.raises(ValueError, match="waypoint chain"):
        _classify(trips, _states(), waypoints=waypoints[waypoints["seq"] < 2])
