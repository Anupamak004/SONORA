"""UUID-scoped temporary session storage with path containment and TTL cleanup."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.exceptions import AudioValidationError, ResourceNotFoundError
from app.models.schemas import (
    AudioMetadata,
    ProcessResponse,
    SessionDetail,
    SessionSummary,
    SupportedAudioFormat,
    WaveformPeaks,
)

logger = logging.getLogger("sonora.session_store")

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_UNSAFE_NAME_CHARS = re.compile(r"[^\w.\- ()\[\]]+")

_MEDIA_TYPES: dict[SupportedAudioFormat, str] = {
    "wav": "audio/wav",
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
}

SOURCE_FILENAME = "source.bin"
DECODED_ORIGINAL_FILENAME = "original_f32.wav"
ORIGINAL_ALIGNED_PLAYABLE_FILENAME = "original_aligned.wav"
PROCESSED_PLAYABLE_FILENAME = "processed.wav"
PROCESSED_F32_FILENAME = "processed_f32.wav"
RESIDUAL_PLAYABLE_FILENAME = "residual.wav"
RESIDUAL_F32_FILENAME = "residual_f32.wav"
PROCESSING_RESULT_FILENAME = "processing_result.json"
METADATA_FILENAME = "metadata.json"


def sanitize_display_name(raw_filename: str | None) -> str:
    """Sanitize user-supplied filename strictly for UI display (never used on disk)."""
    if not raw_filename:
        return "untitled_audio"
    # Extract final path component across both POSIX and Windows separators
    leaf = raw_filename.replace("\\", "/").split("/")[-1].strip()
    leaf = _UNSAFE_NAME_CHARS.sub("_", leaf).strip(". ")
    if not leaf:
        return "untitled_audio"
    return leaf[:120]


class SessionStore:
    """Manages isolated UUID session directories under a fixed temp root."""

    def __init__(self, temp_root: Path, ttl_minutes: int) -> None:
        self._temp_root = temp_root.resolve()
        self._ttl_minutes = ttl_minutes
        self._temp_root.mkdir(parents=True, exist_ok=True)

    @property
    def temp_root(self) -> Path:
        return self._temp_root

    def _validate_session_id(self, session_id: str) -> str:
        if not _UUID_PATTERN.match(session_id):
            raise AudioValidationError(
                code="INVALID_SESSION_ID",
                message="Session identifier format is invalid.",
                status_code=400,
                details={"session_id": session_id},
            )
        return session_id

    def resolve_session_dir(self, session_id: str) -> Path:
        """Resolve a session directory and assert strict containment inside temp_root."""
        valid_id = self._validate_session_id(session_id)
        candidate = (self._temp_root / valid_id).resolve()
        if not candidate.is_relative_to(self._temp_root) or candidate == self._temp_root:
            raise AudioValidationError(
                code="INVALID_SESSION_PATH",
                message="Resolved session path violates storage isolation.",
                status_code=400,
            )
        return candidate

    def create_session_dir(self) -> tuple[str, Path]:
        """Allocate a fresh UUIDv4 session directory."""
        session_id = str(uuid.uuid4())
        session_dir = self.resolve_session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=False)
        return session_id, session_dir

    def remove_dir_quietly(self, session_dir: Path) -> None:
        """Safely remove a session directory within temp_root."""
        resolved = session_dir.resolve()
        if not resolved.is_relative_to(self._temp_root) or resolved == self._temp_root:
            return
        shutil.rmtree(resolved, ignore_errors=True)

    def save_session(
        self,
        session_id: str,
        display_name: str,
        metadata: AudioMetadata,
        waveform: WaveformPeaks,
    ) -> SessionDetail:
        """Persist session metadata atomically and return SessionDetail."""
        session_dir = self.resolve_session_dir(session_id)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=self._ttl_minutes)

        detail = SessionDetail(
            session_id=session_id,
            display_name=display_name,
            created_at=now.isoformat(),
            expires_at=expires.isoformat(),
            metadata=metadata,
            waveform=waveform,
            original_audio_url=f"/api/v1/sessions/{session_id}/audio/original",
        )

        meta_path = session_dir / METADATA_FILENAME
        tmp_path = session_dir / f"{METADATA_FILENAME}.tmp"
        tmp_path.write_text(detail.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_path, meta_path)
        return detail

    def _is_expired(self, expires_at_iso: str, now: datetime | None = None) -> bool:
        ref_now = now or datetime.now(timezone.utc)
        try:
            expires_dt = datetime.fromisoformat(expires_at_iso)
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            return ref_now >= expires_dt
        except ValueError:
            return True

    def _read_metadata(self, session_dir: Path) -> SessionDetail | None:
        meta_path = session_dir / METADATA_FILENAME
        if not meta_path.is_file():
            return None
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
            return SessionDetail.model_validate(raw)
        except Exception:
            return None

    def get_session(self, session_id: str) -> SessionDetail:
        """Load session metadata if present and non-expired."""
        session_dir = self.resolve_session_dir(session_id)
        detail = self._read_metadata(session_dir)
        if detail is None:
            raise ResourceNotFoundError(
                message=f"Audio session '{session_id}' was not found.",
                details={"session_id": session_id},
            )
        if self._is_expired(detail.expires_at):
            self.remove_dir_quietly(session_dir)
            raise ResourceNotFoundError(
                message=f"Audio session '{session_id}' has expired and been cleaned up.",
                details={"session_id": session_id},
            )
        return detail

    def get_original_audio_file(self, session_id: str) -> tuple[Path, str]:
        """Return verified original audio path and HTTP media type for playback."""
        detail = self.get_session(session_id)
        session_dir = self.resolve_session_dir(session_id)
        source_path = (session_dir / SOURCE_FILENAME).resolve()
        if not source_path.is_relative_to(session_dir) or not source_path.is_file():
            raise ResourceNotFoundError(
                message="Original audio file for this session is no longer available.",
                details={"session_id": session_id},
            )
        media_type = _MEDIA_TYPES[detail.metadata.format]
        return source_path, media_type

    def get_decoded_audio_file(self, session_id: str) -> Path:
        """Return verified path to the native sample-rate float32 WAV copy."""
        self.get_session(session_id)
        session_dir = self.resolve_session_dir(session_id)
        decoded_path = (session_dir / DECODED_ORIGINAL_FILENAME).resolve()
        if not decoded_path.is_relative_to(session_dir) or not decoded_path.is_file():
            raise ResourceNotFoundError(
                message="Decoded float32 audio working copy is no longer available.",
                details={"session_id": session_id},
            )
        return decoded_path

    def save_processing_result(self, session_id: str, result: ProcessResponse) -> None:
        """Persist latest processing metadata atomically inside the session directory."""
        session_dir = self.resolve_session_dir(session_id)
        result_path = session_dir / PROCESSING_RESULT_FILENAME
        tmp_path = session_dir / f"{PROCESSING_RESULT_FILENAME}.tmp"
        tmp_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_path, result_path)

    def get_processing_result(self, session_id: str) -> ProcessResponse | None:
        """Load cached processing result if present and output files exist."""
        self.get_session(session_id)
        session_dir = self.resolve_session_dir(session_id)
        result_path = (session_dir / PROCESSING_RESULT_FILENAME).resolve()
        orig_aligned_wav = (session_dir / ORIGINAL_ALIGNED_PLAYABLE_FILENAME).resolve()
        proc_wav = (session_dir / PROCESSED_PLAYABLE_FILENAME).resolve()
        res_wav = (session_dir / RESIDUAL_PLAYABLE_FILENAME).resolve()
        if not (
            result_path.is_relative_to(session_dir)
            and result_path.is_file()
            and orig_aligned_wav.is_file()
            and proc_wav.is_file()
            and res_wav.is_file()
        ):
            return None
        try:
            raw = json.loads(result_path.read_text(encoding="utf-8"))
            return ProcessResponse.model_validate(raw)
        except Exception:
            return None

    def get_original_aligned_audio_file(self, session_id: str) -> Path:
        """Return verified path to sample-aligned 24-bit PCM original WAV for A/B comparison."""
        self.get_session(session_id)
        session_dir = self.resolve_session_dir(session_id)
        target = (session_dir / ORIGINAL_ALIGNED_PLAYABLE_FILENAME).resolve()
        if not target.is_relative_to(session_dir) or not target.is_file():
            raise ResourceNotFoundError(
                message="Sample-aligned original WAV has not been generated for this session yet.",
                details={"session_id": session_id},
            )
        return target

    def get_processed_audio_file(self, session_id: str) -> Path:
        """Return verified path to playable 24-bit PCM processed WAV."""
        self.get_session(session_id)
        session_dir = self.resolve_session_dir(session_id)
        target = (session_dir / PROCESSED_PLAYABLE_FILENAME).resolve()
        if not target.is_relative_to(session_dir) or not target.is_file():
            raise ResourceNotFoundError(
                message="Processed audio has not been generated for this session yet.",
                details={"session_id": session_id},
            )
        return target

    def get_residual_audio_file(self, session_id: str) -> Path:
        """Return verified path to playable 24-bit PCM unnormalized residual WAV."""
        self.get_session(session_id)
        session_dir = self.resolve_session_dir(session_id)
        target = (session_dir / RESIDUAL_PLAYABLE_FILENAME).resolve()
        if not target.is_relative_to(session_dir) or not target.is_file():
            raise ResourceNotFoundError(
                message="Residual audio has not been generated for this session yet.",
                details={"session_id": session_id},
            )
        return target

    def list_sessions(self, limit: int = 20) -> list[SessionSummary]:
        """Return recent non-expired sessions sorted newest first."""
        if not self._temp_root.is_dir():
            return []

        now = datetime.now(timezone.utc)
        summaries: list[SessionSummary] = []

        for entry in self._temp_root.iterdir():
            if not entry.is_dir() or not _UUID_PATTERN.match(entry.name):
                continue
            detail = self._read_metadata(entry)
            if detail is None:
                continue
            if self._is_expired(detail.expires_at, now=now):
                self.remove_dir_quietly(entry)
                continue
            summaries.append(
                SessionSummary(
                    session_id=detail.session_id,
                    display_name=detail.display_name,
                    created_at=detail.created_at,
                    expires_at=detail.expires_at,
                    format=detail.metadata.format,
                    duration_seconds=detail.metadata.duration_seconds,
                    sample_rate=detail.metadata.sample_rate,
                    channels=detail.metadata.channels,
                )
            )

        summaries.sort(key=lambda item: item.created_at, reverse=True)
        return summaries[: max(1, min(limit, 100))]

    def delete_session(self, session_id: str) -> None:
        """Delete a session directory immediately."""
        session_dir = self.resolve_session_dir(session_id)
        if not session_dir.exists():
            raise ResourceNotFoundError(
                message=f"Audio session '{session_id}' was not found.",
                details={"session_id": session_id},
            )
        self.remove_dir_quietly(session_dir)

    def cleanup_expired_sessions(self, now: datetime | None = None) -> int:
        """Delete expired sessions and orphaned partial upload directories."""
        if not self._temp_root.is_dir():
            return 0

        ref_now = now or datetime.now(timezone.utc)
        removed = 0

        for entry in self._temp_root.iterdir():
            if not entry.is_dir() or not _UUID_PATTERN.match(entry.name):
                continue

            detail = self._read_metadata(entry)
            if detail is not None:
                if self._is_expired(detail.expires_at, now=ref_now):
                    self.remove_dir_quietly(entry)
                    removed += 1
            else:
                # Orphaned partial directory without metadata: clean if older than TTL
                try:
                    mtime = datetime.fromtimestamp(
                        entry.stat().st_mtime, tz=timezone.utc
                    )
                    if ref_now - mtime >= timedelta(minutes=self._ttl_minutes):
                        self.remove_dir_quietly(entry)
                        removed += 1
                except OSError:
                    pass

        if removed > 0:
            logger.info("Cleaned up %d expired temporary audio session(s).", removed)
        return removed
