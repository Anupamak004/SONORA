"""Audio session upload, metadata inspection, playback streaming, and cleanup routes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import soundfile as sf
from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.audio.loader import decode_audio_float32
from app.audio.loudness import measure_audio_levels
from app.audio.validator import validate_audio_file
from app.audio.waveform import compute_waveform_peaks
from app.core.config import Settings, get_settings
from app.core.exceptions import AudioValidationError, PayloadTooLargeError
from app.models.schemas import (
    AudioMetadata,
    SessionDetail,
    SessionsListResponse,
    WaveformPeaks,
)
from app.services.session_store import (
    DECODED_ORIGINAL_FILENAME,
    SOURCE_FILENAME,
    SessionStore,
    sanitize_display_name,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])

UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MiB streaming chunks


def get_session_store(settings: Settings = Depends(get_settings)) -> SessionStore:
    """Provide a SessionStore scoped to configured temp_dir and TTL."""
    return SessionStore(
        temp_root=settings.resolved_temp_dir,
        ttl_minutes=settings.session_ttl_minutes,
    )


def _validate_decode_and_analyze(
    source_path: Path,
    session_dir: Path,
    settings: Settings,
) -> tuple[AudioMetadata, WaveformPeaks]:
    """Run blocking validation, native-SR float32 decode, level/LUFS, and peak extraction."""
    probe = validate_audio_file(source_path, settings)
    samples, sample_rate = decode_audio_float32(source_path, probe, settings)

    actual_frames, actual_channels = samples.shape
    actual_duration = round(float(actual_frames) / float(sample_rate), 4)

    # Persist native sample-rate float32 working copy for subsequent restoration stages
    decoded_path = session_dir / DECODED_ORIGINAL_FILENAME
    sf.write(str(decoded_path), samples, sample_rate, subtype="FLOAT", format="WAV")

    levels = measure_audio_levels(samples, sample_rate)
    waveform = compute_waveform_peaks(samples, target_buckets=1200)

    metadata = AudioMetadata(
        format=probe.format,
        codec=probe.codec,
        container=probe.container,
        sample_rate=sample_rate,
        channels=actual_channels,
        duration_seconds=actual_duration,
        frame_count=actual_frames,
        bit_depth=probe.bit_depth,
        bitrate_kbps=probe.bitrate_kbps,
        file_size_bytes=probe.file_size_bytes,
        sample_peak_dbfs=levels.sample_peak_dbfs,
        true_peak_dbtp=levels.true_peak_dbtp,
        rms_dbfs=levels.rms_dbfs,
        integrated_lufs=levels.integrated_lufs,
        loudness_note=levels.loudness_note,
    )
    return metadata, waveform


@router.post(
    "/upload",
    response_model=SessionDetail,
    status_code=status.HTTP_201_CREATED,
)
async def upload_audio(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_session_store),
) -> SessionDetail:
    """Stream, validate, decode (float32 native SR), analyze, and store an audio file."""
    session_id, session_dir = store.create_session_dir()
    source_path = session_dir / SOURCE_FILENAME
    display_name = sanitize_display_name(file.filename)

    try:
        total_written = 0
        with source_path.open("wb") as out_fh:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_written += len(chunk)
                if total_written > settings.max_upload_bytes:
                    raise PayloadTooLargeError(
                        code="FILE_TOO_LARGE",
                        message=(
                            f"Uploaded file exceeds the maximum allowed size of "
                            f"{settings.max_upload_mb} MB."
                        ),
                        details={
                            "max_upload_mb": settings.max_upload_mb,
                            "received_bytes": total_written,
                        },
                    )
                out_fh.write(chunk)

        if total_written == 0:
            raise AudioValidationError(
                code="EMPTY_FILE",
                message="Uploaded file is empty (0 bytes).",
            )

        metadata, waveform = await asyncio.to_thread(
            _validate_decode_and_analyze, source_path, session_dir, settings
        )

        return store.save_session(
            session_id=session_id,
            display_name=display_name,
            metadata=metadata,
            waveform=waveform,
        )
    except Exception:
        store.remove_dir_quietly(session_dir)
        raise
    finally:
        await file.close()


@router.get("", response_model=SessionsListResponse)
async def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    store: SessionStore = Depends(get_session_store),
) -> SessionsListResponse:
    """Return active non-expired audio sessions."""
    return SessionsListResponse(sessions=store.list_sessions(limit=limit))


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> SessionDetail:
    """Fetch full metadata and waveform peaks for a specific session."""
    return store.get_session(session_id)


@router.get("/{session_id}/audio/original")
async def stream_original_audio(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> FileResponse:
    """Stream the validated original recording with Range request support."""
    source_path, media_type = store.get_original_audio_file(session_id)
    return FileResponse(
        path=source_path,
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> Response:
    """Delete an audio session and remove all associated temporary files."""
    store.delete_session(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
