"""Magic-byte, codec, container, and resource-limit audio validation."""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import soundfile as sf

from app.core.config import Settings
from app.core.exceptions import (
    AudioValidationError,
    MediaToolUnavailableError,
    PayloadTooLargeError,
)
from app.models.schemas import SupportedAudioFormat

MIN_SAMPLE_RATE_HZ = 8000
MAX_SAMPLE_RATE_HZ = 192000
MIN_DURATION_SECONDS = 0.05
MAX_CHANNELS = 2
FFPROBE_TIMEOUT_SECONDS = 10

_SOUNDFILE_BIT_DEPTHS: dict[str, int | None] = {
    "PCM_S8": 8,
    "PCM_U8": 8,
    "PCM_16": 16,
    "PCM_24": 24,
    "PCM_32": 32,
    "FLOAT": 32,
    "DOUBLE": 64,
}


@dataclass(frozen=True)
class ValidatedAudioProbe:
    """Verified pre-decode audio stream properties."""

    format: SupportedAudioFormat
    codec: str
    container: str
    sample_rate: int
    channels: int
    duration_seconds: float
    frame_count: int
    bit_depth: int | None
    bitrate_kbps: int | None
    file_size_bytes: int


def _is_valid_mp3_frame_header(b0: int, b1: int, b2: int) -> bool:
    """Validate an MPEG Audio Layer III frame header (strictly MP3, not AAC/ADTS)."""
    if b0 != 0xFF or (b1 & 0xE0) != 0xE0:
        return False
    version_bits = (b1 >> 3) & 0x03  # 01 is reserved
    layer_bits = (b1 >> 1) & 0x03  # 01 is Layer III (MP3); 00 is AAC ADTS
    bitrate_idx = (b2 >> 4) & 0x0F  # 0000=free, 1111=invalid
    sr_idx = (b2 >> 2) & 0x03  # 11=reserved
    return (
        version_bits != 1
        and layer_bits == 1
        and bitrate_idx not in (0, 15)
        and sr_idx != 3
    )


def detect_magic_format(file_path: Path) -> SupportedAudioFormat | None:
    """Identify audio format strictly from file magic bytes (ignoring extension)."""
    try:
        with file_path.open("rb") as fh:
            header = fh.read(65536)
    except OSError as exc:
        raise AudioValidationError(
            code="FILE_READ_ERROR",
            message="Failed to read uploaded file header.",
            details={"reason": str(exc)},
        ) from exc

    if len(header) < 4:
        return None

    # WAV (RIFF....WAVE or RF64....WAVE)
    if (
        len(header) >= 12
        and header[:4] in (b"RIFF", b"RF64")
        and header[8:12] == b"WAVE"
    ):
        return "wav"

    # FLAC (fLaC)
    if header[:4] == b"fLaC":
        return "flac"

    # MP3 with ID3v2 tag header
    if len(header) >= 10 and header[:3] == b"ID3":
        # Synchsafe 28-bit ID3v2 payload size
        b6, b7, b8, b9 = header[6], header[7], header[8], header[9]
        if max(b6, b7, b8, b9) < 0x80:
            tag_size = (b6 << 21) | (b7 << 14) | (b8 << 7) | b9
            flags = header[5]
            footer_len = 10 if (flags & 0x10) else 0
            audio_offset = 10 + tag_size + footer_len
            try:
                with file_path.open("rb") as fh:
                    fh.seek(audio_offset)
                    post_id3 = fh.read(4096)
            except OSError:
                return None

            for idx in range(max(0, len(post_id3) - 3)):
                if _is_valid_mp3_frame_header(
                    post_id3[idx], post_id3[idx + 1], post_id3[idx + 2]
                ):
                    return "mp3"
        return None

    # Raw MP3 without ID3v2 header (scan first 4 KB for valid MPEG Layer III sync)
    scan_limit = min(len(header) - 3, 4096)
    for idx in range(max(0, scan_limit)):
        if _is_valid_mp3_frame_header(header[idx], header[idx + 1], header[idx + 2]):
            return "mp3"

    return None


def _run_ffprobe(file_path: Path, ffprobe_path: str) -> dict[str, Any]:
    """Run ffprobe safely without shell interpolation and with strict timeout."""
    cmd = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-i",
        str(file_path),
    ]
    try:
        completed = subprocess.run(
            cmd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioValidationError(
            code="PROBE_TIMEOUT",
            message="Audio inspection timed out; file may be malformed.",
        ) from exc
    except OSError as exc:
        raise MediaToolUnavailableError(
            code="FFPROBE_EXECUTION_FAILED",
            message="Failed to execute ffprobe for audio validation.",
            details={"reason": str(exc)},
        ) from exc

    if completed.returncode != 0:
        stderr_snippet = (completed.stderr or "").strip()[:300]
        raise AudioValidationError(
            code="MALFORMED_AUDIO_FILE",
            message="Audio container failed integrity validation.",
            details={"probe_error": stderr_snippet or "ffprobe returned non-zero status"},
        )

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AudioValidationError(
            code="PROBE_PARSE_ERROR",
            message="Unable to parse container metadata from ffprobe.",
        ) from exc

    if not isinstance(data, dict):
        raise AudioValidationError(
            code="PROBE_PARSE_ERROR",
            message="Unexpected metadata structure returned by ffprobe.",
        )
    return data


def _extract_bit_depth_from_ffprobe(
    stream: dict[str, Any], codec_name: str
) -> int | None:
    if codec_name == "mp3":
        return None
    for key in ("bits_per_raw_sample", "bits_per_sample"):
        raw = stream.get(key)
        if raw is not None:
            try:
                val = int(raw)
                if val > 0:
                    return val
            except (TypeError, ValueError):
                pass
    return None


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_audio_file(file_path: Path, settings: Settings) -> ValidatedAudioProbe:
    """Validate magic bytes, codec, container integrity, and resource bounds."""
    if not file_path.is_file():
        raise AudioValidationError(
            code="FILE_NOT_FOUND",
            message="Uploaded file could not be found on disk.",
        )

    file_size_bytes = file_path.stat().st_size
    if file_size_bytes == 0:
        raise AudioValidationError(
            code="EMPTY_FILE",
            message="Uploaded file is empty (0 bytes).",
        )
    if file_size_bytes > settings.max_upload_bytes:
        raise PayloadTooLargeError(
            code="FILE_TOO_LARGE",
            message=(
                f"Uploaded file exceeds the maximum allowed size of "
                f"{settings.max_upload_mb} MB."
            ),
            details={
                "max_upload_mb": settings.max_upload_mb,
                "file_size_bytes": file_size_bytes,
            },
        )

    magic_format = detect_magic_format(file_path)
    if magic_format is None:
        raise AudioValidationError(
            code="UNSUPPORTED_AUDIO_FORMAT",
            message=(
                "File content does not match a supported WAV, FLAC, or MP3 header. "
                "File extensions are not trusted."
            ),
        )

    ffprobe_path = settings.resolved_ffprobe_path
    ffmpeg_path = settings.resolved_ffmpeg_path

    if magic_format == "mp3" and (not ffprobe_path or not ffmpeg_path):
        raise MediaToolUnavailableError(
            code="MP3_TOOLING_UNAVAILABLE",
            message=(
                "MP3 ingestion requires local FFmpeg and FFprobe binaries. "
                "Upload WAV or FLAC, or install FFmpeg."
            ),
        )

    codec_name = ""
    container_name = magic_format
    sample_rate: int | None = None
    channels: int | None = None
    duration_seconds: float | None = None
    frame_count: int | None = None
    bit_depth: int | None = None
    bitrate_kbps: int | None = None

    # 1. Inspect via ffprobe whenever available (mandatory for MP3; authoritative codec check for WAV/FLAC)
    if ffprobe_path:
        probe_data = _run_ffprobe(file_path, ffprobe_path)
        streams = probe_data.get("streams") or []
        fmt_info = probe_data.get("format") or {}

        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        non_art_video = [
            s
            for s in streams
            if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")
        ]

        if non_art_video:
            raise AudioValidationError(
                code="VIDEO_CONTAINER_REJECTED",
                message="Video streams are not accepted. Upload an audio-only WAV, FLAC, or MP3 file.",
            )
        if not audio_streams:
            raise AudioValidationError(
                code="NO_AUDIO_STREAM",
                message="No valid audio stream was found inside the uploaded file.",
            )

        stream = audio_streams[0]
        codec_name = str(stream.get("codec_name") or "").lower()
        container_name = str(fmt_info.get("format_name") or magic_format).lower()

        if magic_format == "wav" and not codec_name.startswith("pcm_"):
            raise AudioValidationError(
                code="UNSUPPORTED_CODEC",
                message=(
                    f"Unsupported WAV codec '{codec_name or 'unknown'}'. "
                    "Only uncompressed PCM / IEEE float WAV files are supported."
                ),
                details={"codec": codec_name, "detected_format": magic_format},
            )
        if magic_format == "flac" and codec_name != "flac":
            raise AudioValidationError(
                code="UNSUPPORTED_CODEC",
                message=f"Codec '{codec_name or 'unknown'}' does not match FLAC container.",
                details={"codec": codec_name, "detected_format": magic_format},
            )
        if magic_format == "mp3" and codec_name != "mp3":
            raise AudioValidationError(
                code="UNSUPPORTED_CODEC",
                message=(
                    f"Unsupported codec '{codec_name or 'unknown'}' for MP3 upload. "
                    "Only MPEG Layer III (MP3) audio is supported."
                ),
                details={"codec": codec_name, "detected_format": magic_format},
            )

        sample_rate = _safe_int(stream.get("sample_rate"))
        channels = _safe_int(stream.get("channels"))
        duration_seconds = _safe_float(stream.get("duration")) or _safe_float(
            fmt_info.get("duration")
        )
        bit_depth = _extract_bit_depth_from_ffprobe(stream, codec_name)

        raw_bitrate = _safe_int(stream.get("bit_rate")) or _safe_int(
            fmt_info.get("bit_rate")
        )
        if raw_bitrate and raw_bitrate > 0:
            bitrate_kbps = int(round(raw_bitrate / 1000.0))

    # 2. Cross-validate WAV/FLAC via soundfile (also enables WAV/FLAC when ffprobe is absent)
    if magic_format in ("wav", "flac"):
        try:
            sf_info = sf.info(str(file_path))
        except (sf.LibsndfileError, RuntimeError, OSError) as exc:
            raise AudioValidationError(
                code="MALFORMED_AUDIO_FILE",
                message=f"Failed to read {magic_format.upper()} audio structure.",
                details={"reason": str(exc)},
            ) from exc

        expected_sf_format = "WAV" if magic_format == "wav" else "FLAC"
        if sf_info.format.upper() != expected_sf_format:
            raise AudioValidationError(
                code="UNSUPPORTED_CODEC",
                message=(
                    f"Container mismatch: detected '{sf_info.format}' instead of "
                    f"{expected_sf_format}."
                ),
            )

        if magic_format == "wav" and sf_info.subtype not in _SOUNDFILE_BIT_DEPTHS:
            raise AudioValidationError(
                code="UNSUPPORTED_CODEC",
                message=(
                    f"Unsupported WAV encoding subtype '{sf_info.subtype}'. "
                    "Only uncompressed PCM and IEEE float WAV are supported."
                ),
                details={"subtype": sf_info.subtype},
            )

        sample_rate = sf_info.samplerate
        channels = sf_info.channels
        frame_count = sf_info.frames
        duration_seconds = (
            float(sf_info.frames) / float(sf_info.samplerate)
            if sf_info.samplerate > 0
            else 0.0
        )
        if not codec_name:
            codec_name = sf_info.subtype.lower() if magic_format == "wav" else "flac"
        if bit_depth is None:
            bit_depth = _SOUNDFILE_BIT_DEPTHS.get(sf_info.subtype)

    # 3. Validate numeric stream parameters & resource safety limits
    if sample_rate is None or not (MIN_SAMPLE_RATE_HZ <= sample_rate <= MAX_SAMPLE_RATE_HZ):
        raise AudioValidationError(
            code="UNSUPPORTED_SAMPLE_RATE",
            message=(
                f"Sample rate {sample_rate} Hz is outside the supported range "
                f"({MIN_SAMPLE_RATE_HZ}–{MAX_SAMPLE_RATE_HZ} Hz)."
            ),
            details={"sample_rate": sample_rate},
        )

    if channels is None or not (1 <= channels <= MAX_CHANNELS):
        raise AudioValidationError(
            code="UNSUPPORTED_CHANNEL_COUNT",
            message=(
                f"Unsupported channel count ({channels}). "
                "SONORA currently supports mono (1) and stereo (2) recordings."
            ),
            details={"channels": channels},
        )

    if duration_seconds is None or duration_seconds < MIN_DURATION_SECONDS:
        raise AudioValidationError(
            code="AUDIO_TOO_SHORT",
            message=(
                f"Audio duration must be at least {MIN_DURATION_SECONDS:.2f} seconds."
            ),
            details={"duration_seconds": duration_seconds},
        )

    if duration_seconds > settings.max_duration_seconds:
        raise AudioValidationError(
            code="AUDIO_TOO_LONG",
            message=(
                f"Audio duration ({duration_seconds:.1f}s) exceeds the maximum allowed "
                f"duration of {settings.max_duration_seconds}s."
            ),
            details={
                "duration_seconds": round(duration_seconds, 2),
                "max_duration_seconds": settings.max_duration_seconds,
            },
        )

    if frame_count is None or frame_count <= 0:
        frame_count = max(1, int(math.ceil(duration_seconds * sample_rate)))

    # Decompression-bomb guard: check decoded float32 PCM footprint before loading into RAM
    estimated_pcm_bytes = frame_count * channels * 4
    max_pcm_bytes = settings.max_decoded_pcm_mb * 1024 * 1024
    if estimated_pcm_bytes > max_pcm_bytes:
        raise PayloadTooLargeError(
            code="DECODED_PCM_LIMIT_EXCEEDED",
            message=(
                f"Decoded audio footprint (~{estimated_pcm_bytes / (1024 * 1024):.1f} MB) "
                f"exceeds the {settings.max_decoded_pcm_mb} MB memory safety limit."
            ),
            details={
                "estimated_pcm_mb": round(estimated_pcm_bytes / (1024 * 1024), 2),
                "max_decoded_pcm_mb": settings.max_decoded_pcm_mb,
            },
        )

    return ValidatedAudioProbe(
        format=magic_format,
        codec=codec_name or magic_format,
        container=container_name,
        sample_rate=sample_rate,
        channels=channels,
        duration_seconds=round(duration_seconds, 4),
        frame_count=frame_count,
        bit_depth=bit_depth,
        bitrate_kbps=bitrate_kbps,
        file_size_bytes=file_size_bytes,
    )
