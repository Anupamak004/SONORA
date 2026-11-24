"""Unit tests for configurable instrument preservation profiles."""

from __future__ import annotations

from app.models.profiles import get_profile, list_profiles


def test_profiles_cover_required_instrument_categories() -> None:
    profiles = list_profiles()
    ids = {profile.id for profile in profiles}

    expected = {
        "general",
        "acoustic_guitar",
        "piano",
        "bowed_strings",
        "wind_brass",
        "percussion",
        "bass",
    }
    assert expected.issubset(ids)


def test_every_profile_protects_fundamentals_and_keeps_hpf_below_fundamental() -> None:
    for profile in list_profiles():
        assert profile.protect_fundamentals is True
        assert profile.protect_harmonics is True
        assert profile.pitch_safe_hum_guard is True
        assert profile.min_hpf_hz <= profile.default_hpf_hz <= profile.max_hpf_hz
        assert profile.default_hpf_hz < profile.fundamental_min_hz


def test_get_profile_lookup() -> None:
    piano = get_profile("piano")
    assert piano is not None
    assert piano.fundamental_min_hz == 27.5
    assert get_profile("nonexistent_instrument") is None
