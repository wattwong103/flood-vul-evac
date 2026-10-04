"""A viewport must retrieve every public feature without scanning Parquet."""
import sys
from pathlib import Path
import pandas as pd
import pytest
from shapely.geometry import LineString, box
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bkkflow.map_index import MapIndexUnavailable, build_map_index, query_map_index


def make_run(tmp_path):
    pd.DataFrame({"edge_id": ["west", "east", "east2"], "person_id": ["private"] * 3,
        "geometry_wkt": [LineString([(x, 13.5), (x + .001, 13.5)]).wkt for x in (100.3, 100.8, 100.81)]
        }).to_parquet(tmp_path / "network_edges.parquet")
    pd.DataFrame({"building_id": ["east-building"], "height_m": [None],
        "resident_names": ["private"], "geometry_wkt": [box(100.8, 13.5, 100.801, 13.501).wkt]
        }).to_parquet(tmp_path / "buildings.parquet")
    return build_map_index(tmp_path, "EPSG:4326")


def test_east_and_west_are_reachable_by_stable_pages(tmp_path, monkeypatch):
    result = make_run(tmp_path)
    assert result["rows"] == 4
    monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: pytest.fail("request scanned parquet"))
    west = query_map_index(tmp_path, "network", (100.2, 13.4, 100.4, 13.6), limit=1)
    assert west["features"][0]["properties"]["edge_id"] == "west"
    page = query_map_index(tmp_path, "network", (100.7, 13.4, 100.9, 13.6), limit=1)
    assert page["matched_rows"] == 2
    assert page == query_map_index(tmp_path, "network", (100.7, 13.4, 100.9, 13.6), limit=1)
    following = query_map_index(tmp_path, "network", (100.7, 13.4, 100.9, 13.6), limit=1, after=page["next_cursor"])
    assert following["next_cursor"] is None
    assert {f["properties"]["edge_id"] for f in page["features"] + following["features"]} == {"east", "east2"}
    assert "private" not in str(page)
    assert "person_id" not in str(page)
    buildings = query_map_index(tmp_path, "buildings", (100.7, 13.4, 100.9, 13.6))
    assert buildings["features"][0]["properties"]["height_m"] is None
    assert "resident_names" not in str(buildings)
    with pytest.raises(FileExistsError):
        build_map_index(tmp_path, "EPSG:4326")


def test_run_identity_bounds_and_layers_are_enforced(tmp_path):
    make_run(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / "map.sqlite").write_bytes((tmp_path / "map.sqlite").read_bytes())
    with pytest.raises(MapIndexUnavailable, match="run identity"):
        query_map_index(other, "network", (100, 13, 101, 14))
    for bbox in [(101, 13, 100, 14), (100, 13, float("nan"), 14)]:
        with pytest.raises(ValueError):
            query_map_index(tmp_path, "network", bbox)
    with pytest.raises(ValueError):
        query_map_index(tmp_path, "persons", (100, 13, 101, 14))


def test_projected_geometry_is_served_in_wgs84(tmp_path):
    import geopandas as gpd
    frame = gpd.GeoDataFrame(geometry=[LineString([(100.5, 13.7), (100.501, 13.7)])], crs="EPSG:4326").to_crs("EPSG:32647")
    pd.DataFrame({"edge_id": ["edge"], "geometry_wkt": frame.geometry.to_wkt()}).to_parquet(tmp_path / "network_edges.parquet")
    build_map_index(tmp_path, "EPSG:32647")
    page = query_map_index(tmp_path, "network", (100.4, 13.6, 100.6, 13.8))
    assert page["features"][0]["geometry"]["coordinates"][0] == pytest.approx([100.5, 13.7])


def test_failed_build_is_not_visible_and_can_be_retried(tmp_path, monkeypatch):
    from bkkflow import map_index
    original = map_index.shapely.from_wkt
    def interrupted(*args):
        assert not (tmp_path / "map.sqlite").exists()
        raise RuntimeError("interrupted")
    monkeypatch.setattr(map_index.shapely, "from_wkt", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        make_run(tmp_path)
    assert not (tmp_path / "map.sqlite").exists()
    monkeypatch.setattr(map_index.shapely, "from_wkt", original)
    # A file left by a hard process kill is private and does not prevent retry.
    (tmp_path / ".map-abandoned.sqlite").write_bytes(b"unfinished")
    assert build_map_index(tmp_path, "EPSG:4326")["rows"] == 4


def test_competing_writer_cannot_replace_final_index(tmp_path, monkeypatch):
    from bkkflow import map_index
    original = map_index.shapely.from_wkt
    def competitor(*args):
        (tmp_path / "map.sqlite").write_bytes(b"another completed writer")
        return original(*args)
    monkeypatch.setattr(map_index.shapely, "from_wkt", competitor)
    with pytest.raises(FileExistsError):
        make_run(tmp_path)
    assert (tmp_path / "map.sqlite").read_bytes() == b"another completed writer"
