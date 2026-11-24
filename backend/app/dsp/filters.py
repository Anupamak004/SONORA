"""Conservative deterministic pre-filtering: DC removal, optional HPF, pitch-safe hum notch."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

from app.analysis.spectral import compute_power_stft, power_to_db

DC_OFFSET_THRESHOLD = 2e-3  # ~ -54 dBFS; real hardware DC bias (avoids finite-window musical mean)


@dataclass(frozen=True)
class DcRemovalResult:
    audio: np.ndarray
    applied: bool
    max_offset_measured: float


@dataclass(frozen=True)
class HpfResult:
    audio: np.ndarray
    applied: bool
    cutoff_hz: float | None
    note: str | None = None


@dataclass(frozen=True)
class HumNotchResult:
    audio: np.ndarray
    applied: bool
    detected_base_hz_by_channel: list[float | None]
    notched_frequencies_by_channel: list[list[float]]
    notes: list[str]


def remove_dc_offset_if_present(
    samples: np.ndarray, sample_rate: int
) -> DcRemovalResult:
    """Remove measurable per-channel DC bias via exact zero-phase mean subtraction."""
    _ = sample_rate
    means = np.mean(samples.astype(np.float64), axis=0)
    max_dc = float(np.max(np.abs(means)))
    if max_dc <= DC_OFFSET_THRESHOLD:
        return DcRemovalResult(audio=samples.copy(), applied=False, max_offset_measured=max_dc)

    out = samples.astype(np.float64, copy=True)
    for ch in range(out.shape[1]):
        if abs(float(means[ch])) > DC_OFFSET_THRESHOLD:
            out[:, ch] -= means[ch]

    return DcRemovalResult(
        audio=out.astype(np.float32),
        applied=True,
        max_offset_measured=round(max_dc, 6),
    )


def apply_conservative_hpf(
    samples: np.ndarray,
    sample_rate: int,
    cutoff_hz: float,
) -> HpfResult:
    """Apply zero-phase 2nd-order Butterworth high-pass filter when explicitly enabled."""
    nyquist = float(sample_rate) / 2.0
    if cutoff_hz >= nyquist * 0.4 or samples.shape[0] < 32:
        return HpfResult(
            audio=samples.copy(),
            applied=False,
            cutoff_hz=None,
            note="Skipped high-pass filter: clip too short or cutoff too close to Nyquist.",
        )

    sos = signal.butter(2, float(cutoff_hz), btype="highpass", fs=float(sample_rate), output="sos")
    out = np.empty_like(samples, dtype=np.float64)
    padlen = min(3 * (2 * sos.shape[0] + 1), samples.shape[0] - 1)

    for ch in range(samples.shape[1]):
        out[:, ch] = signal.sosfiltfilt(
            sos, samples[:, ch].astype(np.float64, copy=False), padlen=padlen
        )

    return HpfResult(
        audio=out.astype(np.float32),
        applied=True,
        cutoff_hz=round(float(cutoff_hz), 1),
        note=f"Applied zero-phase high-pass filter at {cutoff_hz:.1f} Hz.",
    )


def _find_verified_hum_harmonics_for_channel(
    channel_audio: np.ndarray,
    sample_rate: int,
) -> tuple[float | None, list[tuple[float, float]]]:
    """Identify steady narrowband 50/60 Hz hum harmonics on a single channel.

    Returns (base_freq_hz, [(exact_freq_hz, Q_factor), ...]).
    Uses strict local-maximum, temporal-steadiness, and pitch-conflict guards so
    musical bass notes (e.g., E1=41.2, G1=49.0, B1=61.74 Hz) are never damaged.
    """
    num_frames = channel_audio.shape[0]
    duration = float(num_frames) / float(sample_rate)
    if duration < 0.35 or num_frames < 2048:
        return None, []

    target_nfft = 16384 if sample_rate >= 40000 else 8192
    n_fft = target_nfft
    while n_fft > num_frames and n_fft > 2048:
        n_fft //= 2
    hop = max(512, n_fft // 4)

    stft = compute_power_stft(
        channel_audio[:, np.newaxis],
        sample_rate,
        n_fft=n_fft,
        hop_length=hop,
    )
    freqs = stft.freqs
    power = stft.power_bins
    nyquist = float(sample_rate) / 2.0
    if freqs.size < 32:
        return None, []

    df = float(freqs[1] - freqs[0])
    tol_hz = max(1.5, df * 1.05)

    median_psd = np.median(power, axis=1)
    p90_psd = np.percentile(power, 90, axis=1)
    p10_psd = np.percentile(power, 10, axis=1)

    def _eval_base(base_hz: float) -> tuple[float, list[tuple[float, float]]]:
        candidates: list[tuple[float, float]] = []
        total_prom = 0.0
        has_fundamental = False

        for h in range(1, 7):
            target = base_hz * h
            if target + 18.0 >= nyquist:
                break

            peak_mask = np.abs(freqs - target) <= tol_hz
            side_mask = (
                ((freqs >= target - 20.0) & (freqs <= target - max(5.0, tol_hz * 2.0)))
                | ((freqs >= target + max(5.0, tol_hz * 2.0)) & (freqs <= target + 20.0))
            )
            if not np.any(peak_mask) or not np.any(side_mask):
                continue

            indices = np.flatnonzero(peak_mask)
            local_best = int(np.argmax(median_psd[indices]))
            peak_idx = int(indices[local_best])
            if peak_idx <= 1 or peak_idx >= median_psd.shape[0] - 2:
                continue

            peak_power = float(median_psd[peak_idx])
            # Must be a true local maximum (prevents catching skirts of nearby musical notes)
            if not (
                peak_power > float(median_psd[peak_idx - 1])
                and peak_power > float(median_psd[peak_idx + 1])
            ):
                continue

            # Parabolic interpolation for sub-bin frequency lock
            y0 = float(np.log(max(median_psd[peak_idx - 1], 1e-18)))
            y1 = float(np.log(max(peak_power, 1e-18)))
            y2 = float(np.log(max(median_psd[peak_idx + 1], 1e-18)))
            denom = y0 - 2.0 * y1 + y2
            delta = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
            delta = float(np.clip(delta, -0.5, 0.5))
            refined_freq = float(freqs[peak_idx]) + delta * df

            # Reject if refined frequency drifts > 1.25 Hz from exact mains harmonic
            # (e.g., B1 = 61.74 Hz is 1.74 Hz away from 60 Hz; G1 = 49.0 Hz is 1.0 Hz away
            #  but also check bandwidth / nearby musical overlap!)
            if abs(refined_freq - target) > 1.2:
                continue

            peak_db = float(power_to_db(peak_power))
            floor_db = float(power_to_db(float(np.median(median_psd[side_mask]))))
            prom_db = peak_db - floor_db

            # Temporal steadiness: electrical hum stays steady; musical notes vary in envelope
            spread_db = max(
                0.0,
                float(power_to_db(float(p90_psd[peak_idx])))
                - float(power_to_db(float(p10_psd[peak_idx]))),
            )
            if peak_db <= -76.0 or prom_db < 9.0 or spread_db > 6.5:
                continue

            # Pitch-conflict guard: check if adjacent bins (2..5 Hz away) carry strong tonal
            # musical energy (e.g., vibrato or an adjacent semitone like G1=49 Hz / B1=61.7 Hz)
            near_music_mask = (np.abs(freqs - refined_freq) >= max(2.2, df * 1.2)) & (
                np.abs(freqs - refined_freq) <= 6.5
            )
            near_peak_db = (
                float(power_to_db(float(np.max(p90_psd[near_music_mask]))))
                if np.any(near_music_mask)
                else -120.0
            )
            # If an active musical note sits right beside the hum frequency, tighten Q conservatively
            if near_peak_db > peak_db - 6.0:
                q_factor = 60.0
            else:
                q_factor = 42.0

            if h == 1:
                has_fundamental = True
            candidates.append((refined_freq, q_factor))
            total_prom += prom_db

        # Require fundamental OR >= 2 harmonics to engage hum notching
        if not has_fundamental and len(candidates) < 2:
            return 0.0, []
        return total_prom, candidates

    score50, harms50 = _eval_base(50.0)
    score60, harms60 = _eval_base(60.0)

    if not harms50 and not harms60:
        return None, []
    if score60 >= score50 and harms60:
        return 60.0, harms60
    return 50.0, harms50


def apply_pitch_safe_hum_notch(
    samples: np.ndarray,
    sample_rate: int,
    strength: float,
) -> HumNotchResult:
    """Apply per-channel evidence-gated zero-phase narrow-Q hum notch filters."""
    if strength <= 0.0 or samples.shape[0] < 2048:
        return HumNotchResult(
            audio=samples.copy(),
            applied=False,
            detected_base_hz_by_channel=[None] * samples.shape[1],
            notched_frequencies_by_channel=[[] for _ in range(samples.shape[1])],
            notes=[],
        )

    out = samples.astype(np.float64, copy=True)
    detected_bases: list[float | None] = []
    notched_by_ch: list[list[float]] = []
    notes: list[str] = []
    any_applied = False

    # Scale notch blend smoothly so low strength still attenuates hum gently without harshness
    notch_mix = float(np.clip(0.55 + 0.45 * (strength / 0.85), 0.55, 1.0))

    for ch in range(samples.shape[1]):
        base_hz, harmonics = _find_verified_hum_harmonics_for_channel(
            samples[:, ch], sample_rate
        )
        detected_bases.append(base_hz)
        if not harmonics:
            notched_by_ch.append([])
            continue

        filtered = out[:, ch].copy()
        applied_freqs: list[float] = []
        padlen = min(48, filtered.shape[0] - 1)

        for freq_hz, q_factor in harmonics:
            if freq_hz >= float(sample_rate) * 0.45:
                continue
            b, a = signal.iirnotch(freq_hz, q_factor, fs=float(sample_rate))
            filtered = signal.filtfilt(b, a, filtered, padlen=padlen)
            applied_freqs.append(round(freq_hz, 1))

        if applied_freqs:
            out[:, ch] = notch_mix * filtered + (1.0 - notch_mix) * out[:, ch]
            any_applied = True
            notes.append(
                f"Channel {ch + 1}: applied pitch-safe narrow-Q {int(base_hz or 0)} Hz hum notches at "
                + ", ".join(f"{f:.1f} Hz" for f in applied_freqs)
                + "."
            )
        notched_by_ch.append(applied_freqs)

    if not any_applied:
        notes.append(
            "Hum reduction enabled, but no steady narrowband 50/60 Hz hum met evidence thresholds; skipped."
        )

    return HumNotchResult(
        audio=out.astype(np.float32),
        applied=any_applied,
        detected_base_hz_by_channel=detected_bases,
        notched_frequencies_by_channel=notched_by_ch,
        notes=notes,
    )
