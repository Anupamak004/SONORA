"""API integration tests for POST /api/v1/sessions/{session_id}/analyze."""

from __future__ import annotations

import io
import math

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient


def _upload_test_wav(
    client: TestClient,
    sample_rate: int = 44100,
    duration_s: float = 1.5,
    channels: int = 2,
    add_60hz_hum: bool = False,
) -> str:
    n = int(round(duration_s * sample_rate))
    t = np.arange(n, dtype=np.float64) / sample_rate
    mono = (0.2 * np.sin(2.0 * math.pi * 440.0 * t)).astype(np.float32)
    if add_60hz_hum:
        mono = mono + (
            0.03 * np.sin(2.0 * math.pi * 60.0 * t)
            + 0.015 * np.sin(2.0 * math.pi * 120.0 * t)
        ).astype(np.float32)

    samples = np.column_stack([mono] * channels)
    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, subtype="PCM_24", format="WAV")
    resp = client.post(
        "/api/v1/sessions/upload",
        files={"file": ("analysis_test.wav", buf.getvalue(), "audio/wav")},
    )
    assert resp.status_code == 201
    return resp.json()["session_id"]


def test_analyze_endpoint_default_and_custom_params(client: TestClient) -> None:
    session_id = _upload_test_wav(client, sample_rate=44100, add_60hz_hum=True)

    # Default empty body -> log scale
    resp = client.post(f"/api/v1/sessions/{session_id}/analyze")
    assert resp.status_code == 200
    body = resp.json()

    assert body["session_id"] == session_id
    assert body["sample_rate"] == 44100
    assert body["channels"] == 2
    assert body["noise_floor"]["method"] == "minimum_statistics_spectral_floor"
    assert len(body["detected_indicators"]) >= 4
    hum = next(i for i in body["detected_indicators"] if i["id"] == "electrical_hum")
    assert hum["detected"] is True
    assert "60 Hz" in hum["label"]
    assert body["spectrogram"]["freq_scale"] == "log"
    assert body["spectrogram"]["time_bins"] <= 220
    assert body["spectrogram"]["freq_bins"] <= 96
    assert len(body["psd"]["frequencies_hz"]) == len(body["psd"]["estimated_noise_floor_db"])
    assert len(body["limitations"]) >= 2

    # Custom linear scale + tighter dB floor + custom bounds
    resp_lin = client.post(
        f"/api/v1/sessions/{session_id}/analyze",
        json={
            "freq_scale": "linear",
            "db_min": -80.0,
            "db_max": -5.0,
            "max_time_bins": 80,
            "max_freq_bins": 48,
        },
    )
    assert resp_lin.status_code == 200
    lin_body = resp_lin.json()
    assert lin_body["spectrogram"]["freq_scale"] == "linear"
    assert lin_body["spectrogram"]["db_min"] == -80.0
    assert lin_body["spectrogram"]["db_max"] == -5.0
    assert lin_body["spectrogram"]["time_bins"] <= 80
    assert lin_body["spectrogram"]["freq_bins"] <= 48


def test_analyze_rejects_invalid_session_id_and_missing_session(client: TestClient) -> None:
    bad_resp = client.post("/api/v1/sessions/not-a-uuid/analyze")
    assert bad_resp.status_code == 400
    assert bad_resp.json()["error"]["code"] == "INVALID_SESSION_ID"

    missing_resp = client.post(
        "/api/v1/sessions/11111111-2222-4333-8444-555555555555/analyze"
    )
    assert missing_resp.status_code == 404
    assert missing_resp.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_analyze_rejects_invalid_parameters(client: TestClient) -> None:
    session_id = _upload_test_wav(client)

    bad_scale = client.post(
        f"/api/v1/sessions/{session_id}/analyze",
        json={"freq_scale": "mel"},
    )
    assert bad_scale.status_code == 422
    assert bad_scale.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"

    bad_span = client.post(
        f"/api/v1/sessions/{session_id}/analyze",
        json={"db_min": -40.0, "db_max": -25.0},
    )
    assert bad_span.status_code == 422

    bad_bins = client.post(
        f"/api/v1/sessions/{session_id}/analyze",
        json={"max_time_bins": 5000},
    )
    assert bad_bins.status_code == 422
