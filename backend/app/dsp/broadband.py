"""Conservative musical broadband noise suppressor (Decision-Directed Wiener + guards).

Design priorities:
1. Per-channel clean-signal bypass: untouched channels stay bit-for-bit clean.
2. Sub-band broadband noise gate: evaluates noise-floor energy and spectral flatness
   across musical sub-bands (150-1000 Hz, 1000-4000 Hz, 4000-12000 Hz, clipped safely
   to Nyquist) so colored, mid-band, or mic/MP3-rolled-off background noise is not
   misclassified as tonal content, while genuinely clean or tonal recordings still bypass.
3. Sustained musical tone & harmonic protection: narrowband peaks and vibrato
   sidebands receive high gain floors so harmonics/sustain are never gated away.
4. Transient / attack protection: positive spectral-flux onset frames relax
   suppression so plucks, hammer strikes, and percussion retain full punch.
5. Conservative attenuation cap: limits maximum suppression (<= 14.5 dB) to prevent
   "watery" musical noise artifacts and unnatural silence pumping.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal
from scipy.ndimage import median_filter, uniform_filter

from app.analysis.noise_estimator import estimate_noise_floor
from app.analysis.spectral import (
    POWER_EPS,
    compute_power_stft,
    compute_spectral_flatness,
    power_to_db,
    select_stft_params,
)

CLEAN_CHANNEL_FLOOR_DBFS = -72.0

# Sub-band gate definitions: (id, low_hz, high_hz, min_floor_db, min_flatness)
# Lower mid band (150-1000 Hz) uses a slightly stricter floor threshold because
# sustained musical fundamentals live there; upper band requires higher flatness
# to avoid mistaking bright harmonic overtones for broadband hiss.
_GATE_SUBBANDS: tuple[tuple[str, float, float, float, float], ...] = (
    ("low_mid_150_1000", 150.0, 1000.0, -64.0, 0.30),
    ("mid_1000_4000", 1000.0, 4000.0, -66.0, 0.30),
    ("high_4000_12000", 4000.0, 12000.0, -68.0, 0.38),
)


@dataclass(frozen=True)
class SubbandNoiseAssessment:
    """Per-band noise floor level and spectral flatness used by the auto-bypass gate."""

    band_id: str
    low_hz: float
    high_hz: float
    floor_db: float
    flatness: float
    triggered: bool


@dataclass(frozen=True)
class BroadbandGateDecision:
    """Transparent decision record for whether broadband suppression should engage."""

    should_apply: bool
    overall_floor_db: float | None
    sustained_tonal_warning: bool
    subbands: list[SubbandNoiseAssessment]
    reason: str


@dataclass(frozen=True)
class BroadbandSuppressionResult:
    audio: np.ndarray
    applied_channels: list[int]
    skipped_clean_channels: list[int]
    max_attenuation_cap_db: float
    notes: list[str]


def evaluate_broadband_noise_gate(
    freqs: np.ndarray,
    broadband_floor_power_psd: np.ndarray,
    overall_floor_db: float | None,
    sustained_tonal_warning: bool,
    sample_rate: int,
) -> BroadbandGateDecision:
    """Decide whether a channel has a genuine broadband noise bed across sub-bands.

    Evaluates each sub-band jointly on (1) its own integrated estimated floor power
    and (2) its own local spectral flatness, clipped safely to Nyquist. This prevents:
    - False bypass on colored, mid-band, or high-frequency rolled-off background noise
      (where a single 100 Hz-24 kHz flatness collapses toward zero).
    - False activation on clean musical recordings (where empty high bands are flat
      at -110 dBFS, or sustained tonal chords have low per-band flatness).
    """
    if overall_floor_db is None or overall_floor_db < CLEAN_CHANNEL_FLOOR_DBFS:
        return BroadbandGateDecision(
            should_apply=False,
            overall_floor_db=overall_floor_db,
            sustained_tonal_warning=sustained_tonal_warning,
            subbands=[],
            reason=(
                f"Auto-bypassed broadband suppression (estimated floor "
                f"{overall_floor_db} dBFS is below clean threshold {CLEAN_CHANNEL_FLOOR_DBFS:.0f} dBFS)."
            ),
        )

    nyquist = float(sample_rate) / 2.0
    max_usable_hz = nyquist * 0.92
    assessments: list[SubbandNoiseAssessment] = []
    triggered_bands: list[SubbandNoiseAssessment] = []

    for band_id, low_hz, high_hz, base_floor_thresh, base_flat_thresh in _GATE_SUBBANDS:
        if low_hz >= max_usable_hz:
            continue
        eff_high = min(high_hz, max_usable_hz)
        if eff_high - low_hz < 120.0:
            continue

        mask = (freqs >= low_hz) & (freqs <= eff_high)
        if int(np.sum(mask)) < 4:
            continue

        band_slice = broadband_floor_power_psd[mask]
        band_floor_db = round(float(power_to_db(float(np.sum(band_slice)))), 2)
        band_flatness = round(compute_spectral_flatness(band_slice), 4)

        # Apply stricter floor & flatness thresholds when sustained narrowband musical
        # tones persisted across the recording, guarding against tonal false positives.
        req_floor_db = base_floor_thresh + (4.0 if sustained_tonal_warning else 0.0)
        req_flatness = base_flat_thresh + (0.10 if sustained_tonal_warning else 0.0)

        # Standard sub-band broadband detection
        standard_hit = band_floor_db > req_floor_db and band_flatness >= req_flatness

        # Substantial colored-noise floor safeguard: if a sub-band carries a genuinely
        # loud noise bed (> -48 dBFS) with clearly non-impulsive spread (flatness >= 0.22)
        # and is not dominated by sustained tonal spikes, do not bypass purely due to slope.
        loud_colored_hit = (
            not sustained_tonal_warning
            and band_floor_db > -48.0
            and band_flatness >= 0.22
        )

        triggered = standard_hit or loud_colored_hit
        item = SubbandNoiseAssessment(
            band_id=band_id,
            low_hz=round(low_hz, 1),
            high_hz=round(eff_high, 1),
            floor_db=band_floor_db,
            flatness=band_flatness,
            triggered=triggered,
        )
        assessments.append(item)
        if triggered:
            triggered_bands.append(item)

    if not triggered_bands:
        summary = ", ".join(
            f"{b.low_hz:.0f}-{b.high_hz:.0f}Hz({b.floor_db:.1f}dB, flat={b.flatness:.2f})"
            for b in assessments
        )
        return BroadbandGateDecision(
            should_apply=False,
            overall_floor_db=overall_floor_db,
            sustained_tonal_warning=sustained_tonal_warning,
            subbands=assessments,
            reason=(
                "Auto-bypassed broadband suppression (no sub-band met broadband noise floor & "
                f"flatness thresholds: {summary or 'no valid bands'})."
            ),
        )

    hit_desc = ", ".join(
        f"{b.low_hz:.0f}-{b.high_hz:.0f}Hz ({b.floor_db:.1f} dBFS, flat={b.flatness:.2f})"
        for b in triggered_bands
    )
    return BroadbandGateDecision(
        should_apply=True,
        overall_floor_db=overall_floor_db,
        sustained_tonal_warning=sustained_tonal_warning,
        subbands=assessments,
        reason=f"Broadband noise bed verified in {hit_desc}.",
    )


def _process_single_channel_wiener(
    ch_audio: np.ndarray,
    sample_rate: int,
    strength: float,
) -> tuple[np.ndarray, bool, str]:
    """Run conservative musical Decision-Directed Wiener suppression on one channel."""
    num_frames = ch_audio.shape[0]
    duration = float(num_frames) / float(sample_rate)
    if num_frames < 256 or strength <= 0.0:
        return ch_audio.copy(), False, "Bypassed (strength=0 or clip too short)."

    # 1. Estimate noise floor conservatively via Stage 3 Blackman-Harris STFT + valley guard
    analysis_stft = compute_power_stft(ch_audio[:, np.newaxis], sample_rate)
    nf_result = estimate_noise_floor(
        stft=analysis_stft,
        duration_seconds=duration,
        is_silent=False,
    )

    freqs_an = analysis_stft.freqs
    floor_db = nf_result.estimate.broadband_noise_floor_dbfs

    # Sub-band noise gate handles colored, mid-band, and mic/MP3 rolled-off noise safely
    gate = evaluate_broadband_noise_gate(
        freqs=freqs_an,
        broadband_floor_power_psd=nf_result.broadband_floor_power_psd,
        overall_floor_db=floor_db,
        sustained_tonal_warning=nf_result.estimate.sustained_tonal_warning,
        sample_rate=sample_rate,
    )
    if not gate.should_apply:
        return ch_audio.copy(), False, gate.reason

    # 2. COLA-exact Hann STFT (75% overlap) for artifact-free synthesis
    n_fft, hop_length = select_stft_params(sample_rate, num_frames)
    noverlap = n_fft - hop_length
    window = signal.get_window("hann", n_fft, fftbins=True)

    f_stft, _, zxx = signal.stft(
        ch_audio.astype(np.float64, copy=False),
        fs=float(sample_rate),
        window=window,
        nperseg=n_fft,
        noverlap=noverlap,
        boundary="zeros",
        padded=True,
    )
    mag_sq = np.abs(zxx) ** 2  # shape (F, T)
    num_f, num_t = mag_sq.shape

    # Map conservative Parseval noise PSD onto Hann STFT bin scale accurately
    win_sum = float(np.sum(window))
    win_energy = float(np.sum(window * window))
    parseval_scale = (win_sum * win_sum) / (float(n_fft) * max(win_energy, 1e-12))
    one_sided = np.ones(num_f, dtype=np.float64)
    if n_fft % 2 == 0:
        one_sided[1:-1] = 2.0
    else:
        one_sided[1:] = 2.0
    bin_to_parseval = parseval_scale * one_sided

    # Interpolate guarded broadband floor onto STFT frequency grid & convert to |zxx|^2 units
    interp_parseval_floor = np.interp(
        f_stft, freqs_an, nf_result.broadband_floor_power_psd
    )
    # Match bin width ratio if n_fft differed from analysis_stft.n_fft
    bin_ratio = float(analysis_stft.n_fft) / float(n_fft)
    noise_psd = np.maximum(
        (interp_parseval_floor * bin_ratio) / np.maximum(bin_to_parseval, 1e-12),
        POWER_EPS,
    )

    # Conservative gain floor and over-subtraction beta scaled by strength (0..0.85)
    # At strength=0.45 -> max attenuation ~9.9 dB; at strength=0.85 -> max attenuation ~14.5 dB
    max_atten_db = 3.0 + 13.0 * (strength / 0.85)
    max_atten_db = float(min(14.5, max(3.0, max_atten_db)))
    g_min = float(10.0 ** (-max_atten_db / 20.0))
    beta = float(0.45 + 0.95 * (strength / 0.85))  # gentle 0.45..1.40
    alpha_dd = 0.96

    # 3. Decision-Directed Wiener Gain Estimation
    gain = np.ones((num_f, num_t), dtype=np.float64)
    prev_clean_sq = mag_sq[:, 0].copy()

    for t in range(num_t):
        gamma = mag_sq[:, t] / noise_psd  # a posteriori SNR
        if t == 0:
            xi = np.maximum(gamma - 1.0, 0.0)
        else:
            xi = alpha_dd * (prev_clean_sq / noise_psd) + (1.0 - alpha_dd) * np.maximum(
                gamma - 1.0, 0.0
            )
        # Wiener gain with gentle floor
        g_t = xi / (xi + beta)
        g_t = np.clip(g_t, g_min, 1.0)
        gain[:, t] = g_t
        prev_clean_sq = (g_t * g_t) * mag_sq[:, t]

    # 4. Musicality Guardrail A: Harmonic / Tonal Peak Protection (per frame)
    # Protect narrowband peaks >= 6 dB above local frequency median (+ adjacent bins for vibrato)
    log_mag = 10.0 * np.log10(np.maximum(mag_sq, POWER_EPS))
    local_freq_med = median_filter(log_mag, size=(11, 1), mode="nearest")
    tonal_prom_db = log_mag - local_freq_med
    # Only protect tonal peaks that are meaningfully above the noise floor (+4 dB)
    noise_db_col = 10.0 * np.log10(noise_psd)[:, np.newaxis]
    harmonic_mask = (tonal_prom_db >= 6.0) & (log_mag >= noise_db_col + 4.0)
    # Widen by +-1 frequency bin to preserve vibrato & natural partial width
    if num_f >= 3:
        dilated_harmonic = harmonic_mask.copy()
        dilated_harmonic[1:, :] |= harmonic_mask[:-1, :]
        dilated_harmonic[:-1, :] |= harmonic_mask[1:, :]
        harmonic_mask = dilated_harmonic

    # Raise gain floor on detected musical harmonics (0.88 minimum)
    gain = np.where(harmonic_mask, np.maximum(gain, 0.88), gain)

    # 5. Musicality Guardrail B: Transient / Attack Protection
    # Positive spectral flux detects plucks, hammer hits, and percussive attacks
    mag_amp = np.sqrt(np.maximum(mag_sq, POWER_EPS))
    flux = np.zeros(num_t, dtype=np.float64)
    if num_t > 1:
        diff = np.maximum(mag_amp[:, 1:] - mag_amp[:, :-1], 0.0)
        flux[1:] = np.sum(diff, axis=0)
        med_flux = float(np.median(flux)) + 1e-9
        std_flux = float(np.std(flux)) + 1e-9
        transient_score = np.clip((flux - (med_flux + 1.5 * std_flux)) / (3.0 * std_flux), 0.0, 1.0)
        # Protect onset frame and 1 trailing frame so crisp attack transients stay untouched
        if num_t > 2:
            transient_score[1:] = np.maximum(transient_score[1:], 0.7 * transient_score[:-1])
        transient_floor = g_min + (0.95 - g_min) * transient_score
        gain = np.maximum(gain, transient_floor[np.newaxis, :])

    # 6. Musicality Guardrail C: Gentle 2D Time-Frequency Mask Smoothing (eliminates musical noise)
    # Preserve sharp transient gains by taking max with pre-smoothed transient peaks
    smoothed_gain = uniform_filter(gain, size=(3, 3), mode="nearest")
    gain = np.clip(np.maximum(smoothed_gain, gain * 0.85), g_min, 1.0)

    # 7. Exact COLA ISTFT reconstruction
    _, reconstructed = signal.istft(
        zxx * gain,
        fs=float(sample_rate),
        window=window,
        nperseg=n_fft,
        noverlap=noverlap,
        boundary=True,
    )

    # Guarantee exact sample count alignment with input
    if reconstructed.shape[0] >= num_frames:
        out = reconstructed[:num_frames]
    else:
        out = np.pad(reconstructed, (0, num_frames - reconstructed.shape[0]))

    note = (
        f"Applied Decision-Directed musical Wiener suppression ({gate.reason} "
        f"est. floor {floor_db:.1f} dBFS, max attenuation cap -{max_atten_db:.1f} dB, "
        "harmonic & transient protection active)."
    )
    return out.astype(np.float32), True, note


def apply_musical_broadband_suppression(
    samples: np.ndarray,
    sample_rate: int,
    strength: float,
) -> BroadbandSuppressionResult:
    """Apply conservative musical broadband suppression independently per channel."""
    max_atten_db = round(float(min(14.5, max(3.0, 3.0 + 13.0 * (strength / 0.85)))), 1)
    out = np.empty_like(samples, dtype=np.float32)
    applied_channels: list[int] = []
    skipped_clean_channels: list[int] = []
    notes: list[str] = []

    for ch in range(samples.shape[1]):
        ch_out, applied, ch_note = _process_single_channel_wiener(
            samples[:, ch], sample_rate, strength
        )
        out[:, ch] = ch_out
        if applied:
            applied_channels.append(ch + 1)
        else:
            skipped_clean_channels.append(ch + 1)
        notes.append(f"Channel {ch + 1}: {ch_note}")

    return BroadbandSuppressionResult(
        audio=out,
        applied_channels=applied_channels,
        skipped_clean_channels=skipped_clean_channels,
        max_attenuation_cap_db=max_atten_db,
        notes=notes,
    )
