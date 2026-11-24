"""Regression tests for the Stage 4 sub-band broadband auto-bypass gate."""

from __future__ import annotations

import math

import numpy as np
from scipy import signal

from app.analysis.noise_estimator import estimate_noise_floor
from app.analysis.spectral import compute_power_stft
from app.dsp.broadband import evaluate_broadband_noise_gate
from app.dsp.pipeline import process_audio_pipeline
from app.models.schemas import ProcessRequest
from benchmarks.metrics import (
    compute_si_sdr_db,
    compute_snr_db,
    compute_transient_preservation,
)


def _synth_ukulele(duration_s: float = 3.2, sr: int = 48000, seed: int = 101) -> np.ndarray:
    """Deterministic re-entrant ukulele chord strumming (C, G, Am, F)."""
    rng = np.random.default_rng(seed)
    n = int(round(duration_s * sr))
    out = np.zeros(n, dtype=np.float64)
    chords = [
        [392.00, 261.63, 329.63, 523.25],
        [392.00, 293.66, 392.00, 493.88],
        [440.00, 261.63, 329.63, 440.00],
        [440.00, 261.63, 349.23, 440.00],
    ]
    strum_times = [0.12, 0.55, 1.00, 1.45, 1.90, 2.35, 2.75]
    for s_idx, t_start in enumerate(strum_times):
        chord = chords[(s_idx // 2) % len(chords)]
        strings = chord if s_idx % 2 == 0 else list(reversed(chord))
        for str_i, f0 in enumerate(strings):
            onset = int(round((t_start + str_i * 0.014) * sr))
            length = min(int(round(0.85 * sr)), n - onset)
            if length <= 64:
                continue
            delay = max(2, int(round(sr / f0)))
            buf = rng.uniform(-1.0, 1.0, size=delay)
            buf -= np.mean(buf)
            pluck = np.zeros(length, dtype=np.float64)
            for i in range(length):
                pluck[i] = buf[i % delay]
                nxt = buf[(i + 1) % delay]
                buf[i % delay] = 0.992 * (0.52 * buf[i % delay] + 0.48 * nxt)
            t_loc = np.arange(length, dtype=np.float64) / sr
            pluck *= np.exp(-t_loc / 0.42)
            peak = float(np.max(np.abs(pluck))) or 1.0
            out[onset : onset + length] += 0.14 * (pluck / peak)
    mono = out.astype(np.float32)
    return np.column_stack([mono, mono])


def _make_pink(
    shape: tuple[int, int],
    sr: int,
    rng: np.random.Generator,
    lowpass_hz: float | None = None,
) -> np.ndarray:
    white = rng.standard_normal(shape)
    freqs = np.fft.rfftfreq(shape[0], d=1.0 / sr)
    scale = 1.0 / np.maximum(freqs, 30.0) ** 0.55
    scale[0] = 0.0
    if lowpass_hz is not None:
        scale *= 1.0 / (1.0 + (freqs / lowpass_hz) ** 12)
    out = np.zeros_like(white)
    for ch in range(shape[1]):
        out[:, ch] = np.fft.irfft(np.fft.rfft(white[:, ch]) * scale, n=shape[0])
    return out / (np.std(out) + 1e-12)


def _make_bandpassed_noise(
    shape: tuple[int, int], sr: int, low_hz: float, high_hz: float, rng: np.random.Generator
) -> np.ndarray:
    white = rng.standard_normal(shape)
    sos = signal.butter(4, [low_hz, high_hz], btype="bandpass", fs=sr, output="sos")
    bp = signal.sosfilt(sos, white, axis=0)
    return bp / (np.std(bp) + 1e-12)


def _rms(arr: np.ndarray) -> float:
    return float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))


def test_clean_ukulele_strumming_is_preserved_without_damage() -> None:
    sr = 48000
    clean = _synth_ukulele(3.2, sr)
    out = process_audio_pipeline(clean, sr, ProcessRequest())

    assert out.actions.broadband_applied_channels == []
    assert out.processing_mode == "bypassed_clean_or_silent"
    assert np.array_equal(out.processed, clean)
    assert float(np.max(np.abs(out.residual))) == 0.0


def test_ukulele_with_loud_fullband_pink_noise_engages_and_reduces_noise() -> None:
    sr = 48000
    rng = np.random.default_rng(1)
    clean = _synth_ukulele(3.2, sr)
    noise = (_make_pink(clean.shape, sr, rng) * (_rms(clean) * 0.7)).astype(np.float32)
    noisy = clean + noise

    out = process_audio_pipeline(noisy, sr, ProcessRequest(strength=0.65))
    assert out.actions.broadband_applied_channels == [1, 2]
    assert out.actions.hpf_applied is False  # HPF not auto-enabled
    assert compute_snr_db(clean, out.processed) > compute_snr_db(clean, noisy) + 2.5
    trans = compute_transient_preservation(clean, out.processed, sr)
    assert trans is not None and trans >= 0.95
    assert np.allclose(out.residual, noisy.astype(np.float64) - out.processed.astype(np.float64), atol=1e-6)


def test_ukulele_with_colored_midband_noise_does_not_false_bypass() -> None:
    """Regression: colored mid-band noise (250-3200 Hz, silent above 4 kHz) must NOT bypass."""
    sr = 48000
    rng = np.random.default_rng(2)
    clean = _synth_ukulele(3.2, sr)
    mid_noise = (
        _make_bandpassed_noise(clean.shape, sr, 250.0, 3200.0, rng) * (_rms(clean) * 0.7)
    ).astype(np.float32)
    noisy = clean + mid_noise

    # Inspect gate directly to verify sub-band detection
    stft = compute_power_stft(noisy[:, :1], sr)
    nf = estimate_noise_floor(stft, noisy.shape[0] / sr, is_silent=False)
    gate = evaluate_broadband_noise_gate(
        stft.freqs,
        nf.broadband_floor_power_psd,
        nf.estimate.broadband_noise_floor_dbfs,
        nf.estimate.sustained_tonal_warning,
        sr,
    )
    assert gate.should_apply is True
    assert any(b.band_id == "mid_1000_4000" and b.triggered for b in gate.subbands)

    out = process_audio_pipeline(noisy, sr, ProcessRequest(strength=0.65))
    assert out.actions.broadband_applied_channels == [1, 2]
    assert not np.array_equal(out.processed, noisy)
    assert compute_snr_db(clean, out.processed) > compute_snr_db(clean, noisy) + 1.5
    trans = compute_transient_preservation(clean, out.processed, sr)
    assert trans is not None and trans >= 0.95


def test_ukulele_with_mic_or_mp3_hf_rolloff_engages_broadband_suppression() -> None:
    sr = 48000
    rng = np.random.default_rng(3)
    clean = _synth_ukulele(3.2, sr)
    rolled_noise = (
        _make_pink(clean.shape, sr, rng, lowpass_hz=11000.0) * (_rms(clean) * 0.65)
    ).astype(np.float32)
    noisy = clean + rolled_noise

    out = process_audio_pipeline(noisy, sr, ProcessRequest(strength=0.65))
    assert out.actions.broadband_applied_channels == [1, 2]
    assert compute_snr_db(clean, out.processed) > compute_snr_db(clean, noisy) + 2.5
    trans = compute_transient_preservation(clean, out.processed, sr)
    assert trans is not None and trans >= 0.95


def test_ukulele_with_rumble_and_background_noise_respects_optional_hpf() -> None:
    sr = 48000
    rng = np.random.default_rng(4)
    clean = _synth_ukulele(3.2, sr)
    pink = _make_pink(clean.shape, sr, rng, lowpass_hz=14000.0) * (_rms(clean) * 0.6)
    rumble = _make_bandpassed_noise(clean.shape, sr, 24.0, 90.0, rng) * (_rms(clean) * 0.5)
    noisy = (clean + pink + rumble).astype(np.float32)

    # Default: HPF stays OFF, broadband engages
    out_default = process_audio_pipeline(noisy, sr, ProcessRequest(strength=0.65))
    assert out_default.actions.hpf_applied is False
    assert out_default.actions.broadband_applied_channels == [1, 2]
    assert compute_snr_db(clean, out_default.processed) > compute_snr_db(clean, noisy) + 2.0

    # With explicit HPF enabled at 100 Hz: even stronger combined rumble + noise reduction
    out_hpf = process_audio_pipeline(
        noisy, sr, ProcessRequest(strength=0.65, hpf_enabled=True, hpf_cutoff_hz=100.0)
    )
    assert out_hpf.actions.hpf_applied is True
    assert out_hpf.actions.broadband_applied_channels == [1, 2]
    assert compute_snr_db(clean, out_hpf.processed) > compute_snr_db(clean, out_default.processed) + 1.5


def test_ukulele_with_nonstationary_speech_traffic_noise_engages_without_false_bypass() -> None:
    sr = 48000
    rng = np.random.default_rng(5)
    clean = _synth_ukulele(3.2, sr)
    n = clean.shape[0]
    t = np.arange(n, dtype=np.float64) / sr
    pink = _make_pink(clean.shape, sr, rng, lowpass_hz=12000.0)
    mod = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(2.0 * math.pi * 0.45 * t)) * (
        0.5 + 0.5 * np.sin(2.0 * math.pi * 3.5 * t)
    )
    sos = signal.butter(4, [280.0, 3200.0], btype="bandpass", fs=sr, output="sos")
    nonstat = signal.sosfilt(sos, pink, axis=0) * mod[:, np.newaxis]
    nonstat = nonstat / (np.std(nonstat) + 1e-12)
    noisy = (clean + nonstat * (_rms(clean) * 0.75)).astype(np.float32)

    out = process_audio_pipeline(noisy, sr, ProcessRequest(strength=0.75))
    # Must NOT auto-bypass as before; engages conservatively on stationary baseline
    assert out.actions.broadband_applied_channels == [1, 2]
    assert compute_snr_db(clean, out.processed) > compute_snr_db(clean, noisy)
    trans = compute_transient_preservation(clean, out.processed, sr)
    assert trans is not None and trans >= 0.95


def test_clean_tonal_silence_and_asymmetric_stereo_preserve_clean_channels() -> None:
    sr = 48000
    t = np.arange(sr * 2, dtype=np.float64) / sr

    # Clean tonal sine & clean sustained vibrato chord still bypass
    clean_sine = (0.25 * np.sin(2.0 * math.pi * 440.0 * t)).astype(np.float32)[:, np.newaxis]
    out_sine = process_audio_pipeline(clean_sine, sr, ProcessRequest())
    assert out_sine.actions.broadband_applied_channels == []
    assert np.array_equal(out_sine.processed, clean_sine)

    # Silence & near-silence (-90 dBFS) bypass
    rng = np.random.default_rng(6)
    near_silent = (rng.standard_normal((sr, 2)) * 3e-5).astype(np.float32)
    out_ns = process_audio_pipeline(near_silent, sr, ProcessRequest())
    assert out_ns.processing_mode == "bypassed_clean_or_silent"
    assert np.array_equal(out_ns.processed, near_silent)

    # Stereo asymmetric: colored mid-band noise ONLY in Left channel, Right channel clean ukulele
    clean_uke = _synth_ukulele(2.5, sr)
    mid_noise_l = (
        _make_bandpassed_noise((clean_uke.shape[0], 1), sr, 250.0, 3200.0, rng)[:, 0]
        * (_rms(clean_uke) * 0.75)
    ).astype(np.float32)
    asym = clean_uke.copy()
    asym[:, 0] += mid_noise_l

    out_asym = process_audio_pipeline(asym, sr, ProcessRequest(strength=0.65))
    assert out_asym.actions.broadband_applied_channels == [1]
    assert out_asym.actions.broadband_skipped_clean_channels == [2]
    # Right channel remains completely untouched
    assert np.array_equal(out_asym.processed[:, 1], clean_uke[:, 1])
    # Left channel improves SNR
    assert compute_snr_db(clean_uke[:, 0], out_asym.processed[:, 0]) > (
        compute_snr_db(clean_uke[:, 0], asym[:, 0]) + 1.5
    )


def test_subband_gate_handles_low_sample_rate_safely() -> None:
    """8 kHz (Nyquist 4 kHz) skips >4 kHz sub-bands cleanly without errors."""
    sr = 8000
    rng = np.random.default_rng(7)
    t = np.arange(sr * 2, dtype=np.float64) / sr
    tone = (0.2 * np.sin(2.0 * math.pi * 440.0 * t)).astype(np.float32)[:, np.newaxis]
    noise = (rng.standard_normal(tone.shape) * 0.03).astype(np.float32)

    out = process_audio_pipeline(tone + noise, sr, ProcessRequest(strength=0.5))
    assert out.processed.shape == tone.shape
    assert out.actions.broadband_applied_channels == [1]
    assert compute_si_sdr_db(tone, out.processed) > compute_si_sdr_db(tone, tone + noise)
