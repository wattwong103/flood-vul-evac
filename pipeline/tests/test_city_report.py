"""Water-report regression checks."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def test_city_report_preserves_unobserved_water_share(tmp_path, monkeypatch):
    import city_report
    from bkkflow.util import write_json
    stats = {
        "geography": {"name": "Bangkok", "aoi_id": "bma", "area_km2": 1643, "analysis_crs": "EPSG:32647"},
        "network": dict.fromkeys(["source_ways", "edges", "nodes", "total_length_km", "walk_length_km", "vehicle_length_km"], 0),
        "population": {"residents_weighted": 100},
        "buildings": dict.fromkeys(["footprints", "height_coverage_share", "tagged_height", "derived_from_levels", "unknown_height"], 0),
        "water": {"features": 0, "waterway_length_km": 0},
        "flood": {"observed_extent": {"source_id": "JRC", "measures": "annual water classification", "years": [
            {"year": 2011, "water_km2": 0, "water_share": None, "excess_km2_vs_baseline": 0}]},
            "depth_status": "not_computed", "depth_reason": "no depth"},
        "destinations": {"candidates": 0, "verified": 0, "by_class": {}, "note": "unverified"},
        "validation": {"checks_total": 1, "checks_failed": 0, "passed": True, "manifest_schema_problems": 0},
        "warnings": [],
    }
    run = tmp_path / "saved"
    run.mkdir()
    write_json(run / "stats.json", stats)
    monkeypatch.setattr(city_report, "RUNS_DIR", tmp_path)
    report = city_report.write_city_summary("saved", run, run / "figure.png").read_text(encoding="utf-8")
    assert "unobserved" in report
    assert "flood does not appear" not in report and "Every year here is a lower bound" not in report


def test_rendered_water_panel_handles_no_observation_share(tmp_path, monkeypatch):
    import geopandas as gpd
    import matplotlib.pyplot as plt
    from shapely.geometry import box
    import city_report
    from bkkflow.sources import gsw
    from bkkflow.util import sha256_file, write_json
    from test_observed import raster_fixture
    fixture, bounds = raster_fixture(tmp_path, [0, 0])
    (tmp_path / "gsw").mkdir()
    path = tmp_path / "gsw" / gsw.tile_name_for(2020, bounds)
    path.write_bytes(fixture.read_bytes())
    write_json(path.with_suffix(".provenance.json"), {
        "resource_url": f"{gsw.BASE}/yearlyClassification2020/{path.name}",
        "retrieved_at": "2026-09-29T00:00:00Z", "content_sha256": sha256_file(path)})
    monkeypatch.setattr(gsw, "STAGED_DIR", tmp_path)
    aoi = gpd.GeoDataFrame(geometry=[box(*bounds)], crs="EPSG:4326").to_crs("EPSG:32647")
    figure, axis = plt.subplots()
    try:
        city_report._plot_observed_water(axis, aoi, {"flood": {"observed_extent": {"years": [
            {"year": 2020, "water_km2": 0, "water_share": None}]}}})
        figure.savefig(tmp_path / "unobserved.png")
        assert any("unobserved" in text.get_text() for text in axis.texts)
        assert (tmp_path / "unobserved.png").stat().st_size > 0
    finally:
        plt.close(figure)


def test_building_evidence_panel_includes_unknown_height():
    import city_report
    import matplotlib.pyplot as plt
    import geopandas as gpd
    from shapely.geometry import box
    from bkkflow.buildings import build_building_table
    source = gpd.GeoDataFrame({"osm_id": [1, 2, 3], "building": ["yes"] * 3,
        "height": [None, "10", None], "building:levels": [None, None, "3"]},
        geometry=[box(100.5 + i*.001, 13.7, 100.5005 + i*.001, 13.7005) for i in range(3)], crs="EPSG:4326")
    aoi = gpd.GeoDataFrame(geometry=[box(100.49, 13.69, 100.51, 13.71)], crs=source.crs)
    buildings = build_building_table(source, aoi_frame=aoi, analysis_crs="EPSG:32647", building_version="test")
    figure, axis = plt.subplots()
    try:
        city_report._plot_building_evidence(axis, buildings)
        assert sum(len(collection.get_offsets()) for collection in axis.collections) == 3
        assert "unknown" in axis.get_legend_handles_labels()[1]
    finally:
        plt.close(figure)
