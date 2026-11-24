# SONORA – AI Instrument Audio Cleaner

SONORA is a local-first web application designed to remove unwanted environmental background noise (hum, wind, fan noise, broadband hiss, static, traffic, and background speech) from musical instrument recordings while prioritizing **musical fidelity** — preserving pitch, harmonics, timbre, transients, sustain, quiet passages, and dynamic range.

## Architecture & Principles

- **Precision Musical DSP First:** Core offline and real-time noise reduction runs on deterministic, music-aware DSP (instrument-aware high-pass filtering with fundamental/harmonic protection, pitch-safe 50/60 Hz harmonic hum removal, silence-free noise floor estimation, optional waveform Noise Print, and transient-preserving MMSE-LSA suppression). The core application operates fully without downloading or installing AI models.
- **Modular Optional AI (Stage 5):** Optional offline AI engines (HTDemucs for vocal/speech stem separation, optional ONNX music denoising models, and benchmark-gated experimental DeepFilterNet3) plug into a uniform engine interface and are evaluated empirically on real and synthetic instrument recordings.
- **Honest Diagnostics:** SONORA explicitly separates **detected noise indicators**, **estimated noise floor**, and **sample-aligned removed difference (residual)**, and never claims perfect noise removal.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the complete technical architecture and [PROJECT_STATUS.md](PROJECT_STATUS.md) for verified implementation status across stages.

## Prerequisites

- **Python** 3.11+ (tested on Python 3.13)
- **Node.js** 20+ and **npm** 10+
- **FFmpeg / FFprobe** (recommended for MP3 decoding/encoding and container probing; WAV/FLAC core remains usable if absent)

## Quick Start (Current: Stage 4 — Precision Musical DSP, Playable Comparison & Benchmarks)

### 1. Configure Environment
```powershell
Copy-Item .env.example .env
```

### 2. Backend Setup & Run
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. Frontend Setup & Run
```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173` in your browser.

### 4. Running Tests & Synthetic DSP Benchmarks
```powershell
# Backend unit & API tests
cd backend
.\.venv\Scripts\pytest.exe

# Reproducible Stage 4 synthetic DSP benchmark harness (from repository root)
backend\.venv\Scripts\python.exe benchmarks\run_benchmark.py

# Frontend typecheck, Vitest component/unit tests, and build
cd frontend
npm run typecheck
npm test
npm run build
```
