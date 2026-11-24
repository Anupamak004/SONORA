"""Conservative silence-free Minimum Statistics noise-floor estimation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import median_filter, percentile_filter

from app.analysis.spectral import (
    MIN_DB_FLOOR,
    POWER_EPS,
    StftResult,
    compute_spectral_flatness,
    power_to_db,
)
from app.models.schemas import ConfidenceLevel, NoiseFloorEstimate


@dataclass(frozen=True)
class NoiseFloorResult:
    """Internal spectral arrays and public summary of estimated background noise."""

    estimate: NoiseFloorEstimate
    active_power_psd: np.ndarray  # Parseval bin power (90th pct)
    median_power_psd: np.ndarray  # Parseval bin power (median)
    raw_min_power_psd: np.ndarray  # Raw temporal minimum statistics (before tonal guard)
    broadband_floor_power_psd: np.ndarray  # Tonal-guarded broadband floor (Parseval)
    active_coherent_psd: np.ndarray
    median_coherent_psd: np.ndarray
    broadband_floor_coherent_psd: np.ndarray
    inter_harmonic_flatness: float


def _exponential_smooth_time(matrix: np.ndarray, alpha: float = 0.78) -> np.ndarray:
    """Apply causal + reverse-averaged gentle temporal smoothing to reduce variance."""
    num_frames = matrix.shape[1]
    if num_frames <= 1:
        return matrix.copy()

    smoothed = np.empty_like(matrix, dtype=np.float64)
    smoothed[:, 0] = matrix[:, 0]
    one_minus = 1.0 - alpha
    for t in range(1, num_frames):
        smoothed[:, t] = alpha * smoothed[:, t - 1] + one_minus * matrix[:, t]
    return smoothed


def _minimum_statistics_envelope(
    smoothed_power: np.ndarray,
    hop_seconds: float,
    window_seconds: float = 1.25,
) -> np.ndarray:
    """Track conservative temporal minimum across sliding sub-windows (Martin 2001 inspired)."""
    num_freqs, num_frames = smoothed_power.shape
    if num_frames <= 3:
        return np.min(smoothed_power, axis=1)

    win_frames = max(4, int(round(window_seconds / max(hop_seconds, 1e-4))))
    if num_frames <= win_frames:
        # Short clip: use conservative 10th percentile with gentle bias compensation
        raw = np.percentile(smoothed_power, 10, axis=1)
        return raw * 1.25

    # Partition into overlapping sub-windows and take the lower quartile of sub-window minima
    step = max(2, win_frames // 2)
    sub_minima: list[np.ndarray] = []
    for start in range(0, num_frames - win_frames + 1, step):
        seg = smoothed_power[:, start : start + win_frames]
        sub_minima.append(np.percentile(seg, 10, axis=1))

    if not sub_minima:
        raw = np.percentile(smoothed_power, 10, axis=1)
    else:
        stacked = np.stack(sub_minima, axis=1)
        # Take 20th percentile of sub-window minima (robust against both transients and dropouts)
        raw = np.percentile(stacked, 20, axis=1)

    # Mild bias compensation factor for smoothed 10th-percentile minimum statistics
    return raw * 1.35


def _guard_against_sustained_musical_tones(
    raw_min_psd: np.ndarray,
    freqs: np.ndarray,
) -> tuple[np.ndarray, bool, float]:
    """Separate persistent narrowband musical partials from broadband noise floor.

    On a sustained violin note, organ chord, or clean sine wave, temporal minimum
    statistics remains high at the sustained pitch frequencies even when the
    inter-harmonic bins are near -120 dBFS. Comparing each bin against a local
    frequency-neighborhood lower quantile prevents sustained musical tones from
    inflating the broadband noise floor estimate.
    """
    num_bins = raw_min_psd.shape[0]
    if num_bins < 16:
        return raw_min_psd.copy(), False, 0.0

    df = float(freqs[1] - freqs[0]) if num_bins > 1 else 20.0
    # ~380 Hz frequency neighborhood (odd size, >= 15 bins) cleanly spans Blackman-Harris main lobes & harmonics
    kernel = max(15, int(round(380.0 / max(df, 1.0))))
    if kernel % 2 == 0:
        kernel += 1
    kernel = min(kernel, num_bins if num_bins % 2 == 1 else num_bins - 1)
    kernel = max(5, kernel)

    log_min = np.log10(np.maximum(raw_min_psd, POWER_EPS))
    # 20th-percentile along frequency axis tracks inter-harmonic broadband valleys
    inter_harmonic_log = percentile_filter(log_min, percentile=20, size=kernel, mode="nearest")
    inter_harmonic_floor = 10.0 ** inter_harmonic_log

    # Check how much of the raw minimum energy comes from isolated narrowband spikes (> 8 dB over local floor)
    spike_excess_db = 10.0 * (log_min - inter_harmonic_log)
    # Ignore sub-35 Hz DC/window leakage
    valid_mask = freqs >= 35.0
    spike_mask = valid_mask & (spike_excess_db > 8.0) & (raw_min_psd > 1e-11)

    total_raw_energy = float(np.sum(raw_min_psd[valid_mask]))
    spike_energy = float(np.sum(raw_min_psd[spike_mask]))
    spike_energy_ratio = spike_energy / max(total_raw_energy, POWER_EPS)

    sustained_tonal_warning = (
        total_raw_energy > 1e-9
        and spike_energy_ratio > 0.35
        and int(np.sum(spike_mask)) >= 1
    )

    # Cap isolated narrowband spikes in the *broadband* floor estimate to local valley + 3 dB
    guarded_floor = np.where(
        spike_mask,
        np.minimum(raw_min_psd, inter_harmonic_floor * 2.0),
        raw_min_psd,
    )
    # Smooth gently along frequency to remove single-bin jitter
    guarded_floor = median_filter(guarded_floor, size=3, mode="nearest")
    return guarded_floor, sustained_tonal_warning, spike_energy_ratio


def estimate_noise_floor(
    stft: StftResult,
    duration_seconds: float,
    is_silent: bool,
) -> NoiseFloorResult:
    """Compute silence-free estimated noise floor with musical-tone safeguards."""
    power_bins = stft.power_bins
    coherent_sq = stft.coherent_mag_sq
    freqs = stft.freqs

    active_power = np.percentile(power_bins, 90, axis=1)
    median_power = np.median(power_bins, axis=1)
    active_coherent = np.percentile(coherent_sq, 90, axis=1)
    median_coherent = np.median(coherent_sq, axis=1)

    if is_silent:
        zeros = np.full_like(active_power, POWER_EPS)
        estimate = NoiseFloorEstimate(
            method="minimum_statistics_spectral_floor",
            broadband_noise_floor_dbfs=None,
            active_signal_dbfs=None,
            estimated_snr_db=None,
            confidence="none",
            sustained_tonal_warning=False,
            notes=[
                "Recording is silent or near-silent (< -80 dBFS RMS); noise floor and SNR cannot be meaningfully estimated."
            ],
        )
        return NoiseFloorResult(
            estimate=estimate,
            active_power_psd=zeros,
            median_power_psd=zeros,
            raw_min_power_psd=zeros,
            broadband_floor_power_psd=zeros,
            active_coherent_psd=zeros,
            median_coherent_psd=zeros,
            broadband_floor_coherent_psd=zeros,
            inter_harmonic_flatness=0.0,
        )

    hop_seconds = float(stft.hop_length) / float(stft.sample_rate)
    smoothed_power = _exponential_smooth_time(power_bins, alpha=0.78)
    raw_min_power = _minimum_statistics_envelope(smoothed_power, hop_seconds)

    broadband_floor_power, sustained_tonal_warning, spike_ratio = (
        _guard_against_sustained_musical_tones(raw_min_power, freqs)
    )

    # Derive coherent-scaled floor curve consistent with PSD visualization
    power_ratio = np.divide(
        broadband_floor_power,
        np.maximum(median_power, POWER_EPS),
    )
    broadband_floor_coherent = np.minimum(
        median_coherent,
        median_coherent * np.clip(power_ratio, 0.0, 1.0),
    )

    # Integrate broadband Parseval power above 20 Hz
    audible_mask = freqs >= 20.0
    if not np.any(audible_mask):
        audible_mask = np.ones_like(freqs, dtype=bool)

    floor_total_power = float(np.sum(broadband_floor_power[audible_mask]))
    active_total_power = float(np.sum(active_power[audible_mask]))

    active_dbfs = round(float(power_to_db(active_total_power)), 2)

    notes: list[str] = [
        "Noise floor is estimated automatically without requiring a silent gap (Minimum Statistics + inter-harmonic valley guard)."
    ]

    if duration_seconds < 0.8:
        notes.append(
            "Recording is very short (< 0.8s); temporal minimum tracking has limited statistical reliability."
        )

    if sustained_tonal_warning:
        notes.append(
            "Sustained narrowband tonal energy persisted across the recording; inter-harmonic floor guarding was applied to avoid mistaking musical notes for stationary noise."
        )

    # Check if broadband floor is essentially numerical/digital silence (< -92 dBFS)
    raw_floor_db = float(power_to_db(floor_total_power, floor_db=MIN_DB_FLOOR))
    if raw_floor_db <= -92.0:
        broadband_floor_dbfs: float | None = round(raw_floor_db, 2)
        estimated_snr_db: float | None = round(max(0.0, active_dbfs - raw_floor_db), 2)
        notes.append(
            "Estimated broadband floor sits near digital silence (< -92 dBFS); recording appears very clean or synthetic."
        )
    else:
        broadband_floor_dbfs = round(raw_floor_db, 2)
        estimated_snr_db = round(max(0.0, active_dbfs - raw_floor_db), 2)

    # Inter-harmonic spectral flatness on broadband floor (120 Hz .. min(8 kHz, Nyquist))
    mid_mask = (freqs >= 120.0) & (freqs <= min(8000.0, stft.sample_rate * 0.45))
    floor_flatness = compute_spectral_flatness(
        broadband_floor_power[mid_mask] if np.any(mid_mask) else broadband_floor_power
    )

    # Calibrate confidence conservatively
    confidence: ConfidenceLevel
    if duration_seconds < 0.5:
        confidence = "low"
    elif sustained_tonal_warning and spike_ratio > 0.65 and raw_floor_db > -85.0:
        confidence = "low"
    elif sustained_tonal_warning or duration_seconds < 1.5:
        confidence = "moderate"
    elif floor_flatness >= 0.35 or raw_floor_db <= -92.0:
        confidence = "high"
    else:
        confidence = "moderate"

    estimate = NoiseFloorEstimate(
        method="minimum_statistics_spectral_floor",
        broadband_noise_floor_dbfs=broadband_floor_dbfs,
        active_signal_dbfs=active_dbfs,
        estimated_snr_db=estimated_snr_db,
        confidence=confidence,
        sustained_tonal_warning=sustained_tonal_warning,
        notes=notes,
    )

    return NoiseFloorResult(
        estimate=estimate,
        active_power_psd=active_power,
        median_power_psd=median_power,
        raw_min_power_psd=raw_min_power,
        broadband_floor_power_psd=broadband_floor_power,
        active_coherent_psd=active_coherent,
        median_coherent_psd=median_coherent,
        broadband_floor_coherent_psd=broadband_floor_coherent,
        inter_harmonic_flatness=floor_flatness,
    )
