"""Environment-driven application configuration for SONORA."""

from __future__ import annotations

import shutil
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ENV_FILES = (
    str(_REPO_ROOT / ".env"),
    str(Path(__file__).resolve().parents[2] / ".env"),
)


class Settings(BaseSettings):
    """Typed runtime settings loaded from environment variables and .env files."""

    model_config = SettingsConfigDict(
        env_prefix="SONORA_",
        env_file=_DEFAULT_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="SONORA")
    app_version: str = Field(default="0.1.0-stage1")
    env: Literal["development", "test", "production"] = Field(default="development")
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO"
    )

    allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173"
    )

    # Scoped temporary storage & audio safety bounds
    temp_dir: str = Field(default="")
    session_ttl_minutes: int = Field(default=60, ge=5, le=1440)
    max_upload_mb: int = Field(default=150, ge=1, le=1024)
    max_duration_seconds: int = Field(default=900, ge=10, le=7200)
    max_decoded_pcm_mb: int = Field(default=512, ge=16, le=4096)

    # Optional explicit external media binary paths (auto-detected if empty)
    ffmpeg_path: str = Field(default="")
    ffprobe_path: str = Field(default="")

    # Processing worker concurrency
    max_workers: int = Field(default=2, ge=1, le=16)

    @property
    def allowed_origins_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.allowed_origins.split(",")
            if origin.strip()
        ]

    @property
    def resolved_temp_dir(self) -> Path:
        if self.temp_dir.strip():
            return Path(self.temp_dir).expanduser().resolve()
        return (Path(tempfile.gettempdir()) / "sonora_sessions").resolve()

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def resolve_binary(self, explicit_path: str, binary_name: str) -> str | None:
        """Resolve an external tool path safely without shell expansion."""
        cleaned = explicit_path.strip()
        if cleaned:
            candidate = Path(cleaned).expanduser()
            if candidate.is_file():
                return str(candidate.resolve())
            return None
        return shutil.which(binary_name)

    @property
    def resolved_ffmpeg_path(self) -> str | None:
        return self.resolve_binary(self.ffmpeg_path, "ffmpeg")

    @property
    def resolved_ffprobe_path(self) -> str | None:
        return self.resolve_binary(self.ffprobe_path, "ffprobe")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear settings cache (used in tests when overriding env vars)."""
    get_settings.cache_clear()
