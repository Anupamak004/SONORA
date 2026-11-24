# SONORA – AI Instrument Audio Cleaner
## Technical Architecture Document (v1.1 — Approved)

> **Architectural Principle:** Musical fidelity and instrument preservation always take priority over aggressive noise removal. An output with lower measured noise floor but smeared transients, dulled overtones, altered pitch/harmonics, or spectral gating artifacts is considered a **failed** result. SONORA never claims perfect noise removal and explicitly distinguishes between **detected noise**, **estimated noise**, and **noise actually removed**.

---

## 1. Overall System Architecture

SONORA is a **local-first, modular full-stack audio processing application** built with a React/TypeScript Web Audio studio frontend and a Python/FastAPI signal-processing & modular AI backend.

**Precision Musical DSP** serves as the primary foundation for both offline and real-time processing. The entire core application must remain **100% functional offline and in real time without downloading or installing any AI models**. Optional AI engines are layered in Stage 5 behind a strict pluggable interface with clearly documented scope, capabilities, and empirical benchmark gates.

Development prioritizes a **complete, verified offline restoration workflow (Stages 1–7)** before implementing complex real-time streaming processing (Stage 8).

---

## 2. Frontend Architecture

- **Stack:** React 18+, TypeScript (strict), Vite, Tailwind CSS, WaveSurfer.js (Stage 2+), Web Audio API (Stage 6+), AudioWorklet (Stage 8).
- **Visual Direction:** Minimal dark audio studio workspace with tabular monospace readouts, clear waveform + spectrogram/PSD visualization, subtle functional accents, and zero fake progress bars.
- **Core Studio Fidelity Features:**
  - Zoomable waveform with **optional** Noise Print region selection.
  - **Spectrogram & Frequency Analysis** view comparing Original, Estimated Noise Floor, and Cleaned spectra.
  - Glitch-free synchronized **A/B and Sample-Aligned Residual ("Removed Difference")** listening, with explicit disclosure that residual contains all processing differences and may include some instrument content.
  - **Separate, Optional Loudness Matching** (ITU-R BS.1770 LUFS) strictly decoupled from core denoising.

---

## 3. Backend Architecture

- **Stack:** Python 3.11+, FastAPI, Pydantic Settings, NumPy, SciPy, Librosa, SoundFile, FFmpeg/FFprobe (Stages 1–4); optional PyTorch/ONNX Runtime in Stage 5.
- **Strict Modular Separation:** `core/` (config, logging, exceptions), `models/` (schemas, instrument profiles), `api/` (thin REST/WS routers including `processing.py`), `audio/` (validator, loader, exporter, loudness, waveform), `analysis/` (Blackman-Harris multi-resolution STFT, silence-free Minimum Statistics + inter-harmonic valley noise-floor estimation, calibrated spectral indicators, bounded spectrogram & PSD curves), `dsp/` (Stage 4 Precision Musical DSP: conditional DC removal, optional zero-phase Butterworth HPF, per-channel evidence-gated pitch-safe 50/60 Hz harmonic notch, per-channel Decision-Directed musical Wiener suppressor with harmonic/transient protection & attenuation caps, optional conditional true-peak limiter, and exact post-limiter sample-aligned residual), `ai/` (optional Stage 5 pluggable engine registry), `realtime/` (Stage 8 binary WS protocol & streaming OLA), `services/` (scoped temp session store, TTL cleaner, parameter-hash caching).

---

## 4. Audio Processing Pipeline & Fidelity Safeguards

1. **Clean-Recording Pass-Through Safeguard:** Already-clean recordings pass through with minimal unnecessary alteration.
2. **Configurable Instrument-Aware Filtering & Alternate/Extended-Range Support:** User-configurable high-pass cutoffs and fundamental/harmonic frequency protection per instrument profile (`general`, `acoustic_guitar`, `piano`, `bowed_strings`, `wind_brass`, `percussion`, `bass`), explicitly accommodating alternate tunings (e.g., Drop D/C guitar) and extended-range instruments (e.g., 7/8-string guitars, 5/6-string basses down to B0 = 30.87 Hz).
3. **Pitch-Conflict-Safe 50/60 Hz Hum Removal:** Verifies persistent narrowband hum harmonics and adapts Q/depth to avoid damaging overlapping musical fundamentals or harmonics.
4. **Automatic Silence-Free Noise Estimation (With Sustained-Tone Safeguards) & Optional Noise Print:** Estimates noise spectrum continuously even without silent regions, while explicitly treating Minimum Statistics as an **estimate** that can confuse long sustained musical tones with stationary noise — guarded by conservative confidence checks, tonality/harmonic protection, and capped suppression; optional waveform Noise Print refines estimation when provided.
5. **Optional / Conditional True-Peak Limiter & Post-Limiter Exact Residual:** True-peak limiting is optional/conditional (engaged only when needed to prevent clipping above `-1.0 dBTP` or when explicitly requested, never altering clean dynamics unnecessarily). Sample-aligned residual (`residual[n] = original[n] - final_cleaned[n]`) is always computed **after** all processing stages including any limiter.
6. **Clear Separation of Metrics:** Explicitly distinguishes *Detected Noise Indicators*, *Estimated Noise Floor*, and *Sample-Aligned Removed Difference*.
7. **Separate Optional Loudness Matching:** Core denoising never forces makeup gain; LUFS matching is optional during playback A/B and export.

---

## 5. AI Model Strategy & Evaluation

- **Precision Musical DSP:** Primary offline & real-time engine. Zero AI downloads required.
- **HTDemucs (`htdemucs`):** Optional Stage 5 **musical stem-separation engine** (specifically for background speech/vocal interference), NOT a general-purpose environmental noise remover.
- **Mel-Band RoFormer / MDX-Net Denoise (ONNX):** Optional Stage 5 offline full-band music denoiser (heavier compute; verified checkpoints only).
- **DeepFilterNet3:** Strictly **experimental** in Stage 5 unless real instrument benchmarks demonstrate acceptable musical fidelity.
- **RNNoise:** **Negative benchmark control only** — never recommended for musical instruments.
- **Evaluation:** Combines controlled synthetic benchmarks, real instrument recordings, and structured listening evaluations.

---

## 6. Real-Time Processing (Stage 8)

- Disables browser speech DSP (`echoCancellation: false`, `noiseSuppression: false`, `autoGainControl: false`).
- Makes microphone `channelCount` and `sampleRate` **configurable**, and inspects actual granted settings via `MediaStreamTrack.getSettings()` and `audioContext.sampleRate` rather than assuming requested constraints were honored.
- Defaults output monitoring to OFF with headphone feedback warning.
- Dual-tier engine: Tier 1 Local AudioWorklet DSP (measurable target < 15–25 ms) and Tier 2 Binary WebSocket Streaming Backend (measurable target 45–90 ms). Latency figures are **measurable targets**, reported live in UI telemetry, never guaranteed.

---

## 7. Security, Performance & Testing

- **Security:** Never trust uploaded filenames/extensions; validate magic bytes + `ffprobe`; enforce upload size, duration, and decoded PCM decompression-bomb caps; `subprocess(..., shell=False)`; UUID-scoped temp storage with TTL cleanup.
- **Performance:** Non-blocking worker pool for CPU-heavy processing; `float32` native-SR processing; lazy optional AI loading; zero-allocation AudioWorklet ring buffers.
- **Testing:** `pytest` unit/API/audio-quality regression suites + `vitest` frontend unit/component tests + real-instrument listening protocol.

---

## 8. Nine-Stage Roadmap (Offline-First)

1. Stage 1 — Project Scaffolding, Configuration, Health & Studio Shell
2. Stage 2 — Secure Audio Ingestion, Validation, Metadata & Playback
3. Stage 3 — Noise Analysis, Spectrogram & Frequency Analysis
4. Stage 4 — Precision Musical DSP Engine & Audio Quality Benchmark Harness
5. Stage 5 — Optional Pluggable AI Engines & Empirical Model Benchmarking
6. Stage 6 — Offline Restoration Studio, Job Queue & A/B/Residual Comparison
7. Stage 7 — High-Quality Export & Session Management
8. Stage 8 — Real-Time Mode (AudioWorklet + Binary WebSocket)
9. Stage 9 — End-to-End Hardening, Listening Audit & Final Documentation
