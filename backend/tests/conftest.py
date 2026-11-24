"""Shared Pytest fixtures for SONORA backend tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture()
def test_settings(tmp_path: Path) -> Settings:
    """Create isolated test settings backed by a temporary directory."""
    return Settings(
        env="test",
        temp_dir=str(tmp_path / "sonora_test_sessions"),
        max_upload_mb=50,
        max_duration_seconds=300,
        max_decoded_pcm_mb=256,
        allowed_origins="http://localhost:5173",
    )


@pytest.fixture()
def client(test_settings: Settings) -> TestClient:
    """FastAPI TestClient with isolated configuration."""
    app = create_app(settings=test_settings)
    with TestClient(app) as test_client:
        yield test_client
