# SONORA â€“ AI Instrument Audio Cleaner
## Project Status Tracker

**Current Stage:** Stage 4 â€” Precision Musical DSP Engine, Playable Comparison & Audio Quality Benchmark Harness (**Completed & Verified**)
**Next Stage:** Stage 5 â€” Optional Pluggable AI Engines & Empirical Model Benchmarking
**Architecture Reference:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (v1.1 â€” Approved & Refined)

> **Policy:** No feature is marked complete unless it has been implemented and verified by automated tests. Unimplemented modules and optional AI engines remain explicitly marked as not implemented. Synthetic benchmark results verify deterministic DSP guardrails and do not prove real-world listening quality.

---

## Stage Progress Overview

| Stage | Milestone | Status | Verification Summary |
| :--- | :--- | :--- | :--- |
| **Stage 1** | Project Scaffolding, Configuration, Health & Studio Shell | **Completed** | Verified & accepted |
| **Stage 2** | Secure Audio Ingestion, Validation, Metadata & WaveSurfer Playback | **Completed** | Verified & accepted |
| **Stage 3** | Noise Analysis, Spectrogram & Frequency Analysis | **Completed** | Verified & accepted |
| **Stage 4** | Precision Musical DSP Engine & Audio Quality Benchmark Harness | **Completed (Audited & Patched)** | Backend: 58/58 pytest passed; Benchmarks: 9/9 scenarios verified; Frontend: `tsc --noEmit`, 12/12 Vitest passed, `vite build` passed |
| **Stage 5** | Optional Pluggable AI Engines & Empirical Model Benchmarking | Not Started | Planned next |
| **Stage 6** | Offline Restoration Studio, Job Queue & A/B/Residual Comparison | Not Started | Planned |
| **Stage 7** | High-Quality Export & Session Management | Not Started | Planned |
| **Stage 8** | Real-Time Mode (AudioWorklet + Binary WebSocket) | Not Started | Planned |
| **Stage 9** | End-to-End Hardening, Listening Audit & Final Documentation | Not Started | Planned |

---

## Stage 4 â€” Verified Deliverables

### Backend Precision Musical DSP (`backend/app/dsp/` & `backend/app/api/processing.py`)
- [x] Conditional zero-phase DC offset removal (only applied when channel mean > `2e-3` / `-54 dBFS`) (`backend/app/dsp/filters.py`)
- [x] Optional conservative zero-phase Butterworth high-pass filter (`20â€“150 Hz`, off by default) (`backend/app/dsp/filters.py`)
- [x] Per-channel evidence-gated, pitch-conflict-safe 50/60 Hz harmonic notch filter bank using sub-bin parabolic peak locking, local-maximum & temporal-steadiness verification, and adaptive Q (`42â€“60`) (`backend/app/dsp/filters.py`)
- [x] Per-channel conservative musical Decision-Directed Wiener broadband suppressor (`backend/app/dsp/broadband.py`) with Nyquist-safe sub-band auto-bypass gate (`150â€“1000 Hz`, `1000â€“4000 Hz`, `4000â€“12000 Hz` joint energy + flatness + sustained-tone guard), clean-channel auto-bypass, harmonic/vibrato peak protection, spectral-flux transient protection, conservative max attenuation cap (`<= 14.5 dB`), and 2D mask smoothing
- [x] Optional/conditional stereo-linked true-peak safety limiter (`backend/app/dsp/limiter.py`, off by default; idle whenever signal stays below ceiling)
- [x] Pipeline orchestrator (`backend/app/dsp/pipeline.py`) preserving native sample rate, channel count, and exact sample count, computing exact unnormalized sample-aligned residual `residual[n] = original[n] - final_processed[n]` AFTER all output-altering stages (including any limiter)
- [x] REST API endpoints (`backend/app/api/processing.py`): `POST /api/v1/sessions/{id}/process` (with SHA-256 parameter caching), `GET /api/v1/sessions/{id}/process`, `GET /api/v1/sessions/{id}/audio/original-aligned` (24-bit PCM sample-aligned WAV for zero-priming-delay A/B & Dry/Wet even on MP3 uploads), `GET /api/v1/sessions/{id}/audio/processed` (24-bit PCM WAV with HTTP Range support), `GET /api/v1/sessions/{id}/audio/residual` (unnormalized 24-bit PCM WAV with HTTP Range support)
- [x] Original uploaded audio (`source.bin`, `original_f32.wav`) strictly preserved read-only
- [x] `/api/v1/health` updated to report `precision_musical_dsp` as `implemented: true, available: true` while keeping all Stage 5 optional AI engines `implemented: false, available: false`
- [x] Automated backend tests verified: **58 passed** (`tests/unit/` + `tests/api/`, including 8 sub-band broadband gate regression tests, benchmark metric regression, and MP3 sample-alignment tests)

### Reproducible Synthetic DSP Benchmark Harness (`benchmarks/`)
- [x] Objective metrics (`benchmarks/metrics.py`): Joint multi-channel Input/Output SNR, Î”SNR, Joint SI-SDR, Î”SI-SDR, independent per-channel SNR & SI-SDR breakdowns, Inputâ†’Output Log-Spectral Distance (dB), Transient Onset Envelope Preservation, Peak/True-Peak, RMS/LUFS delta, and CPU processing time
- [x] All 9 deterministic musical benchmark scenarios (`benchmarks/scenarios.py`, `benchmarks/run_benchmark.py`) generating `benchmarks/results/stage4_dsp_benchmark.json` and `benchmarks/results/stage4_dsp_benchmark.md`

### Frontend Controls & Sample-Synchronized A/B/Dry-Wet/Residual Studio (`frontend/`)
- [x] Sample-synchronized Web Audio API A/B/Dry-Wet/Residual comparison engine with `cancelAndHoldAtTime` click-free 12 ms gain crossfading (`frontend/src/audio/abAudioEngine.ts`)
- [x] Conservative processing controls (`ProcessingControlsPanel.tsx`): strength (`0â€“85%`), dry/wet mix, 50/60 Hz hum toggle, optional HPF toggle + cutoff, optional limiter toggle, bypass toggle, real processing status & error alerts
- [x] Playable comparison deck (`AudioComparisonDeck.tsx`): Original (A) / Cleaned (B) / Live Dry-Wet Mix / Processing Difference (Residual) switcher using sample-aligned WAV streams with mandatory unnormalized residual disclosure, synchronized clickable dual waveforms, honest bypass/applied badges, objective before/after levels, and applied DSP action log
- [x] Automated frontend checks verified: `tsc --noEmit` (0 errors), Vitest **12 passed** (`6 test files`, including direct `AbAudioEngine` sync/blend unit tests and Stage 1â€“3 regression), `vite build` clean

---

## Known Limitations (Stage 4)
- Deterministic CPU DSP excels on steady electrical hum, sub-fundamental rumble (when HPF is enabled), and stationary broadband hiss, but cannot cleanly isolate overlapping non-stationary disturbances (e.g., background human speech or loud passing traffic directly on top of musical notes).
- Synthetic benchmark metrics verify mathematical guardrails and regression stability on controlled mixtures; real-world musical quality must be judged by ear on actual instrument recordings.
- Audio file download/export (Stage 7), optional Stage 5 AI engines (HTDemucs, Mel-Band RoFormer/MDX-Net, experimental DeepFilterNet3), waveform Noise Print region selection & loudness-matched comparison toggle (Stage 6), and real-time microphone AudioWorklet/WebSocket mode (Stage 8) are intentionally deferred to later stages.
- Very long high-sample-rate files run synchronously inside `asyncio.to_thread` with parameter-hash caching; a bounded async job queue with stage progress is planned for Stage 6 when heavier optional Stage 5 AI engines are introduced.
