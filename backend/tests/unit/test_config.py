"""Unit tests for environment-driven Settings configuration."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_defaults_and_derived_properties(tmp_path: Path) -> None:
    custom_temp = tmp_path / "custom_sessions"
    cfg = Settings(
        temp_dir=str(custom_temp),
        allowed_origins="http://localhost:5173, http://127.0.0.1:5173 ",
        max_upload_mb=120,
    )

    assert cfg.resolved_temp_dir == custom_temp.resolve()
    assert cfg.allowed_origins_list == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    assert cfg.max_upload_bytes == 120 * 1024 * 1024


def test_settings_rejects_invalid_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(max_upload_mb=0)

    with pytest.raises(ValidationError):
        Settings(max_duration_seconds=5)

    with pytest.raises(ValidationError):
        Settings(port=70000)


def test_resolve_binary_returns_none_for_missing_explicit_path(tmp_path: Path) -> None:
    cfg = Settings(temp_dir=str(tmp_path))
    missing = str(tmp_path / "does_not_exist_ffmpeg.exe")
    assert cfg.resolve_binary(missing, "ffmpeg") is None
