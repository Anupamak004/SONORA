"""Unit tests for Stage 3 conservative noise estimation, spectral indicators, PSD, and spectrogram."""

from __future__ import annotations

import math

import numpy as np
from scipy import signal

from app.analysis.analyzer import analyze_audio
from app.models.schemas import AnalysisRequest

_RNG = np.random.default_rng(42)


def _sine(
    duration_s: float,
    sr: int,
    freq_hz: float,
    amp: float = 0.25,
    channels: int = 1,
) -> np.ndarray:
    t = np.arange(int(round(duration_s * sr)), dtype=np.float64) / sr
    wave = (amp * np.sin(2.0 * math.pi * freq_hz * t)).astype(np.float32)
    return np.column_stack([wave] * channels)


def _sustained_bowed_note(
    duration_s: float = 2.5,
    sr: int = 48000,
    f0: float = 220.0,
    amp: float = 0.22,
    channels: int = 2,
) -> np.ndarray:
    """Synthesize a continuous bowed string tone with vibrato and 8 harmonics (no silent pauses)."""
    n = int(round(duration_s * sr))
    t = np.arange(n, dtype=np.float64) / sr
    # Gentle 5.5 Hz vibrato (+/- 1.2% pitch depth)
    vib_phase = 2.0 * math.pi * f0 * t + (0.012 * f0 / 5.5) * np.sin(2.0 * math.pi * 5.5 * t)
    mono = np.zeros(n, dtype=np.float64)
    for harmonic in range(1, 9):
        mono += (amp / (harmonic ** 1.15)) * np.sin(harmonic * vib_phase)
    mono_f32 = mono.astype(np.float32)
    return np.column_stack([mono_f32] * channels)


def _indicator_by_id(resp, indicator_id: str):
    return next(item for item in resp.detected_indicators if item.id == indicator_id)


def test_silence_and_near_silence_produce_no_false_detections() -> None:
    sr = 48000
    silent = np.zeros((sr, 2), dtype=np.float32)
    resp = analyze_audio(silent, sr, "test-silent")

    assert resp.signal_state == "silence_or_near_silence"
    assert resp.noise_floor.broadband_noise_floor_dbfs is None
    assert resp.noise_floor.estimated_snr_db is None
    assert all(not ind.detected for ind in resp.detected_indicators)
    assert resp.spectrogram.freq_bins <= 96
    assert resp.spectrogram.time_bins <= 220

    # Near-silence (-95 dBFS noise)
    near_silent = (_RNG.standard_normal((sr, 1)) * 1.5e-5).astype(np.float32)
    near_resp = analyze_audio(near_silent, sr, "test-near-silent")
    assert near_resp.signal_state == "silence_or_near_silence"
    assert all(not ind.detected for ind in near_resp.detected_indicators)


def test_clean_sine_wave_triggers_no_noise_categories() -> None:
    sr = 48000
    clean_a4 = _sine(duration_s=2.0, sr=sr, freq_hz=440.0, amp=0.3, channels=2)
    resp = analyze_audio(clean_a4, sr, "test-clean-sine")

    assert resp.signal_state == "normal"
    assert all(not ind.detected for ind in resp.detected_indicators)
    assert resp.noise_floor.broadband_noise_floor_dbfs is not None
    assert resp.noise_floor.broadband_noise_floor_dbfs < -80.0


def test_sustained_musical_tones_with_vibrato_not_classified_as_noise() -> None:
    sr = 48000
    violin = _sustained_bowed_note(duration_s=2.5, sr=sr, f0=220.0, amp=0.22, channels=2)
    resp = analyze_audio(violin, sr, "test-sustained-violin")

    assert resp.signal_state == "normal"
    for ind_id in ("electrical_hum", "low_freq_rumble", "broadband_hiss", "broadband_environmental"):
        assert _indicator_by_id(resp, ind_id).detected is False, (
            f"Sustained musical tone was falsely flagged as {ind_id}"
        )
    # Clean low tonal bass note (E1 = 41.2 Hz + harmonics) must not be flagged as wind/rumble
    bass_note = (
        _sine(2.0, sr, 41.2, 0.25, channels=1)
        + _sine(2.0, sr, 82.4, 0.14, channels=1)
        + _sine(2.0, sr, 123.6, 0.08, channels=1)
    )
    bass_resp = analyze_audio(bass_note, sr, "test-clean-bass")
    assert _indicator_by_id(bass_resp, "low_freq_rumble").detected is False
    assert _indicator_by_id(bass_resp, "electrical_hum").detected is False


def test_detects_possible_50hz_and_60hz_hum_distinctly() -> None:
    sr = 48000
    n = sr * 2
    t = np.arange(n, dtype=np.float64) / sr
    # Gentle intermittent note so audio represents a musical recording with hum
    envelope = 0.5 * (1.0 + np.sin(2.0 * math.pi * 1.2 * t))
    music = (0.18 * envelope * np.sin(2.0 * math.pi * 330.0 * t)).astype(np.float32)

    hum_50 = (
        0.025 * np.sin(2.0 * math.pi * 50.0 * t)
        + 0.015 * np.sin(2.0 * math.pi * 100.0 * t)
        + 0.010 * np.sin(2.0 * math.pi * 150.0 * t)
    ).astype(np.float32)
    resp_50 = analyze_audio(np.column_stack([music + hum_50]), sr, "test-hum-50")
    ind_50 = _indicator_by_id(resp_50, "electrical_hum")
    assert ind_50.detected is True
    assert "50 Hz" in ind_50.label
    assert "Possible" in ind_50.label
    assert ind_50.metrics["base_freq_hz"] == 50.0
    assert ind_50.confidence in ("moderate", "high")

    hum_60 = (
        0.025 * np.sin(2.0 * math.pi * 60.0 * t)
        + 0.015 * np.sin(2.0 * math.pi * 120.0 * t)
        + 0.010 * np.sin(2.0 * math.pi * 180.0 * t)
    ).astype(np.float32)
    resp_60 = analyze_audio(np.column_stack([music + hum_60]), sr, "test-hum-60")
    ind_60 = _indicator_by_id(resp_60, "electrical_hum")
    assert ind_60.detected is True
    assert "60 Hz" in ind_60.label
    assert ind_60.metrics["base_freq_hz"] == 60.0
    assert ind_60.confidence in ("moderate", "high")


def test_detects_possible_broadband_hiss() -> None:
    sr = 48000
    music = _sine(2.0, sr, 440.0, amp=0.25, channels=2)
    # High-passed white noise (> 4.5 kHz) simulating preamp/tape hiss
    white = _RNG.standard_normal(music.shape).astype(np.float64)
    sos_hp = signal.butter(4, 4500.0, btype="highpass", fs=sr, output="sos")
    hiss = signal.sosfilt(sos_hp, white, axis=0).astype(np.float32)
    hiss = hiss / np.std(hiss) * 0.015  # ~ -36 dBFS RMS hiss

    resp = analyze_audio(music + hiss, sr, "test-hiss")
    ind = _indicator_by_id(resp, "broadband_hiss")
    assert ind.detected is True
    assert ind.confidence in ("moderate", "high")
    assert "Possible" in ind.label


def test_detects_possible_low_frequency_rumble() -> None:
    sr = 48000
    music = _sine(2.5, sr, 523.25, amp=0.2, channels=1)
    white = _RNG.standard_normal(music.shape).astype(np.float64)
    sos_bp = signal.butter(4, [25.0, 95.0], btype="bandpass", fs=sr, output="sos")
    rumble = signal.sosfilt(sos_bp, white, axis=0).astype(np.float32)
    rumble = rumble / np.std(rumble) * 0.035  # ~ -29 dBFS broadband rumble

    resp = analyze_audio(music + rumble, sr, "test-rumble")
    ind = _indicator_by_id(resp, "low_freq_rumble")
    assert ind.detected is True
    assert ind.confidence in ("moderate", "high")


def test_short_clips_unusual_sample_rates_and_bounded_response_sizes() -> None:
    # Very short 8 kHz mono clip (0.12 s)
    short_8k = _sine(0.12, 8000, 440.0, amp=0.2, channels=1)
    resp_8k = analyze_audio(short_8k, 8000, "test-8k-short")
    assert resp_8k.sample_rate == 8000
    assert resp_8k.channels == 1
    assert resp_8k.signal_state == "very_short"
    # Bands above 4 kHz Nyquist must be omitted cleanly
    assert all(b.high_hz <= 4000.0 for b in resp_8k.frequency_bands)

    # Longer 96 kHz stereo clip with explicit strict bounds
    long_96k = _sine(4.0, 96000, 440.0, amp=0.2, channels=2)
    req = AnalysisRequest(
        freq_scale="linear",
        db_min=-90.0,
        db_max=0.0,
        max_time_bins=120,
        max_freq_bins=64,
    )
    resp_96k = analyze_audio(long_96k, 96000, "test-96k-bounded", params=req)
    assert resp_96k.sample_rate == 96000
    assert resp_96k.channels == 2
    assert resp_96k.spectrogram.freq_scale == "linear"
    assert resp_96k.spectrogram.time_bins <= 120
    assert resp_96k.spectrogram.freq_bins <= 64
    assert len(resp_96k.spectrogram.magnitudes_u8) == resp_96k.spectrogram.freq_bins
    assert len(resp_96k.spectrogram.magnitudes_u8[0]) == resp_96k.spectrogram.time_bins
    flat_vals = [v for row in resp_96k.spectrogram.magnitudes_u8 for v in row]
    assert min(flat_vals) >= 0 and max(flat_vals) <= 255
    assert len(resp_96k.psd.frequencies_hz) <= 160
