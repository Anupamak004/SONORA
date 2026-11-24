"""Downsampled waveform peak extraction for fast frontend WaveSurfer.js rendering."""

from __future__ import annotations

import numpy as np

from app.models.schemas import WaveformPeaks


def compute_waveform_peaks(
    samples: np.ndarray, target_buckets: int = 1200
) -> WaveformPeaks:
    """Compute a normalized peak amplitude envelope across the full recording."""
    if samples.ndim != 2 or samples.shape[0] == 0:
        return WaveformPeaks(bucket_count=1, peaks=[0.0])

    num_frames = samples.shape[0]
    bucket_count = max(1, min(target_buckets, num_frames))

    # Max absolute value across channels per frame preserves stereo transients
    mono_abs = np.max(np.abs(samples), axis=1)

    edges = np.linspace(0, num_frames, bucket_count + 1, dtype=np.int64)
    peaks: list[float] = []
    for idx in range(bucket_count):
        start = int(edges[idx])
        end = int(edges[idx + 1])
        if end <= start:
            val = float(mono_abs[min(start, num_frames - 1)])
        else:
            val = float(np.max(mono_abs[start:end]))
        clamped = min(1.0, max(0.0, val))
        peaks.append(round(clamped, 4))

    return WaveformPeaks(bucket_count=len(peaks), peaks=peaks)
