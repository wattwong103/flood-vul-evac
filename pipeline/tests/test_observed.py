"""Tests for the observed-extent and destination-candidate modules.

The two properties that matter here are semantic. The JRC yearly
classification uses 0 for *dry land*, not no-data, and an inverted code table
silently turns a water fraction into its complement. And an OSM tag must never
emerge from this code path as a verified refuge.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow.sources import destinations, gsw  # noqa: E402


# --------------------------------------------------------------------------
# JRC classification codes
# --------------------------------------------------------------------------


def test_zero_means_land_not_nodata() -> None:
    """The single most damaging possible misreading of this product."""
    assert gsw.CODE_LAND == 0
    assert gsw.CODE_WATER == 1
    assert 0 not in gsw.CODE_NODATA
    assert gsw.CODE_CODES[0] == "land"


def test_only_the_two_nodata_codes_are_masked() -> None:
    assert gsw.CODE_NODATA == (2, 3)


# --------------------------------------------------------------------------
# tile addressing
# --------------------------------------------------------------------------


def test_tile_name_for_bangkok_is_the_known_good_tile() -> None:
    # Verified by downloading it: the tile covers lon 100-110, lat 10-20.
    name = gsw.tile_name_for(2011, (100.3279, 13.2191, 100.9386, 13.9552))
    assert name == "yearlyClassification2011-0000240000-0001120000.tif"


def test_tile_name_uses_the_top_edge_not_the_bottom() -> None:
    """A tile 10 degrees further south than the AOI would be a real file for
    the wrong place, so the regression has to be pinned."""
    bangkok = gsw.tile_name_for(2011, (100.33, 13.22, 100.94, 13.96))
    # Latitude band 10-20 must not resolve to the 0-10 band.
    assert "0000240000" in bangkok
    assert "0000280000" not in bangkok


def test_tile_name_reference_tiles() -> None:
    # Measured directly from the downloaded rasters.
    assert gsw.tile_name_for(2011, (-180, 70, -170, 80)) == (
        "yearlyClassification2011-0000000000-0000000000.tif"
    )
    assert gsw.tile_name_for(2011, (-180, 60, -170, 70)) == (
        "yearlyClassification2011-0000040000-0000000000.tif"
    )


def test_tile_name_handles_a_bound_exactly_on_the_band_edge() -> None:
    # Northern edge at 80N belongs to the 70-80 band, not a hypothetical 80-90.
    assert gsw.tile_name_for(2011, (-180, 70, -170, 80)).startswith(
        "yearlyClassification2011-0000000000"
    )


def test_tile_name_refuses_to_straddle_a_tile_edge() -> None:
    with pytest.raises(ValueError):
        gsw.tile_name_for(2011, (95.0, 5.0, 125.0, 25.0))


# --------------------------------------------------------------------------
# summary statistics
# --------------------------------------------------------------------------


class _FakeDataset:
    """Minimal rasterio-like dataset for the area arithmetic."""

    def __init__(self, array):
        self._array = array

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_water_share_uses_classified_area_not_total_pixels() -> None:
    """Land pixels belong in the denominator; masking them inverts the ratio."""
    # 100 land, 10 water, 5 masked.
    array = np.array([0] * 100 + [1] * 10 + [2] * 5, dtype="uint8")
    land = int((array == gsw.CODE_LAND).sum())
    water = int((array == gsw.CODE_WATER).sum())
    classified = int((~np.isin(array, gsw.CODE_NODATA)).sum())
    assert (land, water, classified) == (100, 10, 110)
    assert water / classified == pytest.approx(0.0909, abs=1e-4)
    # The wrong denominator (dropping land) would give 10/15.
    assert water / (water + 5) == pytest.approx(0.6667, abs=1e-4)


def test_observed_payload_declares_it_is_not_depth() -> None:
    assert "NOT depth" in gsw.__doc__ or "not depth" in gsw.__doc__.lower()


# --------------------------------------------------------------------------
# destinations
# --------------------------------------------------------------------------


def test_every_destination_class_maps_to_an_amenity() -> None:
    for amenity, destination_class in destinations.DESTINATION_AMENITIES.items():
        assert isinstance(amenity, str)
        assert destination_class


def test_shelter_is_a_candidate_class_never_a_refuge_class() -> None:
    assert destinations.DESTINATION_AMENITIES["shelter"] == "shelter_candidate"
    assert "shelter_candidate" in destinations.NEVER_REFUGE_CLASSES


def test_destination_module_states_tags_are_not_guarantees() -> None:
    text = destinations.__doc__ or ""
    assert "lead, not a refuge" in text
    assert "verified=False" in text
