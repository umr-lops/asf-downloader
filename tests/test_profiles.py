"""Tests for the mission profile registry."""

from __future__ import annotations

import pytest

from asf_downloader.profiles import MISSIONS, UnknownMissionError, get_profile


def test_nisar_registered() -> None:
    """NISAR is the first (and only) registered mission."""
    assert "NISAR" in MISSIONS
    profile = get_profile("NISAR")
    assert profile.name == "NISAR"
    assert ("L1", "RSLC") in profile.supported_products
    assert ("L2", "GSLC") in profile.supported_products


def test_nisar_s3_prefixes_present() -> None:
    """The NISAR profile carries S3 prefixes for the future direct-S3 backend."""
    profile = get_profile("NISAR")
    assert "RSLC" in profile.s3_prefixes
    assert profile.s3_prefixes["RSLC"]["PROVISIONAL"] == "NISAR_L1_RSLC_PROVISIONAL_V1/"


def test_unknown_mission_lists_available() -> None:
    """Requesting an unregistered mission raises with the available missions listed."""
    with pytest.raises(UnknownMissionError) as excinfo:
        get_profile("SENTINEL-2")
    assert "NISAR" in str(excinfo.value)
    assert excinfo.value.available == ["NISAR"]
