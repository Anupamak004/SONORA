"""Conservative heuristic detectors for spectral noise indicators with safeguards."""

from __future__ import annotations

import numpy as np

from app.analysis.noise_estimator import NoiseFloorResult
from app.analysis.spectral import (
    POWER_EPS,
    StftResult,
    compute_power_stft,
    compute_spectral_flatness,
    power_to_db,
)
from app.models.schemas import ConfidenceLevel, NoiseIndicator


def _score_mains_hum(
    high_res_stft: StftResult,
    base_freq_hz: float,
) -> tuple[bool, ConfidenceLevel, dict[str, float | int | str | bool | None], str]:
    """Evaluate persistence, sharpness, and harmonic alignment for 50 Hz or 60 Hz hum."""
    freqs = high_res_stft.freqs
    power = high_res_stft.power_bins
    nyquist = float(high_res_stft.sample_rate) / 2.0

    if freqs.size < 32 or nyquist < base_freq_hz * 1.5:
        return False, "none", {"base_freq_hz": base_freq_hz}, "Insufficient frequency resolution."

    df = float(freqs[1] - freqs[0])
    # Tolerance around exact mains harmonic (strictly narrow to avoid adjacent notes like 49 Hz G1 / 61.7 Hz B1)
    tol_hz = max(1.6, df * 1.1)

    median_psd = np.median(power, axis=1)
    p90_psd = np.percentile(power, 90, axis=1)
    p10_psd = np.percentile(power, 10, axis=1)

    matched_harmonics: list[int] = []
    prominences_db: list[float] = []
    spreads_db: list[float] = []
    fundamental_prom_db = 0.0
    fundamental_level_db = -120.0
    fundamental_steady = False

    for h in range(1, 7):
        target = base_freq_hz * h
        if target + 18.0 >= nyquist:
            break

        peak_mask = np.abs(freqs - target) <= tol_hz
        # Sidebands 6..20 Hz away on both sides, excluding the peak window
        side_mask = (
            ((freqs >= target - 20.0) & (freqs <= target - max(5.0, tol_hz * 2.0)))
            | ((freqs >= target + max(5.0, tol_hz * 2.0)) & (freqs <= target + 20.0))
        )
        if not np.any(peak_mask) or not np.any(side_mask):
            continue

        peak_slice = median_psd[peak_mask]
        peak_local_idx = int(np.argmax(peak_slice))
        peak_bin_indices = np.flatnonzero(peak_mask)
        peak_idx = int(peak_bin_indices[peak_local_idx])

        # Verify peak_idx is a true local spectral maximum (not the falling skirt of an adjacent musical note like E1=41.2 Hz!)
        if peak_idx <= 0 or peak_idx >= median_psd.shape[0] - 1:
            continue
        peak_power = float(median_psd[peak_idx])
        if not (
            peak_power > float(median_psd[peak_idx - 1])
            and peak_power > float(median_psd[peak_idx + 1])
        ):
            continue

        local_floor = float(np.median(median_psd[side_mask]))
        peak_db = float(power_to_db(peak_power))
        floor_db = float(power_to_db(local_floor))
        prom_db = peak_db - floor_db

        # Temporal steadiness: true electrical hum stays nearly constant across the recording
        frame_p90_db = float(power_to_db(float(p90_psd[peak_idx])))
        frame_p10_db = float(power_to_db(float(p10_psd[peak_idx])))
        temporal_spread_db = max(0.0, frame_p90_db - frame_p10_db)
        is_steady = temporal_spread_db <= 7.5

        if h == 1:
            fundamental_prom_db = prom_db
            fundamental_level_db = peak_db
            fundamental_steady = is_steady

        # Require meaningful audible level (> -78 dBFS) and sharp local prominence
        if peak_db > -78.0 and prom_db >= 8.0 and is_steady:
            matched_harmonics.append(h)
            prominences_db.append(prom_db)
            spreads_db.append(temporal_spread_db)

    # Require fundamental to be present, OR at least 2 strong steady harmonics (e.g. HPF'd mic with 100/150 or 120/180 Hz)
    has_fundamental = 1 in matched_harmonics
    num_matched = len(matched_harmonics)
    avg_prom = float(np.mean(prominences_db)) if prominences_db else 0.0
    avg_spread = float(np.mean(spreads_db)) if spreads_db else 99.0

    detected = (has_fundamental and fundamental_prom_db >= 9.0) or (
        num_matched >= 2 and avg_prom >= 10.0
    )

    if not detected:
        return (
            False,
            "none",
            {
                "base_freq_hz": base_freq_hz,
                "matched_harmonics": num_matched,
                "fundamental_prominence_db": round(fundamental_prom_db, 1),
            },
            f"No steady narrowband spectral peak matched {int(base_freq_hz)} Hz mains harmonics.",
        )

    # Confidence calibration: multi-harmonic steady alignment -> high; fundamental-only -> moderate/low
    if has_fundamental and num_matched >= 3 and avg_prom >= 12.0 and avg_spread <= 4.5:
        confidence: ConfidenceLevel = "high"
    elif (has_fundamental and num_matched >= 2 and avg_prom >= 10.0) or (
        has_fundamental and fundamental_prom_db >= 16.0 and fundamental_steady
    ):
        confidence = "moderate"
    else:
        confidence = "low"

    harm_str = ", ".join(f"{int(base_freq_hz * h)} Hz" for h in matched_harmonics)
    evidence = (
        f"Steady narrowband peaks observed near {harm_str} "
        f"(avg +{avg_prom:.1f} dB above neighboring spectrum, temporal spread {avg_spread:.1f} dB, "
        f"fundamental level {fundamental_level_db:.1f} dBFS)."
    )
    metrics: dict[str, float | int | str | bool | None] = {
        "base_freq_hz": base_freq_hz,
        "matched_harmonics": num_matched,
        "fundamental_prominence_db": round(fundamental_prom_db, 2),
        "avg_prominence_db": round(avg_prom, 2),
        "temporal_spread_db": round(avg_spread, 2),
    }
    return True, confidence, metrics, evidence


def _compute_high_res_stft(
    samples: np.ndarray,
    sample_rate: int,
    duration_seconds: float,
) -> StftResult | None:
    """Compute a high-resolution STFT (~2.7-3 Hz bins) for low-frequency hum & rumble checks."""
    num_frames = samples.shape[0]
    if duration_seconds < 0.35 or num_frames < 2048:
        return None
    target_nfft = 16384 if sample_rate >= 40000 else 8192
    n_fft = target_nfft
    while n_fft > num_frames and n_fft > 2048:
        n_fft //= 2
    hop = max(512, n_fft // 4)
    return compute_power_stft(samples, sample_rate, n_fft=n_fft, hop_length=hop)


def _detect_electrical_hum(
    high_res: StftResult | None,
) -> NoiseIndicator:
    """Detect possible 50 Hz or 60 Hz mains hum and harmonics conservatively."""
    if high_res is None:
        return NoiseIndicator(
            id="electrical_hum",
            label="Possible 50/60 Hz electrical hum",
            detected=False,
            confidence="none",
            evidence="Recording is too short for high-resolution 50/60 Hz harmonic separation.",
            caveat="At least ~0.4 seconds of audio is needed to separate 50/60 Hz mains hum from nearby musical bass notes.",
        )

    det50, conf50, met50, ev50 = _score_mains_hum(high_res, 50.0)
    det60, conf60, met60, ev60 = _score_mains_hum(high_res, 60.0)

    rank = {"none": 0, "low": 1, "moderate": 2, "high": 3}
    score50 = (
        rank[conf50],
        int(met50.get("matched_harmonics") or 0),
        float(met50.get("avg_prominence_db") or 0.0),
    )
    score60 = (
        rank[conf60],
        int(met60.get("matched_harmonics") or 0),
        float(met60.get("avg_prominence_db") or 0.0),
    )

    if not det50 and not det60:
        return NoiseIndicator(
            id="electrical_hum",
            label="Possible 50/60 Hz electrical hum",
            detected=False,
            confidence="none",
            evidence="No persistent narrowband spectral peaks aligned with 50 Hz or 60 Hz mains harmonics.",
            caveat="Very quiet hum buried beneath loud continuous playing cannot be ruled out by spectral analysis alone.",
            metrics={"checked_50hz_prom_db": met50.get("fundamental_prominence_db"), "checked_60hz_prom_db": met60.get("fundamental_prominence_db")},
        )

    if det60 and (not det50 or score60 >= score50):
        return NoiseIndicator(
            id="electrical_hum",
            label="Possible 60 Hz electrical hum",
            detected=True,
            confidence=conf60,
            evidence=ev60,
            caveat=(
                "Spectral evidence suggests possible 60 Hz mains hum, but sustained low-register "
                "musical notes (e.g., B1 = 61.7 Hz, B2 = 123.5 Hz) can sit near 60 Hz harmonics."
            ),
            metrics=met60,
        )

    return NoiseIndicator(
        id="electrical_hum",
        label="Possible 50 Hz electrical hum",
        detected=True,
        confidence=conf50,
        evidence=ev50,
        caveat=(
            "Spectral evidence suggests possible 50 Hz mains hum, but sustained low-register "
            "musical notes (e.g., G1 = 49.0 Hz, G2 = 98.0 Hz) can sit near 50 Hz harmonics."
        ),
        metrics=met50,
    )


def _detect_low_freq_rumble(
    stft: StftResult,
    high_res: StftResult | None,
    noise_floor: NoiseFloorResult,
) -> NoiseIndicator:
    """Detect possible broadband low-frequency wind or rumble while ignoring tonal bass notes."""
    lf_stft = high_res if high_res is not None else stft
    lf_freqs = lf_stft.freqs
    rumble_mask = (lf_freqs >= 18.0) & (lf_freqs <= 115.0)
    mid_mask = (stft.freqs >= 250.0) & (stft.freqs <= 2500.0)

    if int(np.sum(rumble_mask)) < 4 or not np.any(mid_mask):
        return NoiseIndicator(
            id="low_freq_rumble",
            label="Possible low-frequency wind / rumble",
            detected=False,
            confidence="none",
            evidence="Insufficient low-frequency resolution to evaluate sub-115 Hz broadband rumble.",
            caveat="Low-frequency inspection requires sample rate and duration sufficient to resolve 20–115 Hz.",
        )

    # Use high-resolution sub-115 Hz spectrum (~30+ bins) so narrowband tonal bass notes have low flatness
    lf_median = np.median(lf_stft.power_bins[rumble_mask, :], axis=1)
    lf_p10 = np.percentile(lf_stft.power_bins[rumble_mask, :], 10, axis=1)
    lf_p90 = np.percentile(lf_stft.power_bins[rumble_mask, :], 90, axis=1)

    rumble_flatness = compute_spectral_flatness(lf_median)
    floor_rumble_flatness = compute_spectral_flatness(lf_p10)
    # Require the *actual* sub-115 Hz spectrum (not just numerical noise) to be genuinely broadband
    effective_flatness = min(rumble_flatness, max(floor_rumble_flatness, rumble_flatness))

    floor_rumble_db = float(power_to_db(float(np.sum(lf_p10))))
    median_rumble_db = float(power_to_db(float(np.sum(lf_median))))
    active_rumble_db = float(power_to_db(float(np.sum(lf_p90))))
    floor_mid_db = float(
        power_to_db(float(np.sum(noise_floor.broadband_floor_power_psd[mid_mask])))
    )
    active_mid_db = float(
        power_to_db(float(np.sum(noise_floor.active_power_psd[mid_mask])))
    )

    frame_rumble_db = power_to_db(np.sum(lf_stft.power_bins[rumble_mask, :], axis=0))
    assert isinstance(frame_rumble_db, np.ndarray)
    rumble_variability_db = float(
        np.percentile(frame_rumble_db, 90) - np.percentile(frame_rumble_db, 10)
    )

    excess_over_mid_db = floor_rumble_db - floor_mid_db

    # Safeguard: clean tonal bass notes (e.g. 41.2 Hz + 82.4 Hz) have flatness < 0.08 on high-res FFT!
    is_broadband = effective_flatness >= 0.25
    steady_rumble = is_broadband and median_rumble_db > -56.0 and excess_over_mid_db >= 6.0
    gusty_wind = (
        is_broadband
        and active_rumble_db > -48.0
        and rumble_variability_db >= 8.0
        and (active_rumble_db - active_mid_db) >= -6.0
    )

    detected = steady_rumble or gusty_wind
    metrics: dict[str, float | int | str | bool | None] = {
        "estimated_rumble_floor_db": round(floor_rumble_db, 2),
        "median_rumble_db": round(median_rumble_db, 2),
        "active_rumble_db": round(active_rumble_db, 2),
        "excess_over_mid_floor_db": round(excess_over_mid_db, 2),
        "rumble_flatness": round(effective_flatness, 3),
        "temporal_variability_db": round(rumble_variability_db, 2),
    }

    if not detected:
        return NoiseIndicator(
            id="low_freq_rumble",
            label="Possible low-frequency wind / rumble",
            detected=False,
            confidence="none",
            evidence=(
                f"Sub-115 Hz broadband floor ({floor_rumble_db:.1f} dBFS, flatness {effective_flatness:.2f}) "
                "does not show prominent broadband wind or rumble."
            ),
            caveat="Tonal bass fundamentals (27–115 Hz) are intentionally excluded from rumble detection.",
            metrics=metrics,
        )

    if effective_flatness >= 0.40 and (
        (median_rumble_db > -42.0 and excess_over_mid_db >= 10.0) or gusty_wind
    ):
        confidence: ConfidenceLevel = "high" if median_rumble_db > -36.0 else "moderate"
    elif effective_flatness >= 0.30 and excess_over_mid_db >= 8.0:
        confidence = "moderate"
    else:
        confidence = "low"

    pattern = "fluctuating wind-like rumble" if gusty_wind else "steady low-frequency rumble"
    return NoiseIndicator(
        id="low_freq_rumble",
        label="Possible low-frequency wind / rumble",
        detected=True,
        confidence=confidence,
        evidence=(
            f"Elevated broadband energy ({pattern}) below 115 Hz "
            f"(est. floor {floor_rumble_db:.1f} dBFS, {excess_over_mid_db:+.1f} dB vs mid-band floor, "
            f"spectral flatness {effective_flatness:.2f})."
        ),
        caveat=(
            "Low-register instruments (piano left hand, bass, cello, kick drum) also occupy 27–115 Hz; "
            "verify by ear before applying high-pass filtering."
        ),
        metrics=metrics,
    )


def _detect_broadband_hiss(
    stft: StftResult,
    noise_floor: NoiseFloorResult,
) -> NoiseIndicator:
    """Detect possible high-frequency broadband hiss (4–16 kHz) with harmonic guards."""
    nyquist = float(stft.sample_rate) / 2.0
    if nyquist <= 4500.0:
        return NoiseIndicator(
            id="broadband_hiss",
            label="Possible broadband hiss",
            detected=False,
            confidence="none",
            evidence=f"Sample rate ({stft.sample_rate} Hz) has Nyquist {nyquist:.0f} Hz; high-frequency hiss band (> 4 kHz) cannot be evaluated.",
            caveat="Higher sample rates (>= 16 kHz) are required to inspect high-frequency hiss.",
        )

    freqs = stft.freqs
    hiss_high = min(16000.0, nyquist * 0.92)
    hiss_mask = (freqs >= 4000.0) & (freqs <= hiss_high)

    # Use tonal-guarded broadband floor so high violin/piano overtones are excluded!
    floor_hiss_slice = noise_floor.broadband_floor_power_psd[hiss_mask]
    floor_hiss_power = float(np.sum(floor_hiss_slice))
    floor_hiss_db = float(power_to_db(floor_hiss_power))
    hiss_flatness = compute_spectral_flatness(floor_hiss_slice)

    # Check persistence of high-frequency energy across frames
    frame_hf_db = power_to_db(np.sum(stft.power_bins[hiss_mask, :], axis=0))
    assert isinstance(frame_hf_db, np.ndarray)
    hf_p10_db = float(np.percentile(frame_hf_db, 10))
    hf_p90_db = float(np.percentile(frame_hf_db, 90))
    hf_spread_db = max(0.0, hf_p90_db - hf_p10_db)

    metrics: dict[str, float | int | str | bool | None] = {
        "estimated_hf_floor_db": round(floor_hiss_db, 2),
        "hf_flatness": round(hiss_flatness, 3),
        "hf_temporal_spread_db": round(hf_spread_db, 2),
        "band_high_hz": round(hiss_high, 1),
    }

    # Require elevated floor (> -66 dBFS) AND noise-like flatness (>= 0.45)
    detected = floor_hiss_db > -66.0 and hiss_flatness >= 0.45
    if not detected:
        return NoiseIndicator(
            id="broadband_hiss",
            label="Possible broadband hiss",
            detected=False,
            confidence="none",
            evidence=(
                f"High-frequency estimated floor (4–{hiss_high / 1000:.1f} kHz) is {floor_hiss_db:.1f} dBFS "
                f"with flatness {hiss_flatness:.2f}, below broadband hiss thresholds."
            ),
            caveat="Subtle preamp hiss below -66 dBFS or masked by bright cymbals/bow air may still be audible.",
            metrics=metrics,
        )

    if floor_hiss_db > -48.0 and hiss_flatness >= 0.62 and hf_spread_db <= 10.0:
        confidence: ConfidenceLevel = "high"
    elif floor_hiss_db > -58.0 and hiss_flatness >= 0.52:
        confidence = "moderate"
    else:
        confidence = "low"

    return NoiseIndicator(
        id="broadband_hiss",
        label="Possible broadband hiss",
        detected=True,
        confidence=confidence,
        evidence=(
            f"Persistent flat high-frequency floor observed across 4–{hiss_high / 1000:.1f} kHz "
            f"(est. floor {floor_hiss_db:.1f} dBFS, flatness {hiss_flatness:.2f}, spread {hf_spread_db:.1f} dB)."
        ),
        caveat=(
            "Natural instrument air, bow rosin friction, breath noise, and cymbal decay also produce "
            "high-frequency energy; spectral flatness cannot guarantee pure preamp/tape hiss."
        ),
        metrics=metrics,
    )


def _detect_broadband_environmental(
    stft: StftResult,
    noise_floor: NoiseFloorResult,
) -> NoiseIndicator:
    """Detect possible steady broadband environmental / fan-like room noise (120–4000 Hz)."""
    freqs = stft.freqs
    nyquist = float(stft.sample_rate) / 2.0
    env_mask = (freqs >= 120.0) & (freqs <= min(4000.0, nyquist * 0.9))

    if not np.any(env_mask):
        return NoiseIndicator(
            id="broadband_environmental",
            label="Possible broadband environmental / fan-like noise",
            detected=False,
            confidence="none",
            evidence="Frequency range insufficient for midrange broadband floor assessment.",
            caveat="Requires bandwidth spanning at least 120–4000 Hz.",
        )

    floor_slice = noise_floor.broadband_floor_power_psd[env_mask]
    floor_db = float(power_to_db(float(np.sum(floor_slice))))
    floor_flatness = compute_spectral_flatness(floor_slice)

    # Check if the raw temporal minimum is dominated by narrowband tones (sustained music)
    raw_flatness = compute_spectral_flatness(noise_floor.raw_min_power_psd[env_mask])

    metrics: dict[str, float | int | str | bool | None] = {
        "estimated_mid_floor_db": round(floor_db, 2),
        "floor_flatness": round(floor_flatness, 3),
        "raw_min_flatness": round(raw_flatness, 3),
        "sustained_tonal_warning": noise_floor.estimate.sustained_tonal_warning,
    }

    # Strict musical safeguard: must have genuinely broadband inter-harmonic floor (> -60 dBFS & flatness >= 0.35)
    detected = floor_db > -60.0 and floor_flatness >= 0.35
    if not detected:
        return NoiseIndicator(
            id="broadband_environmental",
            label="Possible broadband environmental / fan-like noise",
            detected=False,
            confidence="none",
            evidence=(
                f"Estimated midrange broadband floor (120–4000 Hz) is {floor_db:.1f} dBFS "
                f"(flatness {floor_flatness:.2f}); no prominent stationary broadband bed detected."
            ),
            caveat="Continuous musical playing without pauses can mask moderate room tone or fan noise.",
            metrics=metrics,
        )

    if noise_floor.estimate.sustained_tonal_warning:
        # Downgrade confidence conservatively when sustained tones are present
        confidence: ConfidenceLevel = "low" if floor_db < -45.0 else "moderate"
    elif floor_db > -45.0 and floor_flatness >= 0.50:
        confidence = "high"
    elif floor_db > -54.0 and floor_flatness >= 0.42:
        confidence = "moderate"
    else:
        confidence = "low"

    return NoiseIndicator(
        id="broadband_environmental",
        label="Possible broadband environmental / fan-like noise",
        detected=True,
        confidence=confidence,
        evidence=(
            f"Elevated broadband midrange noise floor across 120–4000 Hz "
            f"(est. floor {floor_db:.1f} dBFS, inter-harmonic flatness {floor_flatness:.2f})."
        ),
        caveat=(
            "Steady room tone, HVAC/fan noise, distant traffic, and dense acoustic reverb tails "
            "share overlapping broadband spectral profiles and cannot be definitively separated "
            "by spectral statistics alone."
        ),
        metrics=metrics,
    )


def _detect_spectral_pattern_notes(
    stft: StftResult,
    noise_floor: NoiseFloorResult,
) -> NoiseIndicator:
    """Report non-stationary tonal or broadband spectral observations conservatively."""
    freqs = stft.freqs
    nyquist = float(stft.sample_rate) / 2.0
    mid_mask = (freqs >= 200.0) & (freqs <= min(6000.0, nyquist * 0.9))

    if not np.any(mid_mask) or stft.power_bins.shape[1] < 8:
        return NoiseIndicator(
            id="spectral_variability",
            label="Background spectral variability pattern",
            detected=False,
            confidence="none",
            evidence="Recording too short to evaluate time-varying background spectral drift.",
            caveat="Time-varying environmental disturbances require longer observation windows.",
        )

    # Compare 15th-percentile vs 40th-percentile broadband floor across frames
    # Use per-frame inter-harmonic flatness to distinguish varying music from varying broadband background
    frame_band = stft.power_bins[mid_mask, :]
    frame_flatness = np.array(
        [compute_spectral_flatness(frame_band[:, t]) for t in range(frame_band.shape[1])],
        dtype=np.float64,
    )
    frame_energy_db = power_to_db(np.sum(frame_band, axis=0))
    assert isinstance(frame_energy_db, np.ndarray)

    # Focus on frames that look broadband-noisy (flatness >= 0.45) rather than tonal musical notes
    noisy_frames = frame_flatness >= 0.45
    noisy_ratio = float(np.mean(noisy_frames))

    if int(np.sum(noisy_frames)) >= 4:
        noisy_energies = frame_energy_db[noisy_frames]
        drift_db = float(np.percentile(noisy_energies, 90) - np.percentile(noisy_energies, 10))
        noisy_level_db = float(np.median(noisy_energies))
    else:
        drift_db = 0.0
        noisy_level_db = -120.0

    detected = (
        noisy_ratio >= 0.15
        and noisy_level_db > -55.0
        and drift_db >= 7.0
    )

    metrics: dict[str, float | int | str | bool | None] = {
        "broadband_frame_ratio": round(noisy_ratio, 3),
        "broadband_drift_db": round(drift_db, 2),
        "broadband_median_db": round(noisy_level_db, 2),
    }

    if not detected:
        return NoiseIndicator(
            id="spectral_variability",
            label="Possible non-stationary environmental disturbance",
            detected=False,
            confidence="none",
            evidence="No strong non-stationary broadband background fluctuation isolated.",
            caveat=(
                "Transient background events (speech, passing traffic, room clicks) overlapping active "
                "musical passages cannot be reliably separated by non-AI spectral statistics alone."
            ),
            metrics=metrics,
        )

    confidence: ConfidenceLevel = "moderate" if drift_db >= 12.0 else "low"
    return NoiseIndicator(
        id="spectral_variability",
        label="Possible non-stationary environmental disturbance",
        detected=True,
        confidence=confidence,
        evidence=(
            f"Time-varying broadband frames ({noisy_ratio * 100:.0f}% of frames, median {noisy_level_db:.1f} dBFS) "
            f"fluctuated by {drift_db:.1f} dB across the recording."
        ),
        caveat=(
            "Fluctuating broadband energy can arise from traffic, wind gusts, or background chatter, "
            "but also from percussive brushes, strumming noise, or breathy playing styles."
        ),
        metrics=metrics,
    )


def detect_noise_indicators(
    samples: np.ndarray,
    stft: StftResult,
    noise_floor: NoiseFloorResult,
    duration_seconds: float,
    is_silent: bool,
) -> list[NoiseIndicator]:
    """Run all conservative spectral noise category detectors."""
    if is_silent:
        return [
            NoiseIndicator(
                id="electrical_hum",
                label="Possible 50/60 Hz electrical hum",
                detected=False,
                confidence="none",
                evidence="Signal is silent or near-silent (< -80 dBFS RMS).",
                caveat="No measurable spectral content to inspect.",
            ),
            NoiseIndicator(
                id="low_freq_rumble",
                label="Possible low-frequency wind / rumble",
                detected=False,
                confidence="none",
                evidence="Signal is silent or near-silent (< -80 dBFS RMS).",
                caveat="No measurable spectral content to inspect.",
            ),
            NoiseIndicator(
                id="broadband_hiss",
                label="Possible broadband hiss",
                detected=False,
                confidence="none",
                evidence="Signal is silent or near-silent (< -80 dBFS RMS).",
                caveat="No measurable spectral content to inspect.",
            ),
            NoiseIndicator(
                id="broadband_environmental",
                label="Possible broadband environmental / fan-like noise",
                detected=False,
                confidence="none",
                evidence="Signal is silent or near-silent (< -80 dBFS RMS).",
                caveat="No measurable spectral content to inspect.",
            ),
        ]

    high_res = _compute_high_res_stft(samples, stft.sample_rate, duration_seconds)
    return [
        _detect_electrical_hum(high_res),
        _detect_low_freq_rumble(stft, high_res, noise_floor),
        _detect_broadband_hiss(stft, noise_floor),
        _detect_broadband_environmental(stft, noise_floor),
        _detect_spectral_pattern_notes(stft, noise_floor),
    ]
