"""Unit & audio-quality tests for Stage 4 Precision Musical DSP pipeline."""

from __future__ import annotations

import math

import numpy as np
from scipy import signal

from app.dsp.pipeline import process_audio_pipeline
from app.models.schemas import ProcessRequest
from benchmarks.metrics import (
    compute_si_sdr_db,
    compute_snr_db,
    compute_transient_preservation,
)
from benchmarks.scenarios import build_all_scenarios


def _scenario_by_id(scenario_id: str):
    return next(s for s in build_all_scenarios(seed=2026) if s.id == scenario_id)


def test_clean_audio_and_near_clean_auto_bypass_or_remain_minimal() -> None:
    for sc_id in ("clean_sustained_tone", "vibrato_harmonics_clean", "near_clean_recording"):
        sc = _scenario_by_id(sc_id)
        out = process_audio_pipeline(sc.noisy_input, sc.sample_rate, sc.request)

        assert out.processed.shape == sc.noisy_input.shape
        assert out.processing_mode in ("bypassed_clean_or_silent", "minimal")
        si_sdr = compute_si_sdr_db(sc.clean, out.processed)
        assert si_sdr is not None and si_sdr > 35.0


def test_hum_reduction_improves_snr_and_preserves_unrelated_musical_notes() -> None:
    sc = _scenario_by_id("music_plus_60hz_hum")
    out = process_audio_pipeline(sc.noisy_input, sc.sample_rate, sc.request)

    assert out.processing_mode == "applied"
    assert out.actions.hum_notches_applied is True
    assert any(abs(f - 60.0) < 1.5 for f in out.actions.hum_notched_frequencies_hz)

    in_snr = compute_snr_db(sc.clean, sc.noisy_input)
    out_snr = compute_snr_db(sc.clean, out.processed)
    in_sisdr = compute_si_sdr_db(sc.clean, sc.noisy_input)
    out_sisdr = compute_si_sdr_db(sc.clean, out.processed)

    assert in_snr is not None and out_snr is not None
    assert out_snr > in_snr + 6.0
    assert in_sisdr is not None and out_sisdr is not None
    assert out_sisdr > in_sisdr + 6.0


def test_broadband_hiss_reduction_preserves_plucked_transients() -> None:
    sc = _scenario_by_id("music_plus_broadband_hiss")
    out = process_audio_pipeline(sc.noisy_input, sc.sample_rate, sc.request)

    assert out.processing_mode == "applied"
    assert len(out.actions.broadband_applied_channels) >= 1

    in_snr = compute_snr_db(sc.clean, sc.noisy_input)
    out_snr = compute_snr_db(sc.clean, out.processed)
    trans = compute_transient_preservation(sc.clean, out.processed, sc.sample_rate)

    assert in_snr is not None and out_snr is not None
    assert out_snr > in_snr + 2.0
    assert trans is not None and trans >= 0.90


def test_low_frequency_rumble_reduction_and_bass_note_preservation() -> None:
    # Rumble scenario with optional HPF enabled removes rumble cleanly
    rumble_sc = _scenario_by_id("music_plus_low_freq_rumble")
    rumble_out = process_audio_pipeline(
        rumble_sc.noisy_input, rumble_sc.sample_rate, rumble_sc.request
    )
    assert rumble_out.actions.hpf_applied is True
    assert compute_snr_db(rumble_sc.clean, rumble_out.processed) > (
        compute_snr_db(rumble_sc.clean, rumble_sc.noisy_input) + 5.0
    )

    # Low-frequency bass notes (41.2..61.74 Hz) with default HPF off must NOT be damaged
    bass_sc = _scenario_by_id("low_freq_bass_notes")
    bass_out = process_audio_pipeline(
        bass_sc.noisy_input, bass_sc.sample_rate, bass_sc.request
    )
    assert bass_out.actions.hpf_applied is False
    assert bass_out.actions.hum_notches_applied is False
    bass_sisdr = compute_si_sdr_db(bass_sc.clean, bass_out.processed)
    assert bass_sisdr is not None and bass_sisdr > 40.0


def test_plucked_clean_transients_and_stereo_single_channel_isolation() -> None:
    pluck_sc = _scenario_by_id("plucked_percussive_transients")
    pluck_out = process_audio_pipeline(
        pluck_sc.noisy_input, pluck_sc.sample_rate, pluck_sc.request
    )
    trans = compute_transient_preservation(
        pluck_sc.clean, pluck_out.processed, pluck_sc.sample_rate
    )
    assert trans is not None and trans >= 0.98

    # Stereo recording with hum ONLY in Left channel must leave Right channel untouched
    stereo_sc = _scenario_by_id("stereo_single_channel_disturbance")
    stereo_out = process_audio_pipeline(
        stereo_sc.noisy_input, stereo_sc.sample_rate, stereo_sc.request
    )
    assert stereo_out.processed.shape == stereo_sc.noisy_input.shape
    # Left channel improved significantly
    left_in_snr = compute_snr_db(stereo_sc.clean[:, 0], stereo_sc.noisy_input[:, 0])
    left_out_snr = compute_snr_db(stereo_sc.clean[:, 0], stereo_out.processed[:, 0])
    assert left_in_snr is not None and left_out_snr is not None
    assert left_out_snr > left_in_snr + 6.0

    # Right channel completely untouched (bit-identical)
    assert np.allclose(
        stereo_out.processed[:, 1], stereo_sc.noisy_input[:, 1], atol=1e-6
    )


def test_residual_exact_post_limiter_and_unnormalized() -> None:
    sr = 48000
    t = np.arange(sr, dtype=np.float64) / sr
    # Deliberately hot peak (0.98) + 60 Hz hum so optional limiter engages at -2.0 dBTP
    hot_signal = (
        0.95 * np.sin(2.0 * math.pi * 440.0 * t)
        + 0.03 * np.sin(2.0 * math.pi * 60.0 * t)
    ).astype(np.float32)
    stereo = np.column_stack([hot_signal, hot_signal])

    req = ProcessRequest(
        strength=0.6,
        hum_reduction_enabled=True,
        enable_limiter=True,
        limiter_ceiling_dbtp=-2.0,
    )
    out = process_audio_pipeline(stereo, sr, req)

    assert out.actions.limiter_engaged is True
    assert out.processed_levels.true_peak_dbtp is not None
    assert out.processed_levels.true_peak_dbtp <= -1.7

    # Exact post-limiter sample alignment: residual[n] == original[n] - final_processed[n]
    expected_residual = (
        stereo.astype(np.float64) - out.processed.astype(np.float64)
    ).astype(np.float32)
    assert out.residual.shape == stereo.shape
    assert np.allclose(out.residual, expected_residual, atol=1e-6)
    # Verify residual is NOT normalized to full scale
    assert float(np.max(np.abs(out.residual))) < 0.5


def test_silence_and_explicit_bypass_preserve_exact_samples() -> None:
    sr = 48000
    silent = np.zeros((sr, 2), dtype=np.float32)
    silent_out = process_audio_pipeline(silent, sr, ProcessRequest())
    assert silent_out.processing_mode == "bypassed_clean_or_silent"
    assert np.array_equal(silent_out.processed, silent)
    assert np.array_equal(silent_out.residual, silent)

    noisy = _scenario_by_id("music_plus_60hz_hum").noisy_input
    bypass_out = process_audio_pipeline(noisy, sr, ProcessRequest(bypass=True))
    assert bypass_out.processing_mode == "bypassed"
    assert np.array_equal(bypass_out.processed, noisy)
    assert float(np.max(np.abs(bypass_out.residual))) == 0.0
