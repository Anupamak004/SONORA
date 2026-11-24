"""API integration tests for Stage 2 audio ingestion, validation, playback, and cleanup."""

from __future__ import annotations

import io
import math
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _build_audio_bytes(
    fmt: str = "WAV",
    subtype: str = "PCM_24",
    sample_rate: int = 48000,
    duration_s: float = 1.0,
    channels: int = 2,
) -> bytes:
    t = np.arange(int(round(duration_s * sample_rate)), dtype=np.float64) / sample_rate
    # Guitar-like harmonic triad (A3=220, C#4=277.18, E4=329.63)
    mono = (
        0.2 * np.sin(2.0 * math.pi * 220.0 * t)
        + 0.15 * np.sin(2.0 * math.pi * 277.18 * t)
        + 0.1 * np.sin(2.0 * math.pi * 329.63 * t)
    ).astype(np.float32)
    samples = np.column_stack([mono] * channels)
    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, subtype=subtype, format=fmt)
    return buf.getvalue()


def test_upload_valid_wav_inspect_stream_and_delete(
    client: TestClient, test_settings: Settings
) -> None:
    wav_bytes = _build_audio_bytes(
        fmt="WAV", subtype="PCM_24", sample_rate=48000, duration_s=1.0, channels=2
    )
    resp = client.post(
        "/api/v1/sessions/upload",
        files={"file": ("../../Studio Guitar Take 1.wav", wav_bytes, "audio/wav")},
    )
    assert resp.status_code == 201
    data = resp.json()

    session_id = data["session_id"]
    # Path traversal stripped from display name
    assert data["display_name"] == "Studio Guitar Take 1.wav"
    assert data["metadata"]["format"] == "wav"
    assert data["metadata"]["sample_rate"] == 48000
    assert data["metadata"]["channels"] == 2
    assert data["metadata"]["bit_depth"] == 24
    assert abs(data["metadata"]["duration_seconds"] - 1.0) < 0.01
    assert data["metadata"]["sample_peak_dbfs"] is not None
    assert data["metadata"]["true_peak_dbtp"] is not None
    assert data["metadata"]["integrated_lufs"] is not None
    assert data["waveform"]["bucket_count"] > 0

    # List & Get endpoints
    list_resp = client.get("/api/v1/sessions")
    assert list_resp.status_code == 200
    assert any(s["session_id"] == session_id for s in list_resp.json()["sessions"])

    get_resp = client.get(f"/api/v1/sessions/{session_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["session_id"] == session_id

    # Stream original audio (full + Range request for WaveSurfer seeking)
    audio_resp = client.get(f"/api/v1/sessions/{session_id}/audio/original")
    assert audio_resp.status_code == 200
    assert audio_resp.headers["content-type"] == "audio/wav"
    assert len(audio_resp.content) == len(wav_bytes)

    range_resp = client.get(
        f"/api/v1/sessions/{session_id}/audio/original",
        headers={"Range": "bytes=0-1023"},
    )
    assert range_resp.status_code == 206
    assert len(range_resp.content) == 1024

    # Delete removes session directory cleanly from disk
    session_dir = test_settings.resolved_temp_dir / session_id
    assert session_dir.is_dir()

    del_resp = client.delete(f"/api/v1/sessions/{session_id}")
    assert del_resp.status_code == 204
    assert not session_dir.exists()
    assert client.get(f"/api/v1/sessions/{session_id}").status_code == 404


def test_upload_valid_flac_preserves_native_sample_rate(client: TestClient) -> None:
    flac_bytes = _build_audio_bytes(
        fmt="FLAC", subtype="PCM_16", sample_rate=44100, duration_s=0.8, channels=1
    )
    resp = client.post(
        "/api/v1/sessions/upload",
        files={"file": ("violin_phrase.flac", flac_bytes, "audio/flac")},
    )
    assert resp.status_code == 201
    meta = resp.json()["metadata"]
    assert meta["format"] == "flac"
    assert meta["codec"] == "flac"
    assert meta["sample_rate"] == 44100
    assert meta["channels"] == 1
    assert meta["bit_depth"] == 16


def test_upload_valid_mp3_when_ffmpeg_available(
    client: TestClient, test_settings: Settings, tmp_path: Path
) -> None:
    ffmpeg_path = test_settings.resolved_ffmpeg_path
    if not ffmpeg_path:
        pytest.skip("FFmpeg not available in environment")

    wav_file = tmp_path / "src.wav"
    mp3_file = tmp_path / "src.mp3"
    wav_file.write_bytes(
        _build_audio_bytes(
            fmt="WAV", subtype="PCM_16", sample_rate=44100, duration_s=1.0, channels=2
        )
    )
    subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-v",
            "error",
            "-i",
            str(wav_file),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(mp3_file),
        ],
        shell=False,
        check=True,
        timeout=15,
    )

    resp = client.post(
        "/api/v1/sessions/upload",
        files={"file": ("piano_demo.mp3", mp3_file.read_bytes(), "audio/mpeg")},
    )
    assert resp.status_code == 201
    meta = resp.json()["metadata"]
    assert meta["format"] == "mp3"
    assert meta["codec"] == "mp3"
    assert meta["sample_rate"] == 44100
    assert meta["channels"] == 2
    assert meta["bit_depth"] is None
    assert meta["bitrate_kbps"] is not None
    assert meta["integrated_lufs"] is not None


def test_upload_rejects_malformed_file_and_cleans_up_temp_dir(
    client: TestClient, test_settings: Settings
) -> None:
    resp = client.post(
        "/api/v1/sessions/upload",
        files={"file": ("spoofed.wav", b"not real audio data at all", "audio/wav")},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "UNSUPPORTED_AUDIO_FORMAT"

    # Verify zero leftover session directories
    remaining = list(test_settings.resolved_temp_dir.iterdir())
    assert remaining == []


def test_upload_rejects_oversized_file_and_cleans_up(tmp_path: Path) -> None:
    cfg = Settings(
        env="test",
        temp_dir=str(tmp_path / "tiny_limit_sessions"),
        max_upload_mb=1,
    )
    app = create_app(settings=cfg)
    oversized_payload = b"RIFF" + (b"\x00" * (1024 * 1024 + 512))

    with TestClient(app) as local_client:
        resp = local_client.post(
            "/api/v1/sessions/upload",
            files={"file": ("huge.wav", oversized_payload, "audio/wav")},
        )
        assert resp.status_code == 413
        assert resp.json()["error"]["code"] == "FILE_TOO_LARGE"

    assert list(cfg.resolved_temp_dir.iterdir()) == []


def test_invalid_session_id_returns_400_envelope(client: TestClient) -> None:
    resp = client.get("/api/v1/sessions/not-a-valid-uuid")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_SESSION_ID"
