"""Unit tests for UUID-scoped temporary session store and TTL cleanup."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.exceptions import AudioValidationError, ResourceNotFoundError
from app.models.schemas import AudioMetadata, WaveformPeaks
from app.services.session_store import SessionStore, sanitize_display_name


def _dummy_metadata() -> AudioMetadata:
    return AudioMetadata(
        format="wav",
        codec="pcm_s16le",
        container="wav",
        sample_rate=48000,
        channels=2,
        duration_seconds=1.0,
        frame_count=48000,
        bit_depth=16,
        bitrate_kbps=None,
        file_size_bytes=192044,
        sample_peak_dbfs=-12.0,
        true_peak_dbtp=-11.9,
        rms_dbfs=-15.0,
        integrated_lufs=-14.5,
        loudness_note=None,
    )


def test_sanitize_display_name_strips_traversal_and_unsafe_chars() -> None:
    assert sanitize_display_name("../../etc/passwd") == "passwd"
    assert sanitize_display_name(r"C:\Users\music\my guitar!.wav") == "my guitar_.wav"
    assert sanitize_display_name("   ...   ") == "untitled_audio"
    assert sanitize_display_name(None) == "untitled_audio"


def test_session_store_rejects_invalid_and_traversal_ids(tmp_path: Path) -> None:
    store = SessionStore(temp_root=tmp_path / "sessions", ttl_minutes=60)
    for bad_id in ("../escape", "not-a-uuid", "12345678-1234-1234-1234-123456789012"):
        with pytest.raises(AudioValidationError) as exc_info:
            store.resolve_session_dir(bad_id)
        assert exc_info.value.code == "INVALID_SESSION_ID"


def test_session_store_ttl_cleanup_removes_expired_and_preserves_active(
    tmp_path: Path,
) -> None:
    store = SessionStore(temp_root=tmp_path / "sessions", ttl_minutes=30)

    active_id, active_dir = store.create_session_dir()
    store.save_session(
        session_id=active_id,
        display_name="active.wav",
        metadata=_dummy_metadata(),
        waveform=WaveformPeaks(bucket_count=2, peaks=[0.1, 0.2]),
    )

    expired_id, expired_dir = store.create_session_dir()
    store.save_session(
        session_id=expired_id,
        display_name="expired.wav",
        metadata=_dummy_metadata(),
        waveform=WaveformPeaks(bucket_count=2, peaks=[0.1, 0.2]),
    )

    # Create an orphaned directory without metadata aged past TTL
    orphan_id, orphan_dir = store.create_session_dir()
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=45)).timestamp()
    os.utime(orphan_dir, (old_ts, old_ts))

    # Simulate 20 minutes in the future for active, vs expired manually backdated
    meta_file = expired_dir / "metadata.json"
    expired_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    meta_text = meta_file.read_text(encoding="utf-8")
    current_expires = store.get_session(active_id).expires_at
    # Overwrite expires_at directly on expired_id metadata
    import json

    raw = json.loads(meta_text)
    raw["expires_at"] = expired_time
    meta_file.write_text(json.dumps(raw), encoding="utf-8")

    removed_count = store.cleanup_expired_sessions()
    assert removed_count == 2
    assert active_dir.exists()
    assert not expired_dir.exists()
    assert not orphan_dir.exists()
    assert store.get_session(active_id).expires_at == current_expires

    with pytest.raises(ResourceNotFoundError):
        store.get_session(expired_id)
