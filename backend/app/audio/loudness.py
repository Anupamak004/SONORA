"""Audio level, true-peak, and ITU-R BS.1770-4 integrated loudness measurement."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal


@dataclass(frozen=True)
class AudioLevelMetrics:
    """Objective amplitude and loudness measurements for a float32 audio buffer."""

    sample_peak_dbfs: float | None
    true_peak_dbtp: float | None
    rms_dbfs: float | None
    integrated_lufs: float | None
    loudness_note: str | None


def _linear_to_dbfs(value: float, floor_linear: float = 1e-10) -> float | None:
    if value <= floor_linear or not math.isfinite(value):
        return None
    return round(20.0 * math.log10(value), 2)


def _design_k_weighting_filters(
    sample_rate: int,
) -> tuple[tuple[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]:
    """Design ITU-R BS.1770-4 K-weighting Stage 1 (high shelf) & Stage 2 (RLB HPF).

    Uses analytical bilinear transform formulas (matching BS.1770-4 at 48 kHz and
    remaining accurate across 44.1 kHz, 88.2 kHz, 96 kHz, etc.).
    """
    fs = float(sample_rate)

    # Stage 1: Pre-filter high-frequency shelf (+3.999843853973347 dB)
    f0 = 1681.974450955533
    g_db = 3.999843853973347
    q1 = 0.7071752369554196
    k1 = math.tan(math.pi * f0 / fs)
    vh = 10.0 ** (g_db / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k1 / q1 + k1 * k1
    b1 = np.array(
        [
            (vh + vb * k1 / q1 + k1 * k1) / a0,
            2.0 * (k1 * k1 - vh) / a0,
            (vh - vb * k1 / q1 + k1 * k1) / a0,
        ],
        dtype=np.float64,
    )
    a1 = np.array(
        [
            1.0,
            2.0 * (k1 * k1 - 1.0) / a0,
            (1.0 - k1 / q1 + k1 * k1) / a0,
        ],
        dtype=np.float64,
    )

    # Stage 2: Revised Low-frequency B-weighting (RLB) high-pass filter
    f0_hp = 38.13547087602444
    q2 = 0.5003270373238773
    k2 = math.tan(math.pi * f0_hp / fs)
    a0_hp = 1.0 + k2 / q2 + k2 * k2
    b2 = np.array([1.0, -2.0, 1.0], dtype=np.float64) / a0_hp
    a2 = np.array(
        [
            1.0,
            2.0 * (k2 * k2 - 1.0) / a0_hp,
            (1.0 - k2 / q2 + k2 * k2) / a0_hp,
        ],
        dtype=np.float64,
    )

    return (b1, a1), (b2, a2)


def _compute_true_peak(samples: np.ndarray, sample_rate: int) -> float:
    """Compute 4x oversampled true peak (ITU-R BS.1770-4) in bounded memory chunks."""
    num_frames = samples.shape[0]
    if num_frames == 0:
        return 0.0

    # Process in 30-second chunks with small overlap to cap memory usage
    chunk_frames = max(sample_rate * 30, 16384)
    overlap = 256
    max_peak = 0.0
    start = 0

    while start < num_frames:
        end = min(start + chunk_frames, num_frames)
        seg_start = max(0, start - overlap)
        seg_end = min(num_frames, end + overlap)
        segment = samples[seg_start:seg_end]

        if segment.shape[0] >= 8:
            oversampled = signal.resample_poly(segment, up=4, down=1, axis=0)
            seg_peak = float(np.max(np.abs(oversampled)))
        else:
            seg_peak = float(np.max(np.abs(segment)))

        if seg_peak > max_peak:
            max_peak = seg_peak
        start = end

    return max_peak


def _compute_integrated_lufs(
    samples: np.ndarray, sample_rate: int
) -> tuple[float | None, str | None]:
    """Compute ITU-R BS.1770-4 gated integrated loudness in LUFS."""
    num_frames, num_channels = samples.shape
    block_size = int(round(0.4 * sample_rate))  # 400 ms block
    hop_size = int(round(0.1 * sample_rate))  # 75% overlap (100 ms step)

    if num_frames < block_size or block_size <= 0 or hop_size <= 0:
        return None, "Audio shorter than 400 ms; gated ITU-R BS.1770 LUFS is undefined."

    (b1, a1), (b2, a2) = _design_k_weighting_filters(sample_rate)

    # Apply K-weighting filters in float64 for numerical stability at high sample rates
    filtered = signal.lfilter(b1, a1, samples.astype(np.float64, copy=False), axis=0)
    filtered = signal.lfilter(b2, a2, filtered, axis=0)

    # Sum weighted channel mean-square energy across 400 ms blocks (G_i = 1.0 for mono/stereo)
    num_blocks = 1 + (num_frames - block_size) // hop_size
    if num_blocks <= 0:
        return None, "Insufficient frames for gated ITU-R BS.1770 LUFS measurement."

    # Vectorized cumulative sum for O(N) exact block mean-square energy
    sq_sum_channels = np.sum(filtered * filtered, axis=1)
    cumsum = np.empty(num_frames + 1, dtype=np.float64)
    cumsum[0] = 0.0
    np.cumsum(sq_sum_channels, out=cumsum[1:])

    starts = np.arange(num_blocks) * hop_size
    ends = starts + block_size
    block_power = (cumsum[ends] - cumsum[starts]) / float(block_size)

    # Guard against log10(0)
    valid_power = np.maximum(block_power, 1e-18)
    block_loudness = -0.691 + 10.0 * np.log10(valid_power)

    # Step 1: Absolute threshold gate (-70 LKFS)
    abs_mask = block_loudness > -70.0
    if not np.any(abs_mask):
        return None, "Signal is below the -70 LKFS absolute loudness gate (silence/near-silence)."

    ungated_mean_power = float(np.mean(block_power[abs_mask]))
    relative_threshold = -0.691 + 10.0 * math.log10(max(ungated_mean_power, 1e-18)) - 10.0

    # Step 2: Relative threshold gate (-10 LU below ungated average)
    rel_mask = abs_mask & (block_loudness > relative_threshold)
    if not np.any(rel_mask):
        return None, "No blocks exceeded the relative loudness gate."

    gated_mean_power = float(np.mean(block_power[rel_mask]))
    integrated = -0.691 + 10.0 * math.log10(max(gated_mean_power, 1e-18))

    if not math.isfinite(integrated):
        return None, "Integrated loudness could not be computed cleanly."

    # Keep mono/stereo note clear
    note = None if num_channels in (1, 2) else f"Measured across {num_channels} channels."
    return round(integrated, 2), note


def measure_audio_levels(samples: np.ndarray, sample_rate: int) -> AudioLevelMetrics:
    """Measure sample peak (dBFS), true peak (dBTP), RMS (dBFS), and integrated LUFS."""
    if samples.ndim != 2 or samples.shape[0] == 0:
        return AudioLevelMetrics(
            sample_peak_dbfs=None,
            true_peak_dbtp=None,
            rms_dbfs=None,
            integrated_lufs=None,
            loudness_note="Empty audio buffer.",
        )

    sample_peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    true_peak = _compute_true_peak(samples, sample_rate)
    integrated_lufs, loudness_note = _compute_integrated_lufs(samples, sample_rate)

    return AudioLevelMetrics(
        sample_peak_dbfs=_linear_to_dbfs(sample_peak),
        true_peak_dbtp=_linear_to_dbfs(true_peak),
        rms_dbfs=_linear_to_dbfs(rms),
        integrated_lufs=integrated_lufs,
        loudness_note=loudness_note,
    )
