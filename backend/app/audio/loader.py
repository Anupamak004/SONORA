"""Native sample-rate float32 audio decoding for WAV, FLAC, and MP3."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from app.audio.validator import ValidatedAudioProbe
from app.core.config import Settings
from app.core.exceptions import (
    AudioValidationError,
    MediaToolUnavailableError,
    PayloadTooLargeError,
)

FFMPEG_DECODE_TIMEOUT_SECONDS = 30


def _decode_mp3_via_ffmpeg(
    file_path: Path,
    probe: ValidatedAudioProbe,
    ffmpeg_path: str,
    max_pcm_bytes: int,
) -> tuple[np.ndarray, int]:
    """Decode MP3 to native sample-rate float32 PCM using bounded pipe reads."""
    cmd = [
        ffmpeg_path,
        "-v",
        "error",
        "-i",
        str(file_path),
        "-vn",
        "-sn",
        "-dn",
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        str(probe.channels),
        "-ar",
        str(probe.sample_rate),
        "pipe:1",
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise MediaToolUnavailableError(
            code="FFMPEG_EXECUTION_FAILED",
            message="Failed to execute FFmpeg for MP3 decoding.",
            details={"reason": str(exc)},
        ) from exc

    chunks: list[bytes] = []
    total_bytes = 0
    # Allow tiny framing tolerance (1%) beyond estimated size for MP3 encoder padding
    hard_byte_cap = max_pcm_bytes + max(65536, int(max_pcm_bytes * 0.01))

    try:
        assert proc.stdout is not None
        assert proc.stderr is not None

        while True:
            chunk = proc.stdout.read(262144)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > hard_byte_cap:
                proc.kill()
                proc.wait(timeout=5)
                raise PayloadTooLargeError(
                    code="DECODED_PCM_LIMIT_EXCEEDED",
                    message="Decoded MP3 PCM stream exceeded the configured memory safety limit.",
                )
            chunks.append(chunk)

        _, stderr_bytes = proc.communicate(timeout=FFMPEG_DECODE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        proc.wait(timeout=5)
        raise AudioValidationError(
            code="DECODE_TIMEOUT",
            message="Audio decoding timed out.",
        ) from exc

    if proc.returncode != 0:
        err_msg = stderr_bytes.decode("utf-8", errors="replace").strip()[:300]
        raise AudioValidationError(
            code="AUDIO_DECODE_FAILED",
            message="FFmpeg failed to decode the MP3 stream.",
            details={"decoder_error": err_msg},
        )

    raw_pcm = b"".join(chunks)
    frame_stride = probe.channels * 4
    usable_bytes = (len(raw_pcm) // frame_stride) * frame_stride
    if usable_bytes == 0:
        raise AudioValidationError(
            code="AUDIO_DECODE_FAILED",
            message="Decoded MP3 stream contained zero audio samples.",
        )

    samples = np.frombuffer(raw_pcm[:usable_bytes], dtype="<f4").copy()
    samples = samples.reshape((-1, probe.channels))
    return samples, probe.sample_rate


def decode_audio_float32(
    file_path: Path, probe: ValidatedAudioProbe, settings: Settings
) -> tuple[np.ndarray, int]:
    """Decode validated WAV, FLAC, or MP3 into native-SR float32 array (frames, channels)."""
    max_pcm_bytes = settings.max_decoded_pcm_mb * 1024 * 1024

    if probe.format in ("wav", "flac"):
        try:
            samples, sample_rate = sf.read(
                str(file_path), dtype="float32", always_2d=True
            )
        except (sf.LibsndfileError, RuntimeError, OSError) as exc:
            raise AudioValidationError(
                code="AUDIO_DECODE_FAILED",
                message=f"Failed to decode {probe.format.upper()} audio samples.",
                details={"reason": str(exc)},
            ) from exc
    elif probe.format == "mp3":
        ffmpeg_path = settings.resolved_ffmpeg_path
        if not ffmpeg_path:
            raise MediaToolUnavailableError(
                code="MP3_TOOLING_UNAVAILABLE",
                message="FFmpeg is required to decode MP3 audio.",
            )
        samples, sample_rate = _decode_mp3_via_ffmpeg(
            file_path, probe, ffmpeg_path, max_pcm_bytes
        )
    else:
        raise AudioValidationError(
            code="UNSUPPORTED_AUDIO_FORMAT",
            message=f"Unsupported audio format '{probe.format}'.",
        )

    if samples.size == 0 or samples.shape[0] == 0:
        raise AudioValidationError(
            code="AUDIO_DECODE_FAILED",
            message="Decoded audio contains no sample frames.",
        )

    if samples.nbytes > max_pcm_bytes + 65536:
        raise PayloadTooLargeError(
            code="DECODED_PCM_LIMIT_EXCEEDED",
            message="Decoded audio exceeds the configured memory safety limit.",
        )

    if not np.all(np.isfinite(samples)):
        raise AudioValidationError(
            code="CORRUPT_AUDIO_SAMPLES",
            message="Decoded audio contains non-finite (NaN or Inf) sample values.",
        )

    return np.ascontiguousarray(samples, dtype=np.float32), int(sample_rate)
