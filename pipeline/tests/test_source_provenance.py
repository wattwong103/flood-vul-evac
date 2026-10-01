"""Offline recovery requires original, content-matching retrieval evidence."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bkkflow import provenance
from bkkflow.util import sha256_file, stable_hash, write_json


def test_recover_matching_cache_record_without_downloading(tmp_path):
    source = tmp_path / "source.tif"
    source.write_bytes(b"original source")
    url = "https://example.test/source.tif"
    key = stable_hash({"url": url, "accept": False})
    metadata = {"url": url, "retrieved_at": "2026-09-29T17:12:01+00:00",
                "content_sha256": sha256_file(source)}
    write_json(tmp_path / key[:2] / f"{key}.json", metadata)
    assert provenance.verify_source(source, url, cache_dir=tmp_path)["retrieved_at"] == metadata["retrieved_at"]
    assert source.with_suffix(".provenance.json").is_file()
    source.write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="provenance"):
        provenance.verify_source(source, url, cache_dir=tmp_path)


def test_missing_provenance_never_invents_a_retrieval_date(tmp_path):
    source = tmp_path / "unknown.tif"
    source.write_bytes(b"unknown")
    with pytest.raises(ValueError, match="provenance"):
        provenance.verify_source(source, "https://example.test/unknown.tif", cache_dir=tmp_path)
    assert not source.with_suffix(".provenance.json").exists()


def test_standalone_cells_and_cached_masks_reject_changed_source(tmp_path, monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box
    import build_observed_cells
    from bkkflow import aoi, observed_evac
    from bkkflow.sources import gsw
    from test_observed import raster_fixture
    fixture, bounds = raster_fixture(tmp_path, [0, 1, 2, 3])
    directory = tmp_path / "gsw"
    directory.mkdir()
    tile = directory / gsw.tile_name_for(2020, bounds)
    tile.write_bytes(fixture.read_bytes())
    write_json(tile.with_suffix(".provenance.json"), {
        "resource_url": f"{gsw.BASE}/yearlyClassification2020/{tile.name}",
        "retrieved_at": "2026-09-29T00:00:00Z", "content_sha256": sha256_file(tile)})
    monkeypatch.setattr(gsw, "STAGED_DIR", tmp_path)
    monkeypatch.setattr(aoi, "load_aoi", lambda *a: gpd.GeoDataFrame(geometry=[box(*bounds)], crs="EPSG:4326"))
    monkeypatch.setattr(build_observed_cells, "YEARS", (2020,))
    assert observed_evac.water_mask(2020)[0].sum() == 2
    tile.write_bytes(b"changed")
    with pytest.raises(ValueError, match="provenance"):
        observed_evac.water_mask(2020)
    with pytest.raises(ValueError, match="provenance"):
        build_observed_cells.build(out_dir=tmp_path / "output")
