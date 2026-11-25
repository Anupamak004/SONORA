"""API routes for Stage 4 Precision Musical DSP processing and playable outputs."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import APIRouter, Body, Depends
from fastapi.responses import FileResponse

from app.api.sessions import get_session_store
from app.audio.loudness import AudioLevelMetrics
from app.audio.waveform import compute_waveform_peaks
from app.core.exceptions import AudioValidationError, ResourceNotFoundError, SonoraError
from app.dsp.pipeline import RESIDUAL_DISCLOSURE_TEXT, process_audio_pipeline
from app.models.schemas import LevelSummary, ProcessRequest, ProcessResponse
from app.services.session_store import (
    ORIGINAL_ALIGNED_PLAYABLE_FILENAME,
    PROCESSED_F32_FILENAME,
    PROCESSED_PLAYABLE_FILENAME,
    RESIDUAL_F32_FILENAME,
    RESIDUAL_PLAYABLE_FILENAME,
    SessionStore,
)

router = APIRouter(prefix="/sessions", tags=["processing"])


def _hash_request(request: ProcessRequest) -> str:
    canonical = request.model_dump_json()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _to_level_summary(metrics: AudioLevelMetrics) -> LevelSummary:
    return LevelSummary(
        sample_peak_dbfs=metrics.sample_peak_dbfs,
        true_peak_dbtp=metrics.true_peak_dbtp,
        rms_dbfs=metrics.rms_dbfs,
        integrated_lufs=metrics.integrated_lufs,
        loudness_note=metrics.loudness_note,
    )


def _atomic_write_wav(
    target_path: Path, samples: np.ndarray, sample_rate: int, subtype: str
) -> None:
    tmp_path = target_path.with_suffix(".tmp.wav")
    sf.write(str(tmp_path), samples, sample_rate, subtype=subtype, format="WAV")
    os.replace(tmp_path, target_path)


def _execute_processing(
    decoded_wav_path: Path,
    session_dir: Path,
    session_id: str,
    request: ProcessRequest,
    params_hash: str,
) -> ProcessResponse:
    """Load untouched original float32 audio, run DSP pipeline, and persist playable outputs."""
    try:
        original, sample_rate = sf.read(
            str(decoded_wav_path), dtype="float32", always_2d=True
        )
    except (sf.LibsndfileError, RuntimeError, OSError) as exc:
        raise AudioValidationError(
            code="PROCESSING_LOAD_FAILED",
            message="Failed to read decoded audio working copy for processing.",
            details={"reason": str(exc)},
        ) from exc

    output = process_audio_pipeline(original, int(sample_rate), request)

    # Persist exact float32 working copies + universally playable 24-bit PCM WAVs.
    # Also write original_aligned.wav (PCM_24 from decoded float32) so MP3/FLAC/WAV
    # A/B comparison and live Dry/Wet blending share zero codec priming delay and
    # identical sample counts across Original, Processed, and Residual streams.
    # Original files (source.bin, original_f32.wav) are never modified.
    _atomic_write_wav(
        session_dir / ORIGINAL_ALIGNED_PLAYABLE_FILENAME,
        np.clip(original, -1.0, 1.0),
        output.sample_rate,
        subtype="PCM_24",
    )
    _atomic_write_wav(
        session_dir / PROCESSED_F32_FILENAME,
        output.processed,
        output.sample_rate,
        subtype="FLOAT",
    )
    _atomic_write_wav(
        session_dir / PROCESSED_PLAYABLE_FILENAME,
        np.clip(output.processed, -1.0, 1.0),
        output.sample_rate,
        subtype="PCM_24",
    )
    _atomic_write_wav(
        session_dir / RESIDUAL_F32_FILENAME,
        output.residual,
        output.sample_rate,
        subtype="FLOAT",
    )
    # Residual is NEVER normalized; only clipped to WAV full-scale bounds if needed
    _atomic_write_wav(
        session_dir / RESIDUAL_PLAYABLE_FILENAME,
        np.clip(output.residual, -1.0, 1.0),
        output.sample_rate,
        subtype="PCM_24",
    )

    processed_waveform = compute_waveform_peaks(output.processed, target_buckets=1200)
    residual_waveform = compute_waveform_peaks(output.residual, target_buckets=1200)

    num_frames, num_channels = output.processed.shape
    duration_seconds = round(float(num_frames) / float(output.sample_rate), 4)

    return ProcessResponse(
        session_id=session_id,
        status="completed",
        processing_mode=output.processing_mode,
        cached=False,
        params_hash=params_hash,
        processing_time_ms=output.processing_time_ms,
        sample_rate=output.sample_rate,
        channels=num_channels,
        frame_count=num_frames,
        duration_seconds=duration_seconds,
        settings_applied=request,
        actions=output.actions,
        original_levels=_to_level_summary(output.original_levels),
        processed_levels=_to_level_summary(output.processed_levels),
        residual_levels=_to_level_summary(output.residual_levels),
        loudness_offset_db=output.loudness_offset_db,
        processed_waveform=processed_waveform,
        residual_waveform=residual_waveform,
        original_aligned_audio_url=f"/api/v1/sessions/{session_id}/audio/original-aligned?v={params_hash}",
        processed_audio_url=f"/api/v1/sessions/{session_id}/audio/processed?v={params_hash}",
        residual_audio_url=f"/api/v1/sessions/{session_id}/audio/residual?v={params_hash}",
        residual_disclosure=RESIDUAL_DISCLOSURE_TEXT,
    )


@router.post("/{session_id}/process", response_model=ProcessResponse)
async def process_session_audio(
    session_id: str,
    request: ProcessRequest | None = Body(default=None),
    store: SessionStore = Depends(get_session_store),
) -> ProcessResponse:
    """Process an uploaded recording using Precision Musical DSP and store playable outputs."""
    decoded_path = store.get_decoded_audio_file(session_id)
    session_dir = store.resolve_session_dir(session_id)
    effective_request = request or ProcessRequest()

    # Never silently substitute DSP output for an explicitly selected AI engine.
    # AudioSep remains unavailable until a verified local adapter and model runtime
    # are installed and registered.
    if effective_request.engine != "precision_musical_dsp":
        raise SonoraError(
            code="AI_ENGINE_UNAVAILABLE",
            message=(
                "AudioSep is not installed or enabled in this SONORA build. "
                "Choose Precision Musical DSP or install a verified AI engine."
            ),
            status_code=503,
            details={
                "requested_engine": effective_request.engine,
                "fallback_applied": False,
            },
        )

    params_hash = _hash_request(effective_request)

    # Return cached result immediately when identical settings were already processed
    existing = store.get_processing_result(session_id)
    if existing is not None and existing.params_hash == params_hash:
        return existing.model_copy(update={"cached": True})

    result = await asyncio.to_thread(
        _execute_processing,
        decoded_path,
        session_dir,
        session_id,
        effective_request,
        params_hash,
    )
    store.save_processing_result(session_id, result)
    return result


@router.get("/{session_id}/process", response_model=ProcessResponse)
async def get_session_processing_result(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> ProcessResponse:
    """Retrieve the latest completed processing result for a session."""
    result = store.get_processing_result(session_id)
    if result is None:
        raise ResourceNotFoundError(
            message="This session has not been processed yet.",
            details={"session_id": session_id},
        )
    return result


@router.get("/{session_id}/audio/original-aligned")
async def stream_original_aligned_audio(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> FileResponse:
    """Stream sample-aligned 24-bit PCM original WAV with HTTP Range support for A/B comparison."""
    target = store.get_original_aligned_audio_file(session_id)
    return FileResponse(
        path=target,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{session_id}/audio/processed")
async def stream_processed_audio(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> FileResponse:
    """Stream the processed WAV recording with native HTTP Range support."""
    target = store.get_processed_audio_file(session_id)
    return FileResponse(
        path=target,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{session_id}/audio/residual")
async def stream_residual_audio(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> FileResponse:
    """Stream the unnormalized sample-aligned residual (original - final_processed) WAV."""
    target = store.get_residual_audio_file(session_id)
    return FileResponse(
        path=target,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )
