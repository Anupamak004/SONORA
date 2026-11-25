"""System health, media tool capability detection, and honest engine readiness."""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends

from app.ai.registry import engine_registry
from app.core.config import Settings, get_settings
from app.models.schemas import (
    EngineCapability,
    HealthResponse,
    MediaToolStatus,
    StorageStatus,
    UploadLimits,
)

router = APIRouter(tags=["system"])


def _probe_binary_version(binary_path: str | None, tool_name: str) -> MediaToolStatus:
    """Safely inspect an external media tool binary without shell execution."""
    if not binary_path:
        return MediaToolStatus(
            available=False,
            version=None,
            notes=f"{tool_name} not found on PATH or SONORA_{tool_name.upper()}_PATH.",
        )

    try:
        completed = subprocess.run(
            [binary_path, "-version"],
            shell=False,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        first_line = (completed.stdout or completed.stderr or "").splitlines()
        version_line = first_line[0].strip() if first_line else None
        if completed.returncode == 0 and version_line:
            return MediaToolStatus(available=True, version=version_line)
        return MediaToolStatus(
            available=False,
            version=None,
            notes=f"{tool_name} exited with code {completed.returncode}.",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return MediaToolStatus(
            available=False,
            version=None,
            notes=f"Failed to execute {tool_name}: {exc}",
        )


def _check_temp_dir_ready(temp_dir: Path) -> bool:
    """Ensure the scoped temporary session directory exists and is writable."""
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        probe_file = temp_dir / ".sonora_write_probe"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _engine_capabilities() -> list[EngineCapability]:
    """Report active DSP and registry-backed optional engine implementation status."""
    registered_engine_ids = {
        descriptor.id for descriptor in engine_registry.descriptors()
    }
    return [
        EngineCapability(
            id="precision_musical_dsp",
            name="Precision Musical DSP (Decision-Directed Wiener + Pitch-Safe Filters)",
            category="precision_dsp",
            implemented=True,
            available=True,
            optional_dependency=False,
            target_stage="Stage 4 (Active)",
            role="Primary offline foundation; deterministic CPU DSP requiring zero AI downloads.",
            limitations=(
                "Conservative suppression excels on steady hum, rumble, and broadband hiss; "
                "cannot cleanly separate overlapping non-stationary speech or complex traffic."
            ),
        ),
        EngineCapability(
            id="htdemucs_stem_separation",
            name="HTDemucs (Vocal / Speech Stem Separation)",
            category="stem_separation",
            implemented="htdemucs_stem_separation" in registered_engine_ids,
            available=False,
            optional_dependency=True,
            target_stage="Stage 5 (Optional)",
            role="Musical stem-separation engine for attenuating background speech/vocals.",
            limitations=(
                "Not a general-purpose environmental noise remover; wind, hiss, and steady "
                "fan noise typically remain in instrumental stems. Offline only."
            ),
        ),
        EngineCapability(
            id="music_ai_denoise_onnx",
            name="Mel-Band RoFormer / MDX-Net Denoise (ONNX)",
            category="music_ai",
            implemented="music_ai_denoise_onnx" in registered_engine_ids,
            available=False,
            optional_dependency=True,
            target_stage="Stage 5 (Optional)",
            role="Optional offline full-band music denoising for complex broadband/room noise.",
            limitations=(
                "Higher CPU/memory cost; offline only; requires verified open-weights "
                "checkpoint download."
            ),
        ),
        EngineCapability(
            id="deepfilternet3_experimental",
            name="DeepFilterNet3 (Experimental, Guarded)",
            category="experimental_ai",
            implemented="deepfilternet3_experimental" in registered_engine_ids,
            available=False,
            optional_dependency=True,
            target_stage="Stage 5 (Experimental)",
            role="Speech-trained full-band suppressor evaluated with strict attenuation caps.",
            limitations=(
                "Trained on speech; remains strictly experimental unless real instrument "
                "benchmarks verify acceptable harmonic and sustain fidelity."
            ),
        ),
    ]


@router.get("/health", response_model=HealthResponse)
async def get_health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Return real backend health, FFmpeg/FFprobe detection, limits, and engine readiness."""
    ffmpeg_status = _probe_binary_version(settings.resolved_ffmpeg_path, "ffmpeg")
    ffprobe_status = _probe_binary_version(settings.resolved_ffprobe_path, "ffprobe")
    temp_dir_ready = _check_temp_dir_ready(settings.resolved_temp_dir)

    supported_formats = ["wav", "flac"]
    if ffmpeg_status.available and ffprobe_status.available:
        supported_formats.append("mp3")

    overall_status = "ok" if temp_dir_ready else "degraded"

    return HealthResponse(
        status=overall_status,
        app_name=settings.app_name,
        version=settings.app_version,
        stage="Stage 4 — Precision Musical DSP & Playable Comparison",
        environment=settings.env,
        python_version=platform.python_version(),
        ffmpeg=ffmpeg_status,
        ffprobe=ffprobe_status,
        storage=StorageStatus(
            temp_dir_ready=temp_dir_ready,
            session_ttl_minutes=settings.session_ttl_minutes,
        ),
        limits=UploadLimits(
            max_upload_mb=settings.max_upload_mb,
            max_duration_seconds=settings.max_duration_seconds,
            max_decoded_pcm_mb=settings.max_decoded_pcm_mb,
            supported_upload_formats=supported_formats,
        ),
        engines=_engine_capabilities(),
    )
