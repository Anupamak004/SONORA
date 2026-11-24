# SONORA Stage 5 (Option B) — Cloud GPU Feasibility Benchmark: CLAPSep vs. AudioSep

This folder contains the self-contained Google Colab feasibility benchmark for evaluating whether **CLAPSep** and/or **AudioSep** can extract ukulele strumming from recordings containing unwanted environmental sounds — **without installing AI dependencies or downloading multi-gigabyte checkpoints onto your 8 GB RAM local laptop**.

> **Status:** Prepared and hardened for review. Nothing has been executed, downloaded, or integrated into SONORA's backend or frontend. Neither model is claimed to work for ukulele extraction until real and synthetic audio outputs are measured and evaluated by human listening.

---

## Files in This Folder

| File | Purpose |
| :--- | :--- |
| [sonora_stage5_clapsep_vs_audiosep_benchmark.ipynb](./sonora_stage5_clapsep_vs_audiosep_benchmark.ipynb) | Hardened Google Colab notebook covering pre/post CUDA checks, fail-closed CPU fallback, pinned Git/HF revisions, SHA-256 + exact byte-size gates, scoped checkpoint loading, genuine peak RAM/VRAM monitoring, real ukulele upload, optional real human speech interference, synthetic mixtures, validated AudioSep chunking, exact audio/metric consistency, and downloadable ZIP report bundle. |
| [README.md](./README.md) | Setup, security model, pinned provenance/trust table, execution guide, metric definitions, synthetic limitations, and listening rubric. |

---

## Security & Trust Model (Read Before Running)

1. **Use a Fresh Isolated Colab Runtime:** Run this notebook ONLY in a fresh, disposable Google Colab runtime with **no sensitive Google Drive mounts, API keys, or personal credentials**.
2. **No Global Pickle Override:** The notebook does **not** set `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1`.
   - It attempts `torch.load(..., weights_only=True)` first.
   - Only if a **pre-verified checkpoint path** (exact byte size + exact expected SHA-256 already validated) fails `weights_only=True` because of legacy Python objects in LAION-CLAP (`.pt`) or PyTorch Lightning (`.ckpt`), a tightly scoped context manager (`scoped_trusted_torch_load`) permits `weights_only=False` strictly for that exact resolved path, records the fallback in `checkpoint_load_audit.json`, and restores `torch.load` in `finally:`.
   - User-uploaded audio files are decoded only by `librosa`/`soundfile` and are **never** passed to `torch.load`.
3. **Residual Security Risk:** Unrestricted pickle deserialization can execute arbitrary code if an upstream checkpoint was compromised prior to the pinned revision. Because upstream authors did not publish independent out-of-band cryptographic signatures (PGP/Sigstore), the SHA-256 checks verify transport and revision integrity against Hugging Face LFS OIDs — **not** independent cryptographic authentication.

---

## Pinned Revisions, Exact Sizes, Expected Hashes & Authentication Status

| Model | Pinned Git Commit | Pinned HF Space Revision | Artifact File | Exact Bytes | Expected SHA-256 (HF LFS OID) | Authentication Status | License |
| :--- | :--- | :--- | :--- | ---: | :--- | :--- | :--- |
| **CLAPSep** | `Aisaka0v0/CLAPSep` @ `bcc768e2064a9bf5a21c0ed0fa23e99fd0cc9aa4` | `AisakaMikoto/CLAPSep` @ `e3c73653fa9aadcddbcc3b5e967182a573589e81` | `model/best_model.ckpt` | `177,818,986` | `6fcc8dbcd7174af86266cf16b4105eced0802352762f81dbfefdce29af3dba04` | **Not cryptographically authenticated** (same-host HF LFS OID only) | MIT |
| **CLAPSep (CLAP)** | *(same)* | *(same)* | `model/music_audioset_epoch_15_esc_90.14.pt` | `2,352,471,003` | `fae3e9c087f2909c28a09dc31c8dfcdacbc42ba44c70e972b58c1bd1caf6dedd` | **Cross-matched to upstream `lukewys/laion_clap@b3708341` on HF; not independently signed** | CC0-1.0 |
| **AudioSep** | `Audio-AGI/AudioSep` @ `944583f18b84589dc965de3ad77525c945334252` | `Audio-AGI/AudioSep` @ `0807a713283035d8b0d0628f1b8e3d6580459f7b` | `checkpoint/audiosep_base_4M_steps.ckpt` | `1,264,844,076` | `f8cda01bfd0ebd141eef45d41db7a3ada23a56568465840d3cff04b8010ce82c` | **Not cryptographically authenticated** (same-host HF LFS OID only) | MIT |
| **AudioSep (CLAP)** | *(same)* | *(same)* | `checkpoint/music_speech_audioset_epoch_15_esc_89.98.pt` | `2,352,471,003` | `51c68f12f9d7ea25fdaaccf741ec7f81e93ee594455410f3bca4f47f88d8e006` | **Cross-matched to upstream `lukewys/laion_clap@b3708341` on HF; not independently signed** | CC0-1.0 |

Verification runs **before** any model loading; any byte-size or SHA-256 mismatch aborts immediately.

---

## Step-by-Step Google Colab Execution Guide

1. **Upload the notebook to a fresh Google Colab runtime:**
   - Open [Google Colab](https://colab.research.google.com/) → **File → Upload notebook** → select `sonora_stage5_clapsep_vs_audiosep_benchmark.ipynb`.
   - Select **Runtime → Change runtime type → Hardware accelerator → T4 GPU** (or L4/A100 if available).
2. **Section 1 — Hardware Check & Fail-Closed CPU Policy:**
   - Records GPU model, VRAM, CPU cores, free disk space (`>= 12 GB`), pre-install `torch` / `torchaudio` / CUDA versions, and available RAM (via `psutil` or `/proc/meminfo`).
   - CPU fallback is **disabled by default** (`ALLOW_CPU_FALLBACK = False`) and **fails closed** if available RAM cannot be measured or is `< 10.0 GB`.
3. **Section 2 — Pinned Repo Checkouts, Dependency Install & CUDA Integrity Guard:**
   - Clones and checks out exact pinned Git commit hashes (asserting `git rev-parse HEAD`).
   - Pins pre-existing `torch` and `torchaudio` versions as `pip` constraints, verifies in a fresh subprocess that `torch`, `torchaudio`, and CUDA availability remain intact (aborting if altered/broken), and saves full `pip freeze` + pinned commits into `environment_manifest.json`.
   - *Reproducibility note:* Version ranges in `pip` do not guarantee identical replay across future Colab images; use the captured `environment_manifest.json` snapshot for exact environment records.
4. **Section 3 — Immutable Checkpoint Download & Integrity Gate:**
   - Downloads checkpoints only when executed, strictly at pinned HF Space revisions (`~5.86 GB` total; toggle `DOWNLOAD_CLAPSEP` / `DOWNLOAD_AUDIOSEP` independently if desired), verifies exact byte sizes and expected SHA-256 digests, and initializes the scoped loader.
5. **Section 4 — Optional Real Ukulele Recording Upload:**
   - Upload your recovered original ukulele recording (`.mp3`/`.wav`/`.flac`). Original bytes are preserved unchanged with SHA-256 verification.
   - Because the earlier expired SONORA Stage 4 session output is missing, **no Stage 4 reference is fabricated or substituted**.
6. **Section 5A & 5B — Synthetic Mixtures & Optional Real Human Speech Interference:**
   - **5A (Synthetic):** Clean 48 kHz ukulele regression guard + 6 synthetic interference scenarios (synthetic speech proxy, traffic, fan, wind, pink noise, adversarial acoustic guitar) calibrated at **0 dB** and **+6 dB SNR**, with separate `clean`, `noise`, and `mixture` files saved.
   - **5B (Optional Real Human Speech):** Set `UPLOAD_REAL_SPEECH = True` (or `LOCAL_REAL_SPEECH_PATH`) to mix your own clean human speech recording with the clean ukulele reference at **0 dB** and **+6 dB SNR**. Never silently downloads copyrighted or unlicensed speech. Preserves the uploaded speech unchanged, decodes a separate working copy, and tags rows `interference_source="real_user_speech"` vs. `"synthetic_dsp_proxy"`.
7. **Section 6 — Peak Memory Monitor, Audio/Metric Consistency & Metrics:**
   - `PeakMemoryMonitor` polls process RSS every 20 ms during model loading and inference (plus Linux `/proc/self/status` `VmHWM` and CUDA `max_memory_allocated` / `max_memory_reserved`), reporting `ram_before_load_mb`, `ram_after_load_mb`, `peak_ram_during_load_mb`, `peak_ram_during_inference_mb`, `gpu_peak_allocated_mb`, and `gpu_peak_reserved_mb` separately.
   - `finalize_audition_waveform` produces the exact 32-bit float audition waveform **before** computing metrics and residuals, logging exact clipping telemetry (`raw_peak_linear`, `was_clipped`, `clipped_samples`, `clipped_fraction`, `gain_adjustment_db`) and saving unmodified `*_raw_f32.wav`, exact `*_audition.wav` (`FLOAT`), and aligned `*_diff_residual.wav` (`FLOAT`). All objective metrics describe the exact waveform auditioned.
8. **Section 7A & 7B — Sequential Evaluation & AudioSep Chunk Validation:**
   - **7A (CLAPSep):** Runs all 5 positive / positive+negative queries, then unloads CLAPSep completely.
   - **7B (AudioSep):** Runs equivalent **positive-only** queries (`N/A (unsupported)` for negative prompts). Bypasses upstream `models/resunet.py:chunk_inference` (verified defects in commit `944583f18b`: returns zeros for `<= 5 s`, double-runs inside its `while` loop, returns `float64` `[1, L]`) with a clean overlap-discard chunker (`_run_audiosep_validated_chunked`) and runs an explicit **short (`3.5 s`) + long (`13.5 s`) validation self-test** verifying `dtype`, `ndim`, sample count, zero-sample alignment lag, and chunk-seam continuity before benchmarking.
9. **Section 8 & 9 — Listening Deck, Tables & Downloadable ZIP:**
   - Inline Colab audio players use `normalize=False` so true relative levels are heard accurately.
   - Exports `metrics_calibrated.csv`, `metrics_real.csv`, `model_load_telemetry.csv`, `checkpoint_load_audit.json`, `audiosep_chunk_validation.json`, `environment_manifest.json`, `checkpoint_manifest.json`, `listening_scorecard_template.csv`, `stage5_cloud_benchmark_report.md`, and `sonora_stage5_cloud_benchmark_results.zip`.

---

## Implemented Metrics & Synthetic Limitations

### Metrics Actually Computed (Aligned Across Code & Docs)
- **Dual-rate Joint SNR & $\Delta\text{SNR}$** and **Joint SI-SDR & $\Delta\text{SI-SDR}$** (at both **32 kHz** pure separation and **48 kHz** full band, exposing the 16 kHz Nyquist cap)
- **Multi-Resolution Log-Spectral Distance (`mr_lsd_32k_db`, `mr_lsd_48k_db`)** across `n_fft ∈ {512, 1024, 2048}`
- **Active-Frame Spectral Correlation (`active_frame_spectral_corr`)** — mean Pearson correlation of log-magnitude spectra on ukulele-active frames
- **Target Level Retention (`target_level_retention_db`)** — active-frame RMS difference vs. clean target (`0.0 dB` = exact level retained)
- **Strumming Attack / Onset Preservation (`onset_preservation`, `crest_delta_db`)** — high-resolution spectral-flux onset Pearson correlation (`n_fft=512`, `hop=128`) + crest-factor change
- **Harmonic Preservation (`harmonic_cosine_sim`, `harmonic_centroid_shift_hz`)** — cosine similarity & centroid shift in `250–6000 Hz` on active frames
- **Background Noise Suppression (`noise_projection_suppression_db`, `gap_noise_suppression_db`)** — orthogonal known-noise projection drop + inter-strum silent-gap RMS drop
- **Resource & Latency Telemetry** — load time, inference time, Real-Time Factor (RTF), `ram_before_load_mb`, `ram_after_load_mb`, `peak_ram_during_load_mb`, `peak_ram_during_inference_mb`, `gpu_peak_allocated_mb`, `gpu_peak_reserved_mb`
- **Processing Difference / Residual (`*_diff_residual.wav`)** — sample-aligned unnormalized `input_aligned - audition_output` (diagnostic difference only — **NOT** guaranteed pure noise)

### Limitations of Synthetic Signals vs. Real-World Audio
- **Synthetic ukulele (`synthesize_clean_ukulele`):** Additive modal harmonics + bandpass finger clicks approximate re-entrant GCEA strumming cleanly for deterministic ground-truth math, but lack real wooden body resonances, fretboard/finger noise, player micro-timing, room early reflections, and microphone coloration. Neural models trained on real AudioSet/YouTube recordings may respond differently to synthetic ukulele than to a real microphone capture.
- **Synthetic interference vs. real-world interference:** Synthetic speech/traffic/fan/wind proxies lack true human phonetics, reverberation, and acoustic room coupling. Use synthetic metrics as controlled diagnostics, and weight **real-speech mixtures (Section 5B)** and **real ukulele recordings (Section 4)** heavily in your final recommendation.
