"""Deterministic synthetic musical benchmark scenarios with clean ground truth."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal

from app.models.schemas import ProcessRequest


@dataclass(frozen=True)
class BenchmarkScenario:
    """Single deterministic benchmark scenario with ground-truth clean reference."""

    id: str
    title: str
    description: str
    sample_rate: int
    clean: np.ndarray  # float32 (frames, channels)
    noisy_input: np.ndarray  # float32 (frames, channels)
    request: ProcessRequest
    is_clean_reference: bool


def _harmonic_phrase(
    duration_s: float,
    sr: int,
    notes_hz: list[float],
    channels: int = 1,
    amp: float = 0.25,
) -> np.ndarray:
    n = int(round(duration_s * sr))
    out = np.zeros(n, dtype=np.float64)
    seg_len = n // len(notes_hz)
    for idx, f0 in enumerate(notes_hz):
        start = idx * seg_len
        end = n if idx == len(notes_hz) - 1 else (idx + 1) * seg_len
        t = np.arange(end - start, dtype=np.float64) / sr
        env = (1.0 - np.exp(-t / 0.012)) * np.exp(-t / 0.55)
        note = np.zeros_like(t)
        for h in range(1, 7):
            if f0 * h < sr * 0.45:
                note += (1.0 / (h ** 1.15)) * np.sin(2.0 * math.pi * f0 * h * t)
        out[start:end] = amp * env * note
    mono = out.astype(np.float32)
    return np.column_stack([mono] * channels)


def _plucked_string_sequence(
    duration_s: float, sr: int, freqs_hz: list[float], rng: np.random.Generator
) -> np.ndarray:
    """Synthesize sharp-attack plucked notes (Karplus-Strong inspired) with natural decay."""
    n = int(round(duration_s * sr))
    out = np.zeros(n, dtype=np.float64)
    step = n // len(freqs_hz)

    for idx, f0 in enumerate(freqs_hz):
        start = idx * step
        length = min(int(0.85 * sr), n - start)
        delay = max(2, int(round(sr / f0)))
        buf = rng.uniform(-1.0, 1.0, size=delay)
        buf -= np.mean(buf)
        pluck = np.zeros(length, dtype=np.float64)
        for i in range(length):
            pluck[i] = buf[i % delay]
            nxt = buf[(i + 1) % delay]
            buf[i % delay] = 0.994 * 0.5 * (buf[i % delay] + nxt)
        # Normalize peak per pluck to consistent musical level
        peak = float(np.max(np.abs(pluck))) or 1.0
        out[start : start + length] += 0.35 * (pluck / peak)

    return out.astype(np.float32)[:, np.newaxis]


def _sustained_vibrato_strings(duration_s: float, sr: int, f0: float = 293.66) -> np.ndarray:
    n = int(round(duration_s * sr))
    t = np.arange(n, dtype=np.float64) / sr
    env = np.minimum(1.0, t / 0.08) * np.minimum(1.0, (duration_s - t) / 0.08)
    vib_phase = 2.0 * math.pi * f0 * t + (0.013 * f0 / 5.5) * np.sin(2.0 * math.pi * 5.5 * t)
    mono = np.zeros(n, dtype=np.float64)
    for h in range(1, 9):
        mono += (0.2 / (h ** 1.1)) * np.sin(h * vib_phase)
    wave = (env * mono).astype(np.float32)
    return np.column_stack([wave, wave])


def build_all_scenarios(seed: int = 2026) -> list[BenchmarkScenario]:
    """Construct all 9 deterministic Stage 4 benchmark scenarios."""
    rng = np.random.default_rng(seed)
    sr = 48000

    scenarios: list[BenchmarkScenario] = []

    # 1. Clean sustained musical tone
    t2 = np.arange(sr * 2, dtype=np.float64) / sr
    clean_tone = (0.25 * np.sin(2.0 * math.pi * 220.0 * t2)).astype(np.float32)[:, np.newaxis]
    scenarios.append(
        BenchmarkScenario(
            id="clean_sustained_tone",
            title="Clean sustained musical tone (A3 = 220 Hz)",
            description="Already clean sustained tone; should auto-bypass with zero degradation.",
            sample_rate=sr,
            clean=clean_tone,
            noisy_input=clean_tone.copy(),
            request=ProcessRequest(),
            is_clean_reference=True,
        )
    )

    # 2. Musical tone with vibrato and harmonics (clean)
    vibrato = _sustained_vibrato_strings(2.5, sr, f0=293.66)
    scenarios.append(
        BenchmarkScenario(
            id="vibrato_harmonics_clean",
            title="Clean bowed string with vibrato & 8 harmonics",
            description="Continuous sustained vibrato note; must not be confused with noise.",
            sample_rate=sr,
            clean=vibrato,
            noisy_input=vibrato.copy(),
            request=ProcessRequest(),
            is_clean_reference=True,
        )
    )

    # 3. Plucked / percussive instrument with sharp attacks and decay (clean + light hiss variant)
    plucks = _plucked_string_sequence(2.8, sr, [196.0, 246.94, 293.66, 392.0], rng)
    scenarios.append(
        BenchmarkScenario(
            id="plucked_percussive_transients",
            title="Plucked string sequence with sharp attacks & decay",
            description="Tests attack transient preservation on sharp plucks.",
            sample_rate=sr,
            clean=plucks,
            noisy_input=plucks.copy(),
            request=ProcessRequest(),
            is_clean_reference=True,
        )
    )

    # 4. Low-frequency musical bass notes (E1=41.2, G1=49.0, A1=55.0, B1=61.74 Hz)
    bass_clean = _harmonic_phrase(
        duration_s=2.8, sr=sr, notes_hz=[41.2, 49.0, 55.0, 61.74], channels=1, amp=0.28
    )
    scenarios.append(
        BenchmarkScenario(
            id="low_freq_bass_notes",
            title="Low-frequency bass notes (E1–B1 near 50/60 Hz)",
            description="Low fundamentals near mains frequencies; must not notch or remove bass.",
            sample_rate=sr,
            clean=bass_clean,
            noisy_input=bass_clean.copy(),
            request=ProcessRequest(hum_reduction_enabled=True, hpf_enabled=False),
            is_clean_reference=True,
        )
    )

    # 5. Clean recording mixed with 60 Hz hum + harmonics
    guitar_clean = _harmonic_phrase(
        duration_s=2.4, sr=sr, notes_hz=[164.81, 220.0, 293.66, 329.63], channels=2, amp=0.22
    )
    t_g = np.arange(guitar_clean.shape[0], dtype=np.float64) / sr
    hum_60 = (
        0.040 * np.sin(2.0 * math.pi * 60.0 * t_g)
        + 0.024 * np.sin(2.0 * math.pi * 120.0 * t_g)
        + 0.015 * np.sin(2.0 * math.pi * 180.0 * t_g)
        + 0.008 * np.sin(2.0 * math.pi * 240.0 * t_g)
    ).astype(np.float32)
    guitar_plus_hum = guitar_clean + np.column_stack([hum_60, hum_60])
    scenarios.append(
        BenchmarkScenario(
            id="music_plus_60hz_hum",
            title="Acoustic phrase + 60 Hz electrical hum & harmonics",
            description="Tests evidence-gated pitch-safe 60 Hz harmonic notch without harming notes.",
            sample_rate=sr,
            clean=guitar_clean,
            noisy_input=guitar_plus_hum,
            request=ProcessRequest(strength=0.6, hum_reduction_enabled=True),
            is_clean_reference=False,
        )
    )

    # 6. Clean recording mixed with broadband hiss (> 4 kHz)
    pluck_clean = _plucked_string_sequence(2.4, sr, [220.0, 277.18, 329.63, 440.0], rng)
    white = rng.standard_normal(pluck_clean.shape).astype(np.float64)
    sos_hp = signal.butter(4, 4200.0, btype="highpass", fs=sr, output="sos")
    hiss = signal.sosfilt(sos_hp, white, axis=0)
    hiss = (hiss / np.std(hiss) * 0.018).astype(np.float32)
    scenarios.append(
        BenchmarkScenario(
            id="music_plus_broadband_hiss",
            title="Plucked phrase + broadband high-frequency hiss (>4.2 kHz)",
            description="Tests conservative broadband Wiener suppression & transient preservation.",
            sample_rate=sr,
            clean=pluck_clean,
            noisy_input=pluck_clean + hiss,
            request=ProcessRequest(strength=0.65, hum_reduction_enabled=True),
            is_clean_reference=False,
        )
    )

    # 7. Clean recording mixed with low-frequency rumble (25-85 Hz) with optional HPF enabled
    melody_clean = _harmonic_phrase(
        duration_s=2.4, sr=sr, notes_hz=[261.63, 329.63, 392.0, 523.25], channels=1, amp=0.22
    )
    white_r = rng.standard_normal(melody_clean.shape).astype(np.float64)
    sos_bp = signal.butter(4, [22.0, 85.0], btype="bandpass", fs=sr, output="sos")
    rumble = signal.sosfilt(sos_bp, white_r, axis=0)
    rumble = (rumble / np.std(rumble) * 0.045).astype(np.float32)
    scenarios.append(
        BenchmarkScenario(
            id="music_plus_low_freq_rumble",
            title="Mid-register phrase + low-frequency rumble (22–85 Hz)",
            description="Tests optional conservative HPF (95 Hz) removing sub-fundamental rumble.",
            sample_rate=sr,
            clean=melody_clean,
            noisy_input=melody_clean + rumble,
            request=ProcessRequest(strength=0.45, hpf_enabled=True, hpf_cutoff_hz=95.0),
            is_clean_reference=False,
        )
    )

    # 8. Stereo instrument recording with disturbance in ONLY one channel (Left)
    stereo_clean = _harmonic_phrase(
        duration_s=2.4, sr=sr, notes_hz=[220.0, 261.63, 329.63, 440.0], channels=2, amp=0.22
    )
    t_s = np.arange(stereo_clean.shape[0], dtype=np.float64) / sr
    hum_50_l = (
        0.035 * np.sin(2.0 * math.pi * 50.0 * t_s)
        + 0.020 * np.sin(2.0 * math.pi * 100.0 * t_s)
        + 0.012 * np.sin(2.0 * math.pi * 150.0 * t_s)
    ).astype(np.float32)
    stereo_noisy = stereo_clean.copy()
    stereo_noisy[:, 0] = stereo_noisy[:, 0] + hum_50_l
    scenarios.append(
        BenchmarkScenario(
            id="stereo_single_channel_disturbance",
            title="Stereo instrument with 50 Hz hum in Left channel only",
            description="Tests per-channel processing: cleans Left while leaving Right untouched.",
            sample_rate=sr,
            clean=stereo_clean,
            noisy_input=stereo_noisy,
            request=ProcessRequest(strength=0.6, hum_reduction_enabled=True),
            is_clean_reference=False,
        )
    )

    # 9. Near-clean recording (-80 dBFS ambient room bed)
    near_clean_base = _harmonic_phrase(
        duration_s=2.0, sr=sr, notes_hz=[293.66, 369.99, 440.0], channels=2, amp=0.22
    )
    tiny_floor = (rng.standard_normal(near_clean_base.shape) * 1.0e-4).astype(np.float32)
    scenarios.append(
        BenchmarkScenario(
            id="near_clean_recording",
            title="Near-clean recording (-80 dBFS quiet ambient bed)",
            description="Should auto-bypass or apply minimal processing to preserve natural tone.",
            sample_rate=sr,
            clean=near_clean_base,
            noisy_input=near_clean_base + tiny_floor,
            request=ProcessRequest(),
            is_clean_reference=True,
        )
    )

    return scenarios
