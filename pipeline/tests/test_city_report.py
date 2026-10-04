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
