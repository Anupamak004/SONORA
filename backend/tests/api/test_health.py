"""API integration tests for GET /api/v1/health."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.ai.base import AIEngine, EngineDescriptor
from app.ai.registry import engine_registry
from app.api.health import _engine_capabilities
from app.core.config import Settings
from app.main import create_app


def test_health_endpoint_returns_valid_status_and_limits(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["app_name"] == "SONORA"
    assert body["storage"]["temp_dir_ready"] is True
    assert body["limits"]["max_upload_mb"] == 50
    assert body["limits"]["max_duration_seconds"] == 300
    assert "wav" in body["limits"]["supported_upload_formats"]
    assert "flac" in body["limits"]["supported_upload_formats"]

    # Stage 4 honesty check: Precision Musical DSP is active; Stage 5 AI engines remain unimplemented
    assert len(body["engines"]) >= 4
    engines_by_id = {engine["id"]: engine for engine in body["engines"]}
    assert engines_by_id["precision_musical_dsp"]["implemented"] is True
    assert engines_by_id["precision_musical_dsp"]["available"] is True
    for engine_id, engine in engines_by_id.items():
        if engine_id != "precision_musical_dsp":
            assert engine["implemented"] is False
            assert engine["available"] is False


def test_health_gracefully_handles_missing_ffmpeg(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.shutil.which", lambda _: None)
    cfg = Settings(
        env="test",
        temp_dir=str(tmp_path / "sessions"),
        ffmpeg_path="",
        ffprobe_path="",
    )
    app = create_app(settings=cfg)
    with TestClient(app) as local_client:
        response = local_client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["ffmpeg"]["available"] is False
        assert body["ffprobe"]["available"] is False
        assert body["limits"]["supported_upload_formats"] == ["wav", "flac"]



def test_health_engine_status_uses_registry_without_loading_models(monkeypatch) -> None:
    class RegisteredTestEngine(AIEngine):
        descriptor = EngineDescriptor(
            id="htdemucs_stem_separation",
            name="Test HTDemucs adapter",
            category="stem_separation",
            description="Test-only registered adapter.",
        )

        def separate(self, audio, sample_rate: int, query: str):
            return audio

    # Isolate the global registry for this test and prove listing does not load a model.
    test_registry = type(engine_registry)()
    test_registry.register(
        RegisteredTestEngine.descriptor,
        lambda: RegisteredTestEngine(),
    )
    monkeypatch.setattr("app.api.health.engine_registry", test_registry)

    capabilities = {item.id: item for item in _engine_capabilities()}
    assert capabilities["htdemucs_stem_separation"].implemented is True
    # A registered adapter is not proof that weights/dependencies are installed.
    assert capabilities["htdemucs_stem_separation"].available is False
    assert capabilities["music_ai_denoise_onnx"].implemented is False
    assert capabilities["deepfilternet3_experimental"].implemented is False
