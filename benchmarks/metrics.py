"""Objective musical fidelity and noise-reduction metrics for benchmark evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal

from app.audio.loudness import measure_audio_levels

EPS = 1e-12
EXACT_MATCH_POWER_EPS = 1e-14
EXACT_MATCH_SENTINEL_DB = 120.0


@dataclass(frozen=True)
class BenchmarkMetrics:
    """Objective quality metrics comparing noisy input and processed output vs clean ground truth."""

    input_snr_db: float | None
    output_snr_db: float | None
    snr_improvement_db: float | None
    input_si_sdr_db: float | None
    output_si_sdr_db: float | None
    si_sdr_improvement_db: float | None
    input_channel_snr_db: list[float | None]
    output_channel_snr_db: list[float | None]
    input_channel_si_sdr_db: list[float | None]
    output_channel_si_sdr_db: list[float | None]
    input_log_spectral_distance_db: float
    log_spectral_distance_db: float
    transient_preservation: float | None
    orig_peak_dbfs: float | None
    proc_peak_dbfs: float | None
    orig_true_peak_dbtp: float | None
    proc_true_peak_dbtp: float | None
    rms_change_db: float | None
    lufs_change_db: float | None
    processing_time_ms: float


def _as_2d_f64(arr: np.ndarray) -> np.ndarray:
    a = arr.astype(np.float64, copy=False)
    return a[:, np.newaxis] if a.ndim == 1 else a


def _validate_same_shape(clean: np.ndarray, test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c = _as_2d_f64(clean)
    t = _as_2d_f64(test)
    if c.shape != t.shape:
        raise ValueError(
            f"Reference and estimate shapes must match for aligned metrics: {c.shape} vs {t.shape}"
        )
    return c, t


def compute_snr_db(clean: np.ndarray, test: np.ndarray) -> float | None:
    """Joint multi-channel SNR (dB) relative to sample-aligned clean reference.

    Aggregates signal power and error power jointly across all channels before
    taking 10*log10(signal_power / error_power). Returns 120.0 dB only when the
    entire signal across all channels matches the reference exactly.
    """
    c, t = _validate_same_shape(clean, test)
    err = t - c
    sig_p = float(np.mean(c * c))
    err_p = float(np.mean(err * err))
    if sig_p <= EPS:
        return None
    if err_p <= EXACT_MATCH_POWER_EPS:
        return EXACT_MATCH_SENTINEL_DB
    return round(10.0 * math.log10(sig_p / err_p), 2)


def compute_per_channel_snr_db(clean: np.ndarray, test: np.ndarray) -> list[float | None]:
    """Independent per-channel SNR (dB) for inspecting stereo channel asymmetry."""
    c, t = _validate_same_shape(clean, test)
    return [compute_snr_db(c[:, ch], t[:, ch]) for ch in range(c.shape[1])]


def compute_si_sdr_db(clean: np.ndarray, estimate: np.ndarray) -> float | None:
    """Joint multi-channel Scale-Invariant SDR (SI-SDR, dB).

    Subtracts per-channel mean, then computes a single joint scale projection
    alpha = <x, s> / <s, s> across the full stereo/mono vector. This:
    1. Matches joint stereo SNR energy aggregation cleanly.
    2. Prevents an untouched clean stereo channel (zero error) from injecting an
       arbitrary 120 dB sentinel into an arithmetic dB average.
    3. Penalizes unwanted stereo L/R balance shifts as distortion.
    """
    c, e = _validate_same_shape(clean, estimate)
    c_zm = c - np.mean(c, axis=0, keepdims=True)
    e_zm = e - np.mean(e, axis=0, keepdims=True)

    s = c_zm.reshape(-1)
    x = e_zm.reshape(-1)
    s_energy = float(np.dot(s, s))
    if s_energy <= EPS:
        return None

    alpha = float(np.dot(x, s)) / s_energy
    s_target = alpha * s
    e_noise = x - s_target
    t_p = float(np.dot(s_target, s_target))
    n_p = float(np.dot(e_noise, e_noise))

    if n_p <= EXACT_MATCH_POWER_EPS:
        return EXACT_MATCH_SENTINEL_DB
    if t_p <= EPS:
        return -120.0
    return round(10.0 * math.log10(t_p / n_p), 2)


def compute_per_channel_si_sdr_db(
    clean: np.ndarray, estimate: np.ndarray
) -> list[float | None]:
    """Independent per-channel SI-SDR (dB) without cross-channel sentinel averaging."""
    c, e = _validate_same_shape(clean, estimate)
    return [compute_si_sdr_db(c[:, ch], e[:, ch]) for ch in range(c.shape[1])]


def compute_log_spectral_distance_db(
    clean: np.ndarray, estimate: np.ndarray, sample_rate: int
) -> float:
    """Mean frame-wise Log-Spectral Distance (LSD in dB; lower is closer to clean)."""
    c, e = _validate_same_shape(clean, estimate)
    n_fft = min(2048, c.shape[0])
    hop = max(64, n_fft // 4)
    lsds: list[float] = []

    for ch in range(c.shape[1]):
        _, _, zc = signal.stft(c[:, ch], fs=sample_rate, nperseg=n_fft, noverlap=n_fft - hop)
        _, _, ze = signal.stft(e[:, ch], fs=sample_rate, nperseg=n_fft, noverlap=n_fft - hop)
        pc = np.maximum(np.abs(zc) ** 2, 1e-10)
        pe = np.maximum(np.abs(ze) ** 2, 1e-10)
        diff_db = 10.0 * np.log10(pc) - 10.0 * np.log10(pe)
        frame_lsd = np.sqrt(np.mean(diff_db ** 2, axis=0))
        lsds.append(float(np.mean(frame_lsd)))

    return round(float(np.mean(lsds)), 3)


def compute_transient_preservation(
    clean: np.ndarray, estimate: np.ndarray, sample_rate: int
) -> float | None:
    """Pearson correlation of positive high-resolution spectral-flux onset envelopes in [0, 1]."""
    c_2d, e_2d = _validate_same_shape(clean, estimate)
    c = np.mean(c_2d, axis=1)
    e = np.mean(e_2d, axis=1)

    n_fft = min(512, c.shape[0])
    hop = max(32, n_fft // 4)
    _, _, zc = signal.stft(c, fs=sample_rate, nperseg=n_fft, noverlap=n_fft - hop)
    _, _, ze = signal.stft(e, fs=sample_rate, nperseg=n_fft, noverlap=n_fft - hop)

    mc = np.abs(zc)
    me = np.abs(ze)
    if mc.shape[1] < 3:
        return None

    fc = np.sum(np.maximum(mc[:, 1:] - mc[:, :-1], 0.0), axis=0)
    fe = np.sum(np.maximum(me[:, 1:] - me[:, :-1], 0.0), axis=0)

    if float(np.std(fc)) < 1e-9 or float(np.std(fe)) < 1e-9:
        return None

    corr = float(np.corrcoef(fc, fe)[0, 1])
    if not math.isfinite(corr):
        return None
    return round(float(np.clip(corr, -1.0, 1.0)), 4)


def evaluate_benchmark_pair(
    *,
    clean: np.ndarray,
    noisy_input: np.ndarray,
    processed: np.ndarray,
    sample_rate: int,
    processing_time_ms: float,
    is_clean_reference_scenario: bool = False,
) -> BenchmarkMetrics:
    """Compute complete objective fidelity & noise-reduction metrics."""
    in_snr = compute_snr_db(clean, noisy_input)
    out_snr = compute_snr_db(clean, processed)
    snr_imp = (
        None
        if (is_clean_reference_scenario or in_snr is None or out_snr is None)
        else round(out_snr - in_snr, 2)
    )

    in_sisdr = compute_si_sdr_db(clean, noisy_input)
    out_sisdr = compute_si_sdr_db(clean, processed)
    sisdr_imp = (
        None
        if (is_clean_reference_scenario or in_sisdr is None or out_sisdr is None)
        else round(out_sisdr - in_sisdr, 2)
    )

    in_ch_snr = compute_per_channel_snr_db(clean, noisy_input)
    out_ch_snr = compute_per_channel_snr_db(clean, processed)
    in_ch_sisdr = compute_per_channel_si_sdr_db(clean, noisy_input)
    out_ch_sisdr = compute_per_channel_si_sdr_db(clean, processed)

    in_lsd = compute_log_spectral_distance_db(clean, noisy_input, sample_rate)
    lsd = compute_log_spectral_distance_db(clean, processed, sample_rate)
    transient_corr = compute_transient_preservation(clean, processed, sample_rate)

    orig_lvl = measure_audio_levels(noisy_input, sample_rate)
    proc_lvl = measure_audio_levels(processed, sample_rate)

    rms_change = (
        round(proc_lvl.rms_dbfs - orig_lvl.rms_dbfs, 2)
        if orig_lvl.rms_dbfs is not None and proc_lvl.rms_dbfs is not None
        else None
    )
    lufs_change = (
        round(proc_lvl.integrated_lufs - orig_lvl.integrated_lufs, 2)
        if orig_lvl.integrated_lufs is not None and proc_lvl.integrated_lufs is not None
        else None
    )

    return BenchmarkMetrics(
        input_snr_db=in_snr,
        output_snr_db=out_snr,
        snr_improvement_db=snr_imp,
        input_si_sdr_db=in_sisdr,
        output_si_sdr_db=out_sisdr,
        si_sdr_improvement_db=sisdr_imp,
        input_channel_snr_db=in_ch_snr,
        output_channel_snr_db=out_ch_snr,
        input_channel_si_sdr_db=in_ch_sisdr,
        output_channel_si_sdr_db=out_ch_sisdr,
        input_log_spectral_distance_db=in_lsd,
        log_spectral_distance_db=lsd,
        transient_preservation=transient_corr,
        orig_peak_dbfs=orig_lvl.sample_peak_dbfs,
        proc_peak_dbfs=proc_lvl.sample_peak_dbfs,
        orig_true_peak_dbtp=orig_lvl.true_peak_dbtp,
        proc_true_peak_dbtp=proc_lvl.true_peak_dbtp,
        rms_change_db=rms_change,
        lufs_change_db=lufs_change,
        processing_time_ms=processing_time_ms,
    )
