"""Named pilot configuration must be explicit, isolated and self-consistent."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow.pilot_config import load_pilot_bundle


PILOT_IDS = (
    "khlong-san-district",
    "sai-mai-district",
    "din-daeng-district",
    "min-buri-district",
)


def test_named_pilots_have_isolated_inputs_and_versions():
    config_dir = Path(__file__).resolve().parents[2] / "config"
    curated = Path("curated-test-root")
    bundles = [load_pilot_bundle(pilot_id, config_dir=config_dir, curated_dir=curated)
               for pilot_id in PILOT_IDS]

    assert [bundle.aoi_id for bundle in bundles] == list(PILOT_IDS)
    assert len({bundle.input_root for bundle in bundles}) == len(PILOT_IDS)
    for bundle in bundles:
        assert bundle.input_root == curated / "pilots" / bundle.aoi_id
        assert bundle.pilot["input_scope"] == bundle.aoi_id
        assert bundle.aoi_id in bundle.population["population_version"]
        assert bundle.population["population_version"] == (
            f"bkk-pop-v0.3-{bundle.aoi_id}-2020-agesex"
        )
        assert bundle.aoi_id in bundle.versions["network"]
        assert bundle.aoi_id in bundle.versions["buildings"]
        assert set(bundle.pilot["source_sha256"]) == {"osm", "population", "geometry"}
        assert all(len(value) == 64 for value in bundle.pilot["source_sha256"].values())
        assert "2011" not in bundle.scenario["flood"]["scenario_id"]

    common = [
        (
            bundle.population["seed"],
            bundle.population["mobility_sample"]["max_agents"],
            bundle.scenario["flood"]["cell_size_m"],
            bundle.scenario["evacuation"]["compliance"],
        )
        for bundle in bundles
    ]
    assert len(set(common)) == 1


def test_omitted_pilot_preserves_legacy_configuration():
    config_dir = Path(__file__).resolve().parents[2] / "config"
    curated = Path("legacy-curated-root")
    bundle = load_pilot_bundle(None, config_dir=config_dir, curated_dir=curated)

    assert not bundle.named
    assert bundle.aoi_id == "khlong-san-district"
    assert bundle.input_root == curated
    # Read the version from the shipped config rather than pinning a literal:
    # the value changes whenever the population content changes.
    import json
    expected = json.loads((config_dir / "population.json").read_text(encoding="utf-8"))
    assert bundle.population["population_version"] == expected["population_version"]
    assert bundle.scenario["flood"]["scenario_id"] == "khlong-san-moderate-2011-analogue"


def test_unknown_named_pilot_fails_without_fallback(tmp_path):
    with pytest.raises(ValueError, match="Unknown pilot"):
        load_pilot_bundle("not-a-pilot", config_dir=tmp_path, curated_dir=tmp_path)


def test_named_pilot_id_rejects_direct_path_traversal(tmp_path):
    config_dir = tmp_path / "config"
    (config_dir / "pilots").mkdir(parents=True)
    (config_dir / "escape.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown pilot"):
        load_pilot_bundle(
            "../escape", config_dir=config_dir, curated_dir=tmp_path / "curated"
        )


def test_mismatched_named_pilot_fails(tmp_path):
    (tmp_path / "pilots").mkdir()
    (tmp_path / "population.json").write_text("{}", encoding="utf-8")
    (tmp_path / "scenario.json").write_text("{}", encoding="utf-8")
    payload = {
        "input_scope": "different-district",
        "analysis_crs": "EPSG:32647",
        "aoi": {"aoi_id": "different-district", "osm_relation_id": 1},
        "versions": {"population": "p", "network": "n", "buildings": "b"},
        "sources": {"osm": "o", "population": "p"},
        "flood_scenario_id": "moderate-distance-to-water",
    }
    (tmp_path / "pilots" / "sai-mai-district.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="does not match"):
        load_pilot_bundle("sai-mai-district", config_dir=tmp_path, curated_dir=tmp_path)
