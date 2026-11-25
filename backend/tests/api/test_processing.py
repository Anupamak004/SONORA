"""API integration tests for Stage 4 processing, caching, Range playback, and residual audio."""

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


def _upload_noisy_stereo_wav(
    client: TestClient, sample_rate: int = 48000, duration_s: float = 1.5
) -> tuple[str, np.ndarray]:
    n = int(round(duration_s * sample_rate))
    t = np.arange(n, dtype=np.float64) / sample_rate
    music = (
        0.22 * np.sin(2.0 * math.pi * 220.0 * t)
        + 0.14 * np.sin(2.0 * math.pi * 330.0 * t)
    )
    hum = (
        0.04 * np.sin(2.0 * math.pi * 60.0 * t)
        + 0.02 * np.sin(2.0 * math.pi * 120.0 * t)
        + 0.012 * np.sin(2.0 * math.pi * 180.0 * t)
    )
    mono = (music + hum).astype(np.float32)
    stereo = np.column_stack([mono, mono])

    buf = io.BytesIO()
    sf.write(buf, stereo, sample_rate, subtype="PCM_24", format="WAV")
    resp = client.post(
        "/api/v1/sessions/upload",
        files={"file": ("guitar_with_60hz_hum.wav", buf.getvalue(), "audio/wav")},
    )
    assert resp.status_code == 201
    return resp.json()["session_id"], stereo


def test_process_endpoint_produces_playable_processed_and_residual_audio_with_range(
    client: TestClient, test_settings: Settings
) -> None:
    session_id, _ = _upload_noisy_stereo_wav(client, sample_rate=48000, duration_s=1.5)

    # Before processing, GET /process and /audio/processed return 404
    assert client.get(f"/api/v1/sessions/{session_id}/process").status_code == 404
    assert client.get(f"/api/v1/sessions/{session_id}/audio/processed").status_code == 404

    orig_bytes_before = (
        test_settings.resolved_temp_dir / session_id / "source.bin"
    ).read_bytes()

    # Run processing
    proc_resp = client.post(
        f"/api/v1/sessions/{session_id}/process",
        json={
            "strength": 0.6,
            "hum_reduction_enabled": True,
            "hpf_enabled": False,
            "dry_wet_mix": 1.0,
            "bypass": False,
            "enable_limiter": False,
        },
    )
    assert proc_resp.status_code == 200
    body = proc_resp.json()

    assert body["session_id"] == session_id
    assert body["status"] == "completed"
    assert body["processing_mode"] == "applied"
    assert body["cached"] is False
    assert body["sample_rate"] == 48000
    assert body["channels"] == 2
    assert body["frame_count"] == 72000
    assert body["actions"]["hum_notches_applied"] is True
    assert body["processed_waveform"]["bucket_count"] > 0
    assert body["residual_waveform"]["bucket_count"] > 0
    assert "original[n] - final_processed[n]" in body["residual_disclosure"]

    # Original file must remain strictly untouched
    orig_bytes_after = (
        test_settings.resolved_temp_dir / session_id / "source.bin"
    ).read_bytes()
    assert orig_bytes_before == orig_bytes_after

    # Duplicate request with identical settings hits cache
    cached_resp = client.post(
        f"/api/v1/sessions/{session_id}/process",
        json={
            "strength": 0.6,
            "hum_reduction_enabled": True,
            "hpf_enabled": False,
            "dry_wet_mix": 1.0,
            "bypass": False,
            "enable_limiter": False,
        },
    )
    assert cached_resp.status_code == 200
    assert cached_resp.json()["cached"] is True

    # GET /process returns latest completed result
    get_resp = client.get(f"/api/v1/sessions/{session_id}/process")
    assert get_resp.status_code == 200
    assert get_resp.json()["params_hash"] == body["params_hash"]

    # Stream sample-aligned original WAV (full + HTTP 206 Range)
    orig_aligned_resp = client.get(
        f"/api/v1/sessions/{session_id}/audio/original-aligned"
    )
    assert orig_aligned_resp.status_code == 200
    assert orig_aligned_resp.headers["content-type"] == "audio/wav"
    orig_aligned_samples, orig_sr = sf.read(
        io.BytesIO(orig_aligned_resp.content), always_2d=True
    )
    assert orig_sr == 48000
    assert orig_aligned_samples.shape == (72000, 2)
    assert (
        client.get(
            f"/api/v1/sessions/{session_id}/audio/original-aligned",
            headers={"Range": "bytes=0-511"},
        ).status_code
        == 206
    )

    # Stream playable processed WAV (full + HTTP 206 Range request)
    audio_resp = client.get(f"/api/v1/sessions/{session_id}/audio/processed")
    assert audio_resp.status_code == 200
    assert audio_resp.headers["content-type"] == "audio/wav"
    proc_samples, proc_sr = sf.read(io.BytesIO(audio_resp.content), always_2d=True)
    assert proc_sr == 48000
    assert proc_samples.shape == (72000, 2)

    range_resp = client.get(
        f"/api/v1/sessions/{session_id}/audio/processed",
        headers={"Range": "bytes=0-2047"},
    )
    assert range_resp.status_code == 206
    assert len(range_resp.content) == 2048

    # Stream unnormalized residual WAV (full + HTTP 206 Range request)
    res_resp = client.get(f"/api/v1/sessions/{session_id}/audio/residual")
    assert res_resp.status_code == 200
    assert res_resp.headers["content-type"] == "audio/wav"
    res_samples, res_sr = sf.read(io.BytesIO(res_resp.content), always_2d=True)
    assert res_sr == 48000
    assert res_samples.shape == (72000, 2)

    # Verify exact sample alignment across streamed 24-bit WAVs: residual == original_aligned - processed
    assert np.allclose(
        res_samples, orig_aligned_samples - proc_samples, atol=1e-5
    )

    res_range = client.get(
        f"/api/v1/sessions/{session_id}/audio/residual",
        headers={"Range": "bytes=0-1023"},
    )
    assert res_range.status_code == 206
    assert len(res_range.content) == 1024

    # Changing a setting invalidates cache and produces a new params_hash
    bypass_resp = client.post(
        f"/api/v1/sessions/{session_id}/process",
        json={"bypass": True},
    )
    assert bypass_resp.status_code == 200
    bypass_body = bypass_resp.json()
    assert bypass_body["cached"] is False
    assert bypass_body["params_hash"] != body["params_hash"]
    assert bypass_body["processing_mode"] == "bypassed"

    # Bypass output matches original_aligned sample-for-sample and residual is exact zero
    bypass_orig, _ = sf.read(
        io.BytesIO(
            client.get(
                f"/api/v1/sessions/{session_id}/audio/original-aligned"
            ).content
        ),
        always_2d=True,
    )
    bypass_proc, _ = sf.read(
        io.BytesIO(
            client.get(f"/api/v1/sessions/{session_id}/audio/processed").content
        ),
        always_2d=True,
    )
    bypass_res, _ = sf.read(
        io.BytesIO(
            client.get(f"/api/v1/sessions/{session_id}/audio/residual").content
        ),
        always_2d=True,
    )
    assert np.array_equal(bypass_orig, bypass_proc)
    assert float(np.max(np.abs(bypass_res))) == 0.0


def test_mp3_upload_processing_maintains_exact_sample_alignment_across_ab_streams(
    client: TestClient, test_settings: Settings, tmp_path: Path
) -> None:
    ffmpeg_path = test_settings.resolved_ffmpeg_path
    if not ffmpeg_path:
        pytest.skip("FFmpeg not available in environment")

    n = 44100
    t = np.arange(n, dtype=np.float64) / 44100.0
    mono = (
        0.2 * np.sin(2.0 * math.pi * 330.0 * t)
        + 0.03 * np.sin(2.0 * math.pi * 60.0 * t)
    ).astype(np.float32)
    wav_src = tmp_path / "src.wav"
    mp3_src = tmp_path / "src.mp3"
    sf.write(str(wav_src), np.column_stack([mono, mono]), 44100, subtype="PCM_16")
    subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-v",
            "error",
            "-i",
            str(wav_src),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(mp3_src),
        ],
        shell=False,
        check=True,
        timeout=15,
    )

    up = client.post(
        "/api/v1/sessions/upload",
        files={"file": ("mp3_align_test.mp3", mp3_src.read_bytes(), "audio/mpeg")},
    )
    assert up.status_code == 201
    sid = up.json()["session_id"]

    proc = client.post(f"/api/v1/sessions/{sid}/process", json={"strength": 0.5})
    assert proc.status_code == 200

    orig_a, sr_a = sf.read(
        io.BytesIO(client.get(f"/api/v1/sessions/{sid}/audio/original-aligned").content),
        always_2d=True,
    )
    proc_b, sr_b = sf.read(
        io.BytesIO(client.get(f"/api/v1/sessions/{sid}/audio/processed").content),
        always_2d=True,
    )
    res_d, sr_d = sf.read(
        io.BytesIO(client.get(f"/api/v1/sessions/{sid}/audio/residual").content),
        always_2d=True,
    )
    assert sr_a == sr_b == sr_d == 44100
    assert orig_a.shape == proc_b.shape == res_d.shape
    assert np.allclose(res_d, orig_a - proc_b, atol=1e-5)


def test_process_endpoint_validates_session_and_parameter_bounds(client: TestClient) -> None:
    assert client.post("/api/v1/sessions/bad-id/process").status_code == 400
    assert (
        client.post(
            "/api/v1/sessions/11111111-2222-4333-8444-555555555555/process"
        ).status_code
        == 404
    )

    session_id, _ = _upload_noisy_stereo_wav(client)

    # Reject unsafe extreme strength (> 0.85), unsafe HPF (> 150 Hz), invalid dry/wet
    for bad_payload in (
        {"strength": 1.0},
        {"strength": -0.1},
        {"hpf_cutoff_hz": 500.0},
        {"hpf_cutoff_hz": 5.0},
        {"dry_wet_mix": 1.5},
        {"limiter_ceiling_dbtp": 1.0},
    ):
        resp = client.post(f"/api/v1/sessions/{session_id}/process", json=bad_payload)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"


def test_explicit_audiosep_selection_returns_unavailable_without_dsp_fallback(
    client: TestClient,
) -> None:
    session_id, _ = _upload_noisy_stereo_wav(client)
    response = client.post(
        f"/api/v1/sessions/{session_id}/process",
        json={"engine": "audiosep_experimental"},
    )

    assert response.status_code == 503
    body = response.json()["error"]
    assert body["code"] == "AI_ENGINE_UNAVAILABLE"
    assert body["details"]["requested_engine"] == "audiosep_experimental"
    assert body["details"]["fallback_applied"] is False
    # An unavailable AI request must not create a misleading DSP result.
    assert client.get(f"/api/v1/sessions/{session_id}/process").status_code == 404
