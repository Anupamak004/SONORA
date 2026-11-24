"""STFT computation, bounded spectrogram quantization, PSD curves, and band summaries."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal

from app.models.schemas import (
    FrequencyBandSummary,
    FrequencyScale,
    PsdComparisonData,
    SpectrogramData,
)

POWER_EPS = 1e-16
MIN_DB_FLOOR = -120.0

_MUSICAL_BANDS: tuple[tuple[str, str, float, float], ...] = (
    ("sub_bass", "Sub-Bass / Rumble", 20.0, 80.0),
    ("low_bass", "Low Bass / Hum Region", 80.0, 250.0),
    ("low_mid", "Low-Mid / Warmth", 250.0, 800.0),
    ("midrange", "Midrange / Fundamentals", 800.0, 2500.0),
    ("presence", "Presence / Harmonics", 2500.0, 6000.0),
    ("brilliance", "Brilliance / Air / Hiss", 6000.0, 20000.0),
)


@dataclass(frozen=True)
class StftResult:
    """Native sample-rate Parseval-calibrated one-sided power STFT."""

    freqs: np.ndarray  # shape (F,)
    times: np.ndarray  # shape (T,)
    power_bins: np.ndarray  # shape (F, T), sum over F == frame RMS^2
    coherent_mag_sq: np.ndarray  # shape (F, T), peak sine of amp A -> A^2 at bin
    n_fft: int
    hop_length: int
    sample_rate: int


def select_stft_params(sample_rate: int, num_frames: int) -> tuple[int, int]:
    """Select native-SR STFT window (~40-46 ms) safely clamped for short clips."""
    target = int(round(sample_rate * 0.043))
    # Nearest power of two in [256, 8192]
    n_fft = 256
    while n_fft * 2 <= target and n_fft < 8192:
        n_fft *= 2
    if abs(n_fft * 2 - target) < abs(n_fft - target) and n_fft * 2 <= 8192:
        n_fft *= 2

    # Clamp cleanly for very short recordings
    while n_fft > num_frames and n_fft > 128:
        n_fft //= 2
    n_fft = max(64, min(n_fft, num_frames))
    hop_length = max(16, n_fft // 4)
    return n_fft, hop_length


def compute_power_stft(
    samples: np.ndarray,
    sample_rate: int,
    n_fft: int | None = None,
    hop_length: int | None = None,
    window_name: str = "blackmanharris",
) -> StftResult:
    """Compute Parseval-calibrated one-sided power STFT averaged across channels.

    Uses a 4-term Blackman-Harris window (-92 dB sidelobes) by default so
    clean musical fundamentals do not leak false -45 dB sidelobe energy into
    neighboring inter-harmonic noise-floor bins. Averages power across stereo
    channels rather than summing L+R waveforms to prevent phase cancellation.
    """
    if samples.ndim == 1:
        audio = samples[:, np.newaxis]
    else:
        audio = samples

    num_frames, num_channels = audio.shape
    if n_fft is None or hop_length is None:
        auto_nfft, auto_hop = select_stft_params(sample_rate, num_frames)
        n_fft = n_fft or auto_nfft
        hop_length = hop_length or auto_hop

    n_fft = max(64, min(n_fft, num_frames))
    hop_length = max(16, min(hop_length, max(16, n_fft // 2)))
    noverlap = n_fft - hop_length

    window = signal.get_window(window_name, n_fft, fftbins=True)
    win_sum = float(np.sum(window))
    win_energy = float(np.sum(window * window))
    parseval_scale = (win_sum * win_sum) / (float(n_fft) * max(win_energy, 1e-12))

    accum_mag_sq: np.ndarray | None = None
    freqs = np.empty(0, dtype=np.float64)
    times = np.empty(0, dtype=np.float64)

    for ch in range(num_channels):
        f, t, zxx = signal.stft(
            audio[:, ch].astype(np.float64, copy=False),
            fs=float(sample_rate),
            window=window,
            nperseg=n_fft,
            noverlap=noverlap,
            boundary="zeros",
            padded=True,
        )
        mag_sq = np.abs(zxx) ** 2
        if accum_mag_sq is None:
            accum_mag_sq = mag_sq
            freqs = f
            times = t
        else:
            accum_mag_sq += mag_sq

    assert accum_mag_sq is not None
    mean_mag_sq = accum_mag_sq / float(num_channels)

    # One-sided factor: double interior bins (exclude DC and Nyquist if even)
    one_sided = np.ones((freqs.shape[0], 1), dtype=np.float64)
    if n_fft % 2 == 0:
        one_sided[1:-1, 0] = 2.0
    else:
        one_sided[1:, 0] = 2.0

    # Parseval bin power: sum over frequency == frame mean-square energy
    power_bins = mean_mag_sq * parseval_scale * one_sided

    # Coherent amplitude squared: pure sine of amplitude A -> ~A^2 at peak bin
    coherent_factor = np.ones((freqs.shape[0], 1), dtype=np.float64)
    if n_fft % 2 == 0:
        coherent_factor[1:-1, 0] = 4.0
    else:
        coherent_factor[1:, 0] = 4.0
    coherent_mag_sq = mean_mag_sq * coherent_factor

    return StftResult(
        freqs=freqs,
        times=times,
        power_bins=power_bins,
        coherent_mag_sq=coherent_mag_sq,
        n_fft=n_fft,
        hop_length=hop_length,
        sample_rate=sample_rate,
    )


def power_to_db(power: np.ndarray | float, floor_db: float = MIN_DB_FLOOR) -> np.ndarray | float:
    """Convert power values safely to dBFS with a finite floor."""
    if isinstance(power, (int, float, np.floating)):
        if power <= POWER_EPS or not math.isfinite(float(power)):
            return floor_db
        return max(floor_db, 10.0 * math.log10(float(power)))
    arr = np.maximum(power, POWER_EPS)
    return np.maximum(floor_db, 10.0 * np.log10(arr))


def compute_spectral_flatness(power_slice: np.ndarray) -> float:
    """Compute Wiener entropy (geometric mean / arithmetic mean) in [0.0, 1.0]."""
    if power_slice.size == 0:
        return 0.0
    arr = np.maximum(power_slice.astype(np.float64, copy=False), POWER_EPS)
    arith_mean = float(np.mean(arr))
    if arith_mean <= POWER_EPS * 10.0:
        return 0.0
    geom_mean = float(np.exp(np.mean(np.log(arr))))
    return float(min(1.0, max(0.0, geom_mean / arith_mean)))


def build_spectrogram(
    stft: StftResult,
    freq_scale: FrequencyScale,
    db_min: float,
    db_max: float,
    max_time_bins: int,
    max_freq_bins: int,
) -> SpectrogramData:
    """Build a bounded, uint8-quantized spectrogram for fast browser Canvas rendering."""
    freqs = stft.freqs
    times = stft.times
    mag_db = power_to_db(stft.coherent_mag_sq, floor_db=db_min)
    assert isinstance(mag_db, np.ndarray)

    # 1. Downsample time axis via max-pooling to preserve transient clarity
    num_t = times.shape[0]
    if num_t > max_time_bins:
        edges = np.linspace(0, num_t, max_time_bins + 1, dtype=np.int64)
        pooled_t = np.empty((mag_db.shape[0], max_time_bins), dtype=np.float64)
        out_times = np.empty(max_time_bins, dtype=np.float64)
        for idx in range(max_time_bins):
            s = int(edges[idx])
            e = max(s + 1, int(edges[idx + 1]))
            pooled_t[:, idx] = np.max(mag_db[:, s:e], axis=1)
            out_times[idx] = float(np.mean(times[s:e]))
    else:
        pooled_t = mag_db
        out_times = times

    # 2. Resample frequency axis to bounded log or linear grid
    nyquist = float(stft.sample_rate) / 2.0
    out_freq_count = min(max_freq_bins, freqs.shape[0])
    if freq_scale == "log":
        f_low = min(20.0, max(1.0, nyquist * 0.01))
        f_high = max(f_low * 2.0, nyquist)
        target_freqs = np.geomspace(f_low, f_high, out_freq_count)
    else:
        target_freqs = np.linspace(0.0, nyquist, out_freq_count)

    # Map each target frequency bin using bin-range max pooling / interpolation
    resampled = np.empty((out_freq_count, pooled_t.shape[1]), dtype=np.float64)
    for t_idx in range(pooled_t.shape[1]):
        resampled[:, t_idx] = np.interp(target_freqs, freqs, pooled_t[:, t_idx])

    # 3. Quantize linearly to uint8 [0..255] over [db_min, db_max]
    span = max(1.0, db_max - db_min)
    norm = np.clip((resampled - db_min) / span, 0.0, 1.0)
    quantized = np.rint(norm * 255.0).astype(np.uint8)

    return SpectrogramData(
        freq_scale=freq_scale,
        db_min=db_min,
        db_max=db_max,
        n_fft=stft.n_fft,
        hop_length=stft.hop_length,
        time_bins=int(quantized.shape[1]),
        freq_bins=int(quantized.shape[0]),
        times_sec=[round(float(v), 4) for v in out_times],
        frequencies_hz=[round(float(v), 2) for v in target_freqs],
        magnitudes_u8=quantized.tolist(),
    )


def compute_frequency_bands(
    stft: StftResult,
    active_power_psd: np.ndarray,
    median_power_psd: np.ndarray,
    noise_floor_power_psd: np.ndarray,
    is_silent: bool,
) -> list[FrequencyBandSummary]:
    """Compute per-band Parseval levels, estimated floor, SNR, and flatness."""
    nyquist = float(stft.sample_rate) / 2.0
    freqs = stft.freqs
    summaries: list[FrequencyBandSummary] = []

    for band_id, label, low_hz, high_hz in _MUSICAL_BANDS:
        if low_hz >= nyquist:
            continue
        effective_high = min(high_hz, nyquist)
        mask = (freqs >= low_hz) & (freqs < effective_high)
        if not np.any(mask):
            continue

        if is_silent:
            summaries.append(
                FrequencyBandSummary(
                    id=band_id,
                    label=label,
                    low_hz=round(low_hz, 1),
                    high_hz=round(effective_high, 1),
                    active_level_db=None,
                    median_level_db=None,
                    estimated_noise_floor_db=None,
                    estimated_band_snr_db=None,
                    spectral_flatness=0.0,
                )
            )
            continue

        active_band_power = float(np.sum(active_power_psd[mask]))
        median_band_power = float(np.sum(median_power_psd[mask]))
        floor_band_power = float(np.sum(noise_floor_power_psd[mask]))

        active_db = (
            round(float(power_to_db(active_band_power)), 2)
            if active_band_power > 1e-12
            else None
        )
        median_db = (
            round(float(power_to_db(median_band_power)), 2)
            if median_band_power > 1e-12
            else None
        )
        floor_db = (
            round(float(power_to_db(floor_band_power)), 2)
            if floor_band_power > 1e-12
            else None
        )

        snr_db: float | None = None
        if active_db is not None and floor_db is not None:
            snr_db = round(max(0.0, active_db - floor_db), 2)

        flatness = round(compute_spectral_flatness(median_power_psd[mask]), 3)

        summaries.append(
            FrequencyBandSummary(
                id=band_id,
                label=label,
                low_hz=round(low_hz, 1),
                high_hz=round(effective_high, 1),
                active_level_db=active_db,
                median_level_db=median_db,
                estimated_noise_floor_db=floor_db,
                estimated_band_snr_db=snr_db,
                spectral_flatness=flatness,
            )
        )

    return summaries


def build_psd_comparison(
    stft: StftResult,
    active_coherent_psd: np.ndarray,
    median_coherent_psd: np.ndarray,
    noise_floor_coherent_psd: np.ndarray,
    num_points: int = 128,
) -> PsdComparisonData:
    """Build compact log-spaced PSD curves for active signal, median, and noise floor."""
    nyquist = float(stft.sample_rate) / 2.0
    f_low = min(20.0, max(1.0, nyquist * 0.01))
    f_high = max(f_low * 2.0, nyquist)
    grid = np.geomspace(f_low, f_high, min(num_points, max(32, stft.freqs.shape[0])))

    active_db = np.interp(
        grid, stft.freqs, power_to_db(active_coherent_psd, floor_db=MIN_DB_FLOOR)
    )
    median_db = np.interp(
        grid, stft.freqs, power_to_db(median_coherent_psd, floor_db=MIN_DB_FLOOR)
    )
    floor_db = np.interp(
        grid, stft.freqs, power_to_db(noise_floor_coherent_psd, floor_db=MIN_DB_FLOOR)
    )

    return PsdComparisonData(
        frequencies_hz=[round(float(v), 2) for v in grid],
        active_p90_db=[round(float(v), 2) for v in active_db],
        overall_median_db=[round(float(v), 2) for v in median_db],
        estimated_noise_floor_db=[round(float(v), 2) for v in floor_db],
    )
