"""Top-level orchestrator for Stage 3 spectral, PSD, and conservative noise analysis."""

from __future__ import annotations

import numpy as np

from app.analysis.classifier import detect_noise_indicators
from app.analysis.noise_estimator import estimate_noise_floor
from app.analysis.spectral import (
    build_psd_comparison,
    build_spectrogram,
    compute_frequency_bands,
    compute_power_stft,
    power_to_db,
)
from app.models.schemas import AnalysisRequest, AnalysisResponse, SignalState

SILENCE_RMS_DBFS_THRESHOLD = -80.0
VERY_SHORT_DURATION_SECONDS = 0.5


def analyze_audio(
    samples: np.ndarray,
    sample_rate: int,
    session_id: str,
    params: AnalysisRequest | None = None,
) -> AnalysisResponse:
    """Analyze native-SR float32 audio for spectral content, noise floor, and indicators."""
    cfg = params or AnalysisRequest()
    audio = samples[:, np.newaxis] if samples.ndim == 1 else samples
    num_frames, num_channels = audio.shape
    duration_seconds = round(float(num_frames) / float(sample_rate), 4)

    # Overall RMS level check for silence / near-silence handling
    rms_power = float(np.mean(audio.astype(np.float64) ** 2))
    rms_dbfs = float(power_to_db(rms_power))
    is_silent = rms_dbfs < SILENCE_RMS_DBFS_THRESHOLD

    signal_state: SignalState
    if is_silent:
        signal_state = "silence_or_near_silence"
    elif duration_seconds < VERY_SHORT_DURATION_SECONDS:
        signal_state = "very_short"
    else:
        signal_state = "normal"

    # Preserve original sample rate for STFT analysis
    stft = compute_power_stft(audio, sample_rate)

    # 1. Conservative silence-free estimated noise floor
    noise_floor_result = estimate_noise_floor(
        stft=stft,
        duration_seconds=duration_seconds,
        is_silent=is_silent,
    )

    # 2. Detected possible noise indicators (distinct from estimated floor)
    indicators = detect_noise_indicators(
        samples=audio,
        stft=stft,
        noise_floor=noise_floor_result,
        duration_seconds=duration_seconds,
        is_silent=is_silent,
    )

    # 3. Frequency-band summaries
    frequency_bands = compute_frequency_bands(
        stft=stft,
        active_power_psd=noise_floor_result.active_power_psd,
        median_power_psd=noise_floor_result.median_power_psd,
        noise_floor_power_psd=noise_floor_result.broadband_floor_power_psd,
        is_silent=is_silent,
    )

    # 4. Bounded PSD comparison curves
    psd = build_psd_comparison(
        stft=stft,
        active_coherent_psd=noise_floor_result.active_coherent_psd,
        median_coherent_psd=noise_floor_result.median_coherent_psd,
        noise_floor_coherent_psd=noise_floor_result.broadband_floor_coherent_psd,
        num_points=128,
    )

    # 5. Bounded quantized spectrogram
    spectrogram = build_spectrogram(
        stft=stft,
        freq_scale=cfg.freq_scale,
        db_min=cfg.db_min,
        db_max=cfg.db_max,
        max_time_bins=cfg.max_time_bins,
        max_freq_bins=cfg.max_freq_bins,
    )

    limitations = [
        "Spectral indicators identify possible noise patterns from signal statistics and cannot guarantee definitive noise classification.",
        "Estimated noise floor uses silence-free Minimum Statistics with inter-harmonic guarding; long sustained musical notes or dense chords without pauses may still bias estimates.",
        "Stage 3 performs read-only diagnostic analysis only — no audio modification or noise reduction has been applied.",
    ]
    if signal_state == "very_short":
        limitations.append(
            "Clip duration is under 0.5 seconds; low-frequency resolution and temporal noise-floor stability are inherently limited."
        )

    return AnalysisResponse(
        session_id=session_id,
        sample_rate=sample_rate,
        channels=num_channels,
        duration_seconds=duration_seconds,
        signal_state=signal_state,
        noise_floor=noise_floor_result.estimate,
        detected_indicators=indicators,
        frequency_bands=frequency_bands,
        psd=psd,
        spectrogram=spectrogram,
        limitations=limitations,
    )
