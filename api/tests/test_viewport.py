"""Viewport pages are bounded, public, and tied to the requested run."""
import json
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from api.app import create_app
from pipeline.bkkflow.map_index import build_map_index


@pytest.fixture
def viewport(tmp_path, monkeypatch):
    run = tmp_path / "selected"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"run_id": "selected", "outputs": []}))
    pd.DataFrame({"edge_id": ["east", "west"], "geometry_wkt": [
        "LINESTRING (100.8 13.5, 100.81 13.5)", "LINESTRING (100.3 13.5, 100.31 13.5)"]
        }).to_parquet(run / "network_edges.parquet")
    build_map_index(run, "EPSG:4326")
    monkeypatch.setenv("BKKFLOW_RUNS_DIR", str(tmp_path))
    return TestClient(create_app()), run


def test_viewport_api_and_unavailable_index(viewport):
    client, run = viewport
    response = client.get("/v1/runs/selected/map/network?bbox=100.7,13,101,14&limit=1")
    assert response.status_code == 200
    assert response.json()["features"][0]["properties"]["edge_id"] == "east"
    assert response.json()["run_id"] == "selected"
    (run / "map.sqlite").write_bytes(b"corrupt")
    unavailable = client.get("/v1/runs/selected/map/network?bbox=100,13,101,14")
    assert unavailable.status_code == 200
    assert unavailable.json()["available"] is False
    (run / "map.sqlite").unlink()
    assert client.get("/v1/runs/selected/map/buildings?bbox=100,13,101,14").json()["available"] is False


@pytest.mark.parametrize("query", ["bbox=bad", "bbox=100,13,nan,14", "bbox=101,13,100,14", "bbox=100,13,101,14&limit=5001", "bbox=100,13,101,14&after=-1"])
def test_invalid_viewport_requests_are_rejected(viewport, query):
    client, _ = viewport
    assert client.get("/v1/runs/selected/map/network?" + query).status_code == 422
    assert client.get("/v1/runs/selected/map/persons?bbox=100,13,101,14").status_code == 422


def test_network_summary_does_not_read_large_parquet(viewport, monkeypatch):
    client, run = viewport
    (run / "stats.json").write_text(json.dumps({"network": {"edges": 2}}))
    monkeypatch.setattr(pd, "read_parquet", lambda *a, **kw: pytest.fail("summary scanned a layer"))
    result = client.get("/v1/runs/selected/network?summary_only=true").json()
    assert result["summary"]["edges"] == result["matched_rows"] == 2
    assert result["features"] == []
