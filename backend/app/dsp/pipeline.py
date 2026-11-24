"""Top-level Precision Musical DSP offline processing pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from app.audio.loudness import AudioLevelMetrics, measure_audio_levels
from app.dsp.broadband import apply_musical_broadband_suppression
from app.dsp.filters import (
    apply_conservative_hpf,
    apply_pitch_safe_hum_notch,
    remove_dc_offset_if_present,
)
from app.dsp.limiter import apply_optional_true_peak_limiter
from app.models.schemas import ProcessingActions, ProcessingMode, ProcessRequest

SILENCE_RMS_THRESHOLD = 1e-4  # -80 dBFS
RESIDUAL_DISCLOSURE_TEXT = (
    "Processing Difference / Residual is computed sample-aligned as "
    "original[n] - final_processed[n] after all processing stages (including any "
    "enabled limiter) with no independent normalization. It represents all differences "
    "introduced by processing and may contain some musical instrument content — it is "
    "a fidelity diagnostic, not pure isolated noise."
)


@dataclass(frozen=True)
class PipelineOutput:
    """Complete deterministic DSP processing result with exact sample-aligned residual."""

    processed: np.ndarray  # float32, shape (frames, channels)
    residual: np.ndarray  # float32, shape (frames, channels), exact original - final_processed
    sample_rate: int
    processing_mode: ProcessingMode
    actions: ProcessingActions
    original_levels: AudioLevelMetrics
    processed_levels: AudioLevelMetrics
    residual_levels: AudioLevelMetrics
    loudness_offset_db: float | None
    processing_time_ms: float


def process_audio_pipeline(
    samples: np.ndarray,
    sample_rate: int,
    request: ProcessRequest,
) -> PipelineOutput:
    """Execute the conservative Precision Musical DSP pipeline on native-SR float32 audio.

    Guarantees:
    - Never mutates the input `samples` array.
    - Preserves exact sample count, sample rate, and channel layout.
    - Computes exact sample-aligned `residual = original - final_processed` AFTER all
      output-altering operations (including any optional limiter).
    """
    t0 = time.perf_counter()
    original = np.ascontiguousarray(
        samples[:, np.newaxis] if samples.ndim == 1 else samples,
        dtype=np.float32,
    )
    num_frames, num_channels = original.shape

    original_levels = measure_audio_levels(original, sample_rate)
    notes: list[str] = []

    # 1. Explicit user bypass
    if request.bypass or request.dry_wet_mix <= 0.0:
        final_processed = original.copy()
        residual = np.zeros_like(original, dtype=np.float32)
        notes.append(
            "Processing bypassed by user control; output is bit-identical to original audio."
            if request.bypass
            else "Dry/wet mix set to 0%; output is bit-identical to original audio."
        )
        return _finalize_output(
            original=original,
            final_processed=final_processed,
            residual=residual,
            sample_rate=sample_rate,
            mode="bypassed",
            original_levels=original_levels,
            actions=ProcessingActions(
                dc_offset_removed=False,
                hpf_applied=False,
                hpf_cutoff_hz=None,
                hum_notches_applied=False,
                hum_notched_frequencies_hz=[],
                broadband_applied_channels=[],
                broadband_skipped_clean_channels=list(range(1, num_channels + 1)),
                limiter_engaged=False,
                limiter_gain_reduction_db=0.0,
                notes=notes,
            ),
            t0=t0,
        )

    # 2. Silence / near-silence guard
    rms_lin = float(np.sqrt(np.mean(original.astype(np.float64) ** 2))) if original.size else 0.0
    if rms_lin < SILENCE_RMS_THRESHOLD or num_frames < 64:
        final_processed = original.copy()
        residual = np.zeros_like(original, dtype=np.float32)
        notes.append(
            "Recording is silent, near-silent (< -80 dBFS RMS), or too short; processing bypassed automatically."
        )
        return _finalize_output(
            original=original,
            final_processed=final_processed,
            residual=residual,
            sample_rate=sample_rate,
            mode="bypassed_clean_or_silent",
            original_levels=original_levels,
            actions=ProcessingActions(
                dc_offset_removed=False,
                hpf_applied=False,
                hpf_cutoff_hz=None,
                hum_notches_applied=False,
                hum_notched_frequencies_hz=[],
                broadband_applied_channels=[],
                broadband_skipped_clean_channels=list(range(1, num_channels + 1)),
                limiter_engaged=False,
                limiter_gain_reduction_db=0.0,
                notes=notes,
            ),
            t0=t0,
        )

    # 3. Stage 1: Conditional DC offset removal (only if measurable offset present)
    dc_res = remove_dc_offset_if_present(original, sample_rate)
    working = dc_res.audio
    if dc_res.applied:
        notes.append(
            f"Removed measurable DC offset (max channel mean {dc_res.max_offset_measured:.5f})."
        )

    # 4. Stage 2: Optional conservative high-pass filter (only if user enabled)
    hpf_applied = False
    hpf_cutoff_used: float | None = None
    if request.hpf_enabled:
        hpf_res = apply_conservative_hpf(working, sample_rate, request.hpf_cutoff_hz)
        working = hpf_res.audio
        hpf_applied = hpf_res.applied
        hpf_cutoff_used = hpf_res.cutoff_hz
        if hpf_res.note:
            notes.append(hpf_res.note)

    # 5. Stage 3: Evidence-gated, pitch-safe 50/60 Hz hum removal (per channel)
    hum_applied = False
    hum_freqs_flat: list[float] = []
    if request.hum_reduction_enabled:
        hum_res = apply_pitch_safe_hum_notch(working, sample_rate, request.strength)
        working = hum_res.audio
        hum_applied = hum_res.applied
        for ch_freqs in hum_res.notched_frequencies_by_channel:
            for f in ch_freqs:
                if f not in hum_freqs_flat:
                    hum_freqs_flat.append(f)
        hum_freqs_flat.sort()
        notes.extend(hum_res.notes)

    # 6. Stage 4: Conservative musical broadband Wiener suppression (per channel)
    bb_res = apply_musical_broadband_suppression(working, sample_rate, request.strength)
    working = bb_res.audio
    notes.extend(bb_res.notes)

    # 7. Stage 5: Dry/Wet parallel blend (exact sample alignment)
    wet = float(request.dry_wet_mix)
    if wet < 1.0:
        blended = (
            wet * working.astype(np.float64) + (1.0 - wet) * original.astype(np.float64)
        ).astype(np.float32)
    else:
        blended = working

    # 8. Stage 6: Optional / conditional true-peak limiter (only when explicitly enabled & needed)
    limiter_engaged = False
    limiter_gr_db = 0.0
    if request.enable_limiter:
        lim_res = apply_optional_true_peak_limiter(
            blended, sample_rate, ceiling_dbtp=request.limiter_ceiling_dbtp
        )
        final_processed = lim_res.audio
        limiter_engaged = lim_res.engaged
        limiter_gr_db = lim_res.gain_reduction_db
        if limiter_engaged:
            notes.append(
                f"Optional true-peak limiter engaged at {request.limiter_ceiling_dbtp:.1f} dBTP "
                f"(max gain reduction {limiter_gr_db:.2f} dB)."
            )
        else:
            notes.append(
                f"Optional true-peak limiter enabled but idle (signal already below {request.limiter_ceiling_dbtp:.1f} dBTP)."
            )
    else:
        final_processed = blended

    # Ensure finite float32 output with exact original shape
    assert final_processed.shape == original.shape
    final_processed = np.nan_to_num(final_processed, nan=0.0, posinf=0.0, neginf=0.0).astype(
        np.float32
    )

    # 9. Stage 7 (POST-ALL-OPERATIONS): Exact sample-aligned residual (unnormalized!)
    residual = (
        original.astype(np.float64) - final_processed.astype(np.float64)
    ).astype(np.float32)

    # Determine honest processing_mode
    any_dsp_engaged = (
        dc_res.applied
        or hpf_applied
        or hum_applied
        or len(bb_res.applied_channels) > 0
        or limiter_engaged
    )
    residual_rms = float(np.sqrt(np.mean(residual.astype(np.float64) ** 2)))
    orig_rms = max(rms_lin, 1e-12)
    rel_change = residual_rms / orig_rms

    mode: ProcessingMode
    if not any_dsp_engaged or residual_rms < 1e-7:
        mode = "bypassed_clean_or_silent"
        notes.append(
            "Recording appeared already clean with no confirmed noise requiring suppression; output left effectively unchanged."
        )
    elif rel_change < 0.015 and not hum_applied and not hpf_applied:
        mode = "minimal"
        notes.append(
            "Only minimal processing was applied to preserve natural instrument timbre and dynamics."
        )
    else:
        mode = "applied"

    actions = ProcessingActions(
        dc_offset_removed=dc_res.applied,
        hpf_applied=hpf_applied,
        hpf_cutoff_hz=hpf_cutoff_used,
        hum_notches_applied=hum_applied,
        hum_notched_frequencies_hz=hum_freqs_flat,
        broadband_applied_channels=bb_res.applied_channels,
        broadband_skipped_clean_channels=bb_res.skipped_clean_channels,
        limiter_engaged=limiter_engaged,
        limiter_gain_reduction_db=limiter_gr_db,
        notes=notes,
    )

    return _finalize_output(
        original=original,
        final_processed=final_processed,
        residual=residual,
        sample_rate=sample_rate,
        mode=mode,
        original_levels=original_levels,
        actions=actions,
        t0=t0,
    )


def _finalize_output(
    *,
    original: np.ndarray,
    final_processed: np.ndarray,
    residual: np.ndarray,
    sample_rate: int,
    mode: ProcessingMode,
    original_levels: AudioLevelMetrics,
    actions: ProcessingActions,
    t0: float,
) -> PipelineOutput:
    processed_levels = measure_audio_levels(final_processed, sample_rate)
    residual_levels = measure_audio_levels(residual, sample_rate)

    loudness_offset_db: float | None = None
    if (
        original_levels.integrated_lufs is not None
        and processed_levels.integrated_lufs is not None
    ):
        loudness_offset_db = round(
            original_levels.integrated_lufs - processed_levels.integrated_lufs, 2
        )

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return PipelineOutput(
        processed=final_processed,
        residual=residual,
        sample_rate=sample_rate,
        processing_mode=mode,
        actions=actions,
        original_levels=original_levels,
        processed_levels=processed_levels,
        residual_levels=residual_levels,
        loudness_offset_db=loudness_offset_db,
        processing_time_ms=elapsed_ms,
    )
