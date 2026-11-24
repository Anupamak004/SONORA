"""Optional, conditional true-peak safety limiter (never alters clean dynamics needlessly)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal


@dataclass(frozen=True)
class LimiterResult:
    audio: np.ndarray
    engaged: bool
    ceiling_dbtp: float
    peak_before_dbtp: float | None
    gain_reduction_db: float


def apply_optional_true_peak_limiter(
    samples: np.ndarray,
    sample_rate: int,
    ceiling_dbtp: float = -1.0,
) -> LimiterResult:
    """Conditionally limit peaks only if 4x oversampled true peak exceeds ceiling_dbtp.

    Stereo-linked smooth lookahead envelope preserves stereo imaging and leaves
    recordings below ceiling_dbtp completely bit-identical.
    """
    if samples.shape[0] == 0:
        return LimiterResult(
            audio=samples.copy(),
            engaged=False,
            ceiling_dbtp=ceiling_dbtp,
            peak_before_dbtp=None,
            gain_reduction_db=0.0,
        )

    ceiling_lin = float(10.0 ** (ceiling_dbtp / 20.0))

    # Measure 4x true peak conservatively
    if samples.shape[0] >= 8:
        oversampled = signal.resample_poly(samples, up=4, down=1, axis=0)
        true_peak = float(np.max(np.abs(oversampled)))
    else:
        true_peak = float(np.max(np.abs(samples)))

    peak_before_db = (
        round(float(20.0 * np.log10(true_peak)), 2) if true_peak > 1e-10 else None
    )

    if true_peak <= ceiling_lin:
        return LimiterResult(
            audio=samples.copy(),
            engaged=False,
            ceiling_dbtp=ceiling_dbtp,
            peak_before_dbtp=peak_before_db,
            gain_reduction_db=0.0,
        )

    # Stereo-linked instantaneous peak envelope
    linked_abs = np.max(np.abs(samples.astype(np.float64, copy=False)), axis=1)
    # Include safety headroom for inter-sample peaks
    sample_peak = float(np.max(linked_abs))
    isp_ratio = max(1.0, true_peak / max(sample_peak, 1e-12))
    effective_ceiling = ceiling_lin / isp_ratio

    needed_gain = np.minimum(1.0, effective_ceiling / np.maximum(linked_abs, 1e-12))

    # Smooth release envelope (~45 ms release, instant attack)
    release_coeff = float(np.exp(-1.0 / max(1.0, 0.045 * sample_rate)))
    gain_env = np.ones_like(needed_gain)
    current = 1.0
    for i in range(needed_gain.shape[0]):
        target = float(needed_gain[i])
        if target < current:
            current = target
        else:
            current = release_coeff * current + (1.0 - release_coeff) * target
        gain_env[i] = current

    # Short lookahead smoothing (~1.5 ms symmetric boxcar) to prevent harmonic distortion on attack
    lookahead = max(3, int(round(0.0015 * sample_rate)))
    if lookahead % 2 == 0:
        lookahead += 1
    if lookahead < gain_env.shape[0]:
        kernel = np.ones(lookahead, dtype=np.float64) / float(lookahead)
        gain_env = np.minimum(gain_env, np.convolve(gain_env, kernel, mode="same"))

    limited = (samples.astype(np.float64) * gain_env[:, np.newaxis]).astype(np.float32)
    min_gain = float(np.min(gain_env))
    gr_db = round(float(-20.0 * np.log10(max(min_gain, 1e-6))), 2)

    return LimiterResult(
        audio=limited,
        engaged=True,
        ceiling_dbtp=ceiling_dbtp,
        peak_before_dbtp=peak_before_db,
        gain_reduction_db=gr_db,
    )
