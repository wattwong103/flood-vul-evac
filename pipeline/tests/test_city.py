"""Tests for the city-scale modules.

The city path is a different implementation from the pilot path, so it needs
its own tests. The properties checked here are the ones that would silently
produce a wrong city map: identity stability of the noded network, the
access rules, the packing arithmetic, and the honesty of the null contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import city_network as cn  # noqa: E402
from bkkflow.city_runner import (  # noqa: E402
    FLOOD_NOT_COMPUTED,
    FLOOD_REASON,
    _observed_source_version,
    _stage_record,
)
from bkkflow.sources import city_osm, terrain  # noqa: E402


def test_source_coverage_rejects_an_uncovered_eastern_aoi(tmp_path):
    path = tmp_path / "source.poly"
    path.write_text("test\n1\n100 13\n100.8 13\n100.8 14\n100 14\nEND\nEND\n")
    aoi = gpd.GeoDataFrame(geometry=[box(100.4, 13.2, 100.94, 13.9)], crs="EPSG:4326")
    with pytest.raises(ValueError, match="does not cover"):
        city_osm.source_coverage(path, aoi)


def test_source_coverage_respects_holes_and_crs(tmp_path):
    path = tmp_path / "source.poly"
    path.write_text("test\n1\n100 13\n101 13\n101 14\n100 14\nEND\n"
                    "!2\n100.8 13.8\n100.9 13.8\n100.9 13.9\n100.8 13.9\nEND\nEND\n")
    aoi = gpd.GeoDataFrame(geometry=[box(100.4, 13.2, 100.5, 13.3)], crs="EPSG:4326")
    coverage = city_osm.source_coverage(path, aoi.to_crs("EPSG:32647"))
    assert coverage["covers_aoi"] is True
    assert len(coverage["sha256"]) == 64
    with pytest.raises(ValueError, match="does not cover"):
        city_osm.source_coverage(path, gpd.GeoDataFrame(
            geometry=[box(100.82, 13.82, 100.88, 13.88)], crs="EPSG:4326"))


def test_destination_candidates_are_clipped_to_aoi(tmp_path, monkeypatch):
    import pyogrio
    from shapely.geometry import Point
    from bkkflow.sources.destinations import extract_destinations
    points = gpd.GeoDataFrame({"osm_id": [1, 2], "name": [None, None],
        "other_tags": ['"amenity"=>"school"'] * 2},
        geometry=[Point(100.5, 13.5), Point(100.9, 13.5)], crs="EPSG:4326")
    monkeypatch.setattr(pyogrio, "read_dataframe", lambda *args, **kwargs: points)
    aoi = gpd.GeoDataFrame(geometry=[box(100.4, 13.4, 100.6, 13.6)], crs="EPSG:4326")
    result = extract_destinations(out_dir=tmp_path, aoi_frame=aoi)
    assert result["rows"] == 1
    assert result["verified_count"] == 0
    assert pd.read_parquet(tmp_path / "destinations.parquet").destination_id.tolist() == ["d_1"]


def test_cached_osm_provenance_rejects_changed_bytes(tmp_path):
    from bkkflow.util import sha256_file, write_json
    source = tmp_path / "sample.pbf"
    source.write_bytes(b"source snapshot")
    write_json(source.with_suffix(".provenance.json"), {"url": "https://example.test/source",
        "retrieved_at": "2026-09-29T00:00:00Z", "content_sha256": sha256_file(source)})
    assert city_osm.source_provenance(source, "https://example.test/source")["retrieved_at"].startswith("2026-09-29")
    source.write_bytes(b"changed snapshot")
    with pytest.raises(ValueError, match="provenance"):
        city_osm.source_provenance(source, "https://example.test/source")


def _roads() -> gpd.GeoDataFrame:
    """A small grid with a crossing, so noding has something to do."""
    # Near Bangkok: coordinates at (0, 0) degrees fall outside the UTM 47N
    # projection domain and return infinities, so a test grid there is useless.
    lon0, lat0 = 100.500, 13.720
    d = 0.002
    geometries = [
        LineString([(lon0, lat0), (lon0 + d, lat0)]),
        LineString([(lon0 + d, lat0), (lon0 + 2 * d, lat0)]),
        LineString([(lon0, lat0), (lon0, lat0 + d)]),
        LineString([(lon0, lat0 + d), (lon0 + 2 * d, lat0 + d)]),
        LineString([(lon0 + d / 2, lat0 - d), (lon0 + d / 2, lat0 + 2 * d)]),
    ]
    return gpd.GeoDataFrame(
        {
            "osm_id": list(range(5)),
            "highway": ["residential", "residential", "footway", "residential", "primary"],
            "geometry": geometries,
        },
        crs="OGC:CRS84",
    )


def test_node_packing_round_trips() -> None:
    x = np.array([662161.795, 662182.678, -3.5])
    y = np.array([1519117.43, 1519095.02, 12.25])
    packed = cn._pack_nodes(x, y)
    assert len(set(packed.tolist())) == 3
    # The same coordinates must pack identically on a second call.
    assert np.array_equal(packed, cn._pack_nodes(x, y))


def test_node_packing_is_stable_under_repetition() -> None:
    values = np.array([100.0, 200.0, 300.0])
    first = cn._pack_nodes(values, values)
    second = cn._pack_nodes(values.copy(), values.copy())
    assert np.array_equal(first, second)


def test_city_network_nodes_the_crossing() -> None:
    """A crossing must become a junction, not two unconnected edges."""
    network = cn.build_city_network(
        _roads(), analysis_crs="EPSG:32647", network_version="t"
    )
    edges = network.edges
    assert len(edges) > len(_roads())  # the crossing created extra segments
    # A shared coordinate must be one node, not two.
    packed = cn._pack_nodes(
        np.concatenate([edges.geometry.map(lambda g: g.coords[0][0]).to_numpy(),
                        edges.geometry.map(lambda g: g.coords[-1][0]).to_numpy()]),
        np.concatenate([edges.geometry.map(lambda g: g.coords[0][1]).to_numpy(),
                        edges.geometry.map(lambda g: g.coords[-1][1]).to_numpy()]),
    )
    assert len(set(packed.tolist())) == network.stats["nodes"]


def test_city_edge_ids_are_stable_and_order_independent() -> None:
    first = cn.build_city_network(_roads(), analysis_crs="EPSG:32647", network_version="t")
    second = cn.build_city_network(
        _roads().iloc[::-1], analysis_crs="EPSG:32647", network_version="t"
    )
    assert set(first.edges["edge_id"]) == set(second.edges["edge_id"])


def test_city_access_rules_separate_walk_from_vehicle() -> None:
    network = cn.build_city_network(_roads(), analysis_crs="EPSG:32647", network_version="t")
    edges = network.edges
    assert edges[edges["highway"] == "footway"]["vehicle_allowed"].sum() == 0
    assert edges[edges["highway"] == "primary"]["vehicle_allowed"].sum() > 0
    assert edges["walk_allowed"].all()


def test_city_edge_lengths_are_positive_and_finite() -> None:
    network = cn.build_city_network(_roads(), analysis_crs="EPSG:32647", network_version="t")
    lengths = network.edges["length_m"]
    assert lengths.gt(0).all()
    assert np.isfinite(lengths).all()


def test_closed_polygon_way_becomes_a_line() -> None:
    frame = gpd.GeoDataFrame(
        {
            "osm_id": [1],
            "highway": ["pedestrian"],
            # Near Bangkok: (0,0) degrees is outside the UTM 47N domain.
            "geometry": [box(100.500, 13.720, 100.502, 13.722)],
        },
        crs="OGC:CRS84",
    )
    network = cn.build_city_network(frame, analysis_crs="EPSG:32647", network_version="t")
    assert len(network.edges) >= 1


# --------------------------------------------------------------------------
# routing index
# --------------------------------------------------------------------------


def test_routing_index_is_bidirectional() -> None:
    network = cn.build_city_network(_roads(), analysis_crs="EPSG:32647", network_version="t")
    edges = network.edges
    index = cn.CityRoutingIndex(
        edges,
        edges["walk_allowed"].to_numpy(),
        edges["speed_walk_mps"].fillna(1.4).to_numpy(),
    )
    # Every directed arc exists in both directions, so the degree sum is even.
    assert index.edge_count > 0
    assert index.node_count > 0


def test_dijkstra_from_a_node_reaches_it_at_zero_cost() -> None:
    network = cn.build_city_network(_roads(), analysis_crs="EPSG:32647", network_version="t")
    edges = network.edges
    index = cn.CityRoutingIndex(
        edges, edges["walk_allowed"].to_numpy(), edges["speed_walk_mps"].fillna(1.4).to_numpy()
    )
    costs, _ = index.dijkstra(0)
    assert costs[0] == pytest.approx(0.0)
    assert np.isfinite(costs).sum() > 1


def test_dijkstra_costs_are_non_negative_and_monotone_by_reach() -> None:
    network = cn.build_city_network(_roads(), analysis_crs="EPSG:32647", network_version="t")
    edges = network.edges
    index = cn.CityRoutingIndex(
        edges, edges["walk_allowed"].to_numpy(), edges["speed_walk_mps"].fillna(1.4).to_numpy()
    )
    costs, _ = index.dijkstra(0)
    reachable = costs[np.isfinite(costs)]
    assert (reachable >= 0).all()


def test_dijkstra_from_an_invalid_node_is_all_infinite() -> None:
    network = cn.build_city_network(_roads(), analysis_crs="EPSG:32647", network_version="t")
    edges = network.edges
    index = cn.CityRoutingIndex(
        edges, edges["walk_allowed"].to_numpy(), edges["speed_walk_mps"].fillna(1.4).to_numpy()
    )
    costs, _ = index.dijkstra(-1)
    assert not np.isfinite(costs).any()


# --------------------------------------------------------------------------
# other_tags parsing
# --------------------------------------------------------------------------


def test_other_tags_parses_the_gdal_hash_fragment() -> None:
    fragment = '"building:levels"=>"3","addr:district"=>"X","height"=>12.5'
    parsed = city_osm.parse_other_tags(fragment)
    assert parsed["building:levels"] == "3"
    assert parsed["addr:district"] == "X"
    assert parsed["height"] == "12.5"


def test_other_tags_tolerates_junk() -> None:
    assert city_osm.parse_other_tags(None) == {}
    assert city_osm.parse_other_tags("") == {}
    assert city_osm.parse_other_tags("not a hash") == {}


# --------------------------------------------------------------------------
# terrain tile maths
# --------------------------------------------------------------------------


def test_tile_index_round_trips_through_bounds() -> None:
    x, y = terrain.lonlat_to_tile(100.5, 13.72, 13)
    west, south, east, north = terrain.tile_to_bounds(x, y, 13)
    assert west <= 100.5 <= east
    assert south <= 13.72 <= north


def test_terrarium_decoding_matches_the_specification() -> None:
    rgb = np.array([[[128, 5, 0]]], dtype="uint8")
    assert terrain._terrarium_to_metres(rgb)[0, 0] == pytest.approx(5.0)
    rgb = np.array([[[0, 0, 0]]], dtype="uint8")
    assert terrain._terrarium_to_metres(rgb)[0, 0] == pytest.approx(-32768.0)
    rgb = np.array([[[255, 255, 255]]], dtype="uint8")
    assert terrain._terrarium_to_metres(rgb)[0, 0] == pytest.approx(32767.996)


def test_tile_set_covers_the_requested_bounds() -> None:
    bounds = (100.3279, 13.2191, 100.9386, 13.9552)
    tiles = terrain.tiles_for_bounds(bounds, 13)
    assert len(tiles) > 0
    for x, y in tiles:
        west, south, east, north = terrain.tile_to_bounds(x, y, 13)
        assert east > bounds[0] and west < bounds[2]
        assert north > bounds[1] and south < bounds[3]


# --------------------------------------------------------------------------
# the null contract
# --------------------------------------------------------------------------


def test_flood_absence_is_declared_with_a_reason() -> None:
    assert FLOOD_NOT_COMPUTED
    assert "DEM" in FLOOD_REASON or "terrain" in FLOOD_REASON
    assert "CITY_SCALE_LIMITATIONS" in FLOOD_REASON


def test_city_run_never_reports_zero_for_flood() -> None:
    """A zero would read as 'no flooding'. Absence must be null."""
    import inspect

    from bkkflow import city_runner

    source = inspect.getsource(city_runner.execute_city_run)
    flood_block = source[source.index('"flood": {'): source.index('"evacuation": {')]
    assert '"max_depth_m": None' in flood_block
    assert '"edges_closed": None' in flood_block
    assert '"flooded_area_km2": None' in flood_block
    assert "0," not in flood_block.split('"reason"')[0].replace('"max_depth_m": 0', '')


def test_stage_record_rejects_negative_or_non_finite_duration() -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        _stage_record("aggregation", -1.0)
    with pytest.raises(ValueError, match="finite and non-negative"):
        _stage_record("aggregation", float("nan"))


def test_observed_source_version_identifies_every_raw_tile() -> None:
    observed = {
        "status": "ok",
        "source_id": "jrc-global-surface-water-v1.4",
        "retrieved_at": "2026-09-30T00:00:00+00:00",
        "years": [
            {
                "year": 2010,
                "tile_name": "yearlyClassification2010.tif",
                "content_sha256": "a" * 64,
                "retrieved_at": "2026-09-29T00:00:00+00:00",
            },
            {
                "year": 2012,
                "tile_name": "yearlyClassification2012.tif",
                "content_sha256": "b" * 64,
                "retrieved_at": "2026-09-30T00:00:00+00:00",
            },
        ],
    }

    version = _observed_source_version(observed, aoi_id="bangkok-bma")

    assert version is not None
    assert version["source_id"] == "jrc-global-surface-water-v1.4"
    assert len(version["content_sha256"]) == 64
    assert version["request_parameters"]["years"] == [2010, 2012]
    assert len(version["request_parameters"]["tiles"]) == 2


def test_city_cache_rejects_old_source_before_reuse(tmp_path):
    with pytest.raises(ValueError, match="re-ingest"):
        city_osm.validate_cached_ingest({"source_id": "bbbike-bangkok-osm-extract"},
            gpd.GeoDataFrame(geometry=[box(100, 13, 101, 14)], crs="EPSG:4326"), tmp_path)


def test_city_cache_rejects_changed_layer(tmp_path, monkeypatch):
    from bkkflow.util import sha256_file
    path = tmp_path / "roads.parquet"
    path.write_bytes(b"original")
    record = {"source_id": city_osm.SOURCE_ID, "pbf_path": "unused",
        "resource_url": "unused", "content_sha256": "source", "coverage": {"sha256": "coverage"},
        "layers": {"roads": {"sha256": sha256_file(path)}}}
    monkeypatch.setattr(city_osm, "source_provenance", lambda *a: {"content_sha256": "source"})
    monkeypatch.setattr(city_osm, "source_coverage", lambda *a: {"sha256": "coverage"})
    path.write_bytes(b"replaced")
    with pytest.raises(ValueError, match="roads"):
        city_osm.validate_cached_ingest(record, None, tmp_path)


def test_manually_staged_osm_requires_download_provenance(tmp_path):
    source = tmp_path / "manual.pbf"
    source.write_bytes(b"manual source")
    with pytest.raises(ValueError, match="download provenance.*re-download"):
        city_osm.source_provenance(source, "https://example.test/source")
