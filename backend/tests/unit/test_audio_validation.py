"""Unit tests for magic-byte/codec validation, limits, loudness, and waveform peaks."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.audio.loudness import measure_audio_levels
from app.audio.validator import detect_magic_format, validate_audio_file
from app.audio.waveform import compute_waveform_peaks
from app.core.config import Settings
from app.core.exceptions import AudioValidationError, PayloadTooLargeError


def _make_sine(
    duration_s: float = 1.0,
    sample_rate: int = 48000,
    freq_hz: float = 1000.0,
    peak_amp: float = 0.1,
    channels: int = 2,
) -> np.ndarray:
    t = np.arange(int(round(duration_s * sample_rate)), dtype=np.float64) / sample_rate
    mono = (peak_amp * np.sin(2.0 * math.pi * freq_hz * t)).astype(np.float32)
    return np.column_stack([mono] * channels)


def test_detect_magic_format_rejects_spoofed_wav(tmp_path: Path) -> None:
    fake_wav = tmp_path / "guitar.wav"
    fake_wav.write_bytes(b"This is definitely not a WAV audio recording.")
    assert detect_magic_format(fake_wav) is None


def test_validate_rejects_unsupported_wav_codec_adpcm(tmp_path: Path) -> None:
    adpcm_path = tmp_path / "compressed.wav"
    samples = _make_sine(duration_s=0.5, sample_rate=44100, channels=1)
    sf.write(str(adpcm_path), samples, 44100, subtype="IMA_ADPCM", format="WAV")

    settings = Settings(env="test", temp_dir=str(tmp_path))
    with pytest.raises(AudioValidationError) as exc_info:
        validate_audio_file(adpcm_path, settings)
    assert exc_info.value.code == "UNSUPPORTED_CODEC"


def test_validate_enforces_duration_and_decoded_pcm_limits(tmp_path: Path) -> None:
    wav_path = tmp_path / "long_note.wav"
    samples = _make_sine(duration_s=12.0, sample_rate=48000, channels=2)
    sf.write(str(wav_path), samples, 48000, subtype="PCM_16", format="WAV")

    short_limit_cfg = Settings(
        env="test",
        temp_dir=str(tmp_path),
        max_duration_seconds=10,
    )
    with pytest.raises(AudioValidationError) as dur_exc:
        validate_audio_file(wav_path, short_limit_cfg)
    assert dur_exc.value.code == "AUDIO_TOO_LONG"

    # 12s * 48000 * 2ch * 4 bytes ~= 4.4 MB; test decompression-bomb cap with 16 MB vs long FLAC
    flac_path = tmp_path / "silent_bomb.flac"
    # 60s stereo @ 96 kHz = ~44 MB decoded float32 PCM, but compresses to tiny FLAC
    bomb_samples = np.zeros((96000 * 60, 2), dtype=np.float32)
    sf.write(str(flac_path), bomb_samples, 96000, subtype="PCM_16", format="FLAC")
    assert flac_path.stat().st_size < 512 * 1024  # tiny on disk

    low_pcm_cfg = Settings(
        env="test",
        temp_dir=str(tmp_path),
        max_duration_seconds=120,
        max_decoded_pcm_mb=16,
    )
    with pytest.raises(PayloadTooLargeError) as pcm_exc:
        validate_audio_file(flac_path, low_pcm_cfg)
    assert pcm_exc.value.code == "DECODED_PCM_LIMIT_EXCEEDED"


def test_validate_rejects_unsupported_channel_count(tmp_path: Path) -> None:
    quad_path = tmp_path / "quad.wav"
    quad = _make_sine(duration_s=0.5, sample_rate=48000, channels=4)
    sf.write(str(quad_path), quad, 48000, subtype="PCM_16", format="WAV")

    settings = Settings(env="test", temp_dir=str(tmp_path))
    with pytest.raises(AudioValidationError) as exc_info:
        validate_audio_file(quad_path, settings)
    assert exc_info.value.code == "UNSUPPORTED_CHANNEL_COUNT"


def test_loudness_accuracy_on_known_sine_reference() -> None:
    # -20 dBFS peak 1 kHz stereo sine -> ITU-R BS.1770 integrated loudness ~= -20.0 LUFS
    stereo_48k = _make_sine(duration_s=2.0, sample_rate=48000, freq_hz=1000.0, peak_amp=0.1, channels=2)
    metrics_48k = measure_audio_levels(stereo_48k, 48000)

    assert metrics_48k.sample_peak_dbfs is not None
    assert abs(metrics_48k.sample_peak_dbfs - (-20.0)) < 0.05
    assert metrics_48k.true_peak_dbtp is not None
    assert abs(metrics_48k.true_peak_dbtp - (-20.0)) < 0.1
    assert metrics_48k.rms_dbfs is not None
    assert abs(metrics_48k.rms_dbfs - (-23.01)) < 0.05
    assert metrics_48k.integrated_lufs is not None
    assert abs(metrics_48k.integrated_lufs - (-20.0)) < 0.25

    # Verify 44.1 kHz bilinear K-weighting consistency
    mono_44k = _make_sine(duration_s=2.0, sample_rate=44100, freq_hz=1000.0, peak_amp=0.1, channels=1)
    metrics_44k = measure_audio_levels(mono_44k, 44100)
    assert metrics_44k.integrated_lufs is not None
    assert abs(metrics_44k.integrated_lufs - (-23.01)) < 0.25


def test_loudness_handles_silence_and_short_clips_gracefully() -> None:
    silent = np.zeros((48000, 1), dtype=np.float32)
    silent_metrics = measure_audio_levels(silent, 48000)
    assert silent_metrics.sample_peak_dbfs is None
    assert silent_metrics.integrated_lufs is None
    assert silent_metrics.loudness_note is not None

    short = _make_sine(duration_s=0.15, sample_rate=48000, channels=1)
    short_metrics = measure_audio_levels(short, 48000)
    assert short_metrics.sample_peak_dbfs is not None
    assert short_metrics.integrated_lufs is None
    assert short_metrics.loudness_note is not None


def test_waveform_peaks_bounds_and_bucket_count() -> None:
    samples = _make_sine(duration_s=1.0, sample_rate=48000, peak_amp=0.5, channels=2)
    waveform = compute_waveform_peaks(samples, target_buckets=200)
    assert waveform.bucket_count == 200
    assert len(waveform.peaks) == 200
    assert max(waveform.peaks) <= 0.51
    assert min(waveform.peaks) >= 0.0
