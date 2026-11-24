"""Regression tests for Stage 4 benchmark SNR, SI-SDR, per-channel, and alignment metrics."""

from __future__ import annotations

import math

import numpy as np
import pytest

from benchmarks.metrics import (
    EXACT_MATCH_SENTINEL_DB,
    compute_per_channel_si_sdr_db,
    compute_per_channel_snr_db,
    compute_si_sdr_db,
    compute_snr_db,
    evaluate_benchmark_pair,
)
from benchmarks.scenarios import build_all_scenarios


def test_joint_stereo_si_sdr_not_inflated_by_clean_channel_sentinel() -> None:
    """Regression: single-channel noise in stereo must not average a 120 dB clean channel."""
    sr = 48000
    t = np.arange(sr, dtype=np.float64) / sr
    clean_mono = 0.25 * np.sin(2.0 * math.pi * 220.0 * t)
    clean_stereo = np.column_stack([clean_mono, clean_mono]).astype(np.float32)

    # Orthogonal 50 Hz noise added ONLY to Left channel at exact known ~10 dB Left SNR
    noise_l = 0.07905694 * np.sin(2.0 * math.pi * 50.0 * t)
    noisy_stereo = clean_stereo.copy()
    noisy_stereo[:, 0] += noise_l.astype(np.float32)

    # Reduce Left noise amplitude by 4x (+12.04 dB improvement on Left)
    cleaned_stereo = clean_stereo.copy()
    cleaned_stereo[:, 0] += (0.25 * noise_l).astype(np.float32)

    metrics = evaluate_benchmark_pair(
        clean=clean_stereo,
        noisy_input=noisy_stereo,
        processed=cleaned_stereo,
        sample_rate=sr,
        processing_time_ms=10.0,
        is_clean_reference_scenario=False,
    )

    # Left SNR ~= 10.0 dB; Right has zero noise -> joint stereo SNR ~= 13.01 dB
    assert metrics.input_snr_db is not None
    assert abs(metrics.input_snr_db - 13.01) < 0.1
    assert metrics.input_si_sdr_db is not None
    # Joint SI-SDR must match joint SNR (~13.01 dB), NOT (10 + 120)/2 = 65 dB!
    assert abs(metrics.input_si_sdr_db - metrics.input_snr_db) < 0.1

    # Output joint SNR & SI-SDR both improve by exact +12.04 dB
    assert metrics.snr_improvement_db is not None
    assert metrics.si_sdr_improvement_db is not None
    assert abs(metrics.snr_improvement_db - 12.04) < 0.1
    assert abs(metrics.si_sdr_improvement_db - 12.04) < 0.1

    # Independent per-channel breakdown exposes Left vs untouched Right accurately
    assert len(metrics.input_channel_si_sdr_db) == 2
    assert abs((metrics.input_channel_si_sdr_db[0] or 0.0) - 10.0) < 0.1
    assert metrics.input_channel_si_sdr_db[1] == EXACT_MATCH_SENTINEL_DB
    assert abs((metrics.output_channel_si_sdr_db[0] or 0.0) - 22.04) < 0.1
    assert metrics.output_channel_si_sdr_db[1] == EXACT_MATCH_SENTINEL_DB


def test_si_sdr_scale_invariance_and_stereo_balance_sensitivity() -> None:
    sr = 48000
    t = np.arange(sr, dtype=np.float64) / sr
    s = 0.25 * np.sin(2.0 * math.pi * 440.0 * t)
    n = 0.025 * np.sin(2.0 * math.pi * 1000.0 * t)  # orthogonal, 20 dB SNR
    clean = np.column_stack([s, s]).astype(np.float32)
    est = np.column_stack([s + n, s + n]).astype(np.float32)

    base_sisdr = compute_si_sdr_db(clean, est)
    scaled_sisdr = compute_si_sdr_db(clean, est * 0.5)
    scaled_snr = compute_snr_db(clean, est * 0.5)

    assert base_sisdr is not None and scaled_sisdr is not None and scaled_snr is not None
    assert abs(base_sisdr - 20.0) < 0.1
    # Uniform scaling preserves SI-SDR but degrades unscaled SNR
    assert abs(scaled_sisdr - base_sisdr) < 0.05
    assert scaled_snr < 10.0

    # Asymmetric stereo gain distortion (halving only Left channel) MUST degrade joint SI-SDR
    imbalanced = clean.copy()
    imbalanced[:, 0] *= 0.5
    imbalanced_sisdr = compute_si_sdr_db(clean, imbalanced)
    assert imbalanced_sisdr is not None and imbalanced_sisdr < 15.0


def test_metrics_handle_silent_channels_and_shape_mismatch() -> None:
    silent = np.zeros((1000, 2), dtype=np.float32)
    assert compute_snr_db(silent, silent) is None
    assert compute_si_sdr_db(silent, silent) is None
    assert compute_per_channel_snr_db(silent, silent) == [None, None]
    assert compute_per_channel_si_sdr_db(silent, silent) == [None, None]

    with pytest.raises(ValueError):
        compute_si_sdr_db(np.zeros((100, 1)), np.zeros((101, 1)))


def test_all_benchmark_scenarios_are_sample_aligned() -> None:
    for sc in build_all_scenarios(seed=2026):
        assert sc.clean.shape == sc.noisy_input.shape
        assert sc.clean.ndim == 2
        assert sc.clean.dtype == np.float32
        assert sc.noisy_input.dtype == np.float32
