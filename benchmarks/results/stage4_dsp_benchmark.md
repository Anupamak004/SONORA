# SONORA Stage 4 — Precision Musical DSP Synthetic Benchmark Report

> **Note:** These results are generated from **deterministic synthetic signals and controlled noise mixtures** for regression verification. They do **not** replace listening tests on real musical instrument recordings. SNR and SI-SDR are computed **jointly** across all channels (per-channel breakdowns are included in the JSON report).

| Scenario | Mode | In SNR | Out SNR | ΔSNR | In→Out SI-SDR | ΔSI-SDR | In→Out LSD (dB) | Transients | Time (ms) |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Clean sustained musical tone (A3 = 220 Hz) | `bypassed_clean_or_silent` | 120.00 dB | 120.00 dB | N/A | 120.00→120.00 dB | N/A | 0.00→0.00 | 1.0000 | 52.9 |
| Clean bowed string with vibrato & 8 harmonics | `bypassed_clean_or_silent` | 120.00 dB | 120.00 dB | N/A | 120.00→120.00 dB | N/A | 0.00→0.00 | 1.0000 | 162.3 |
| Plucked string sequence with sharp attacks & decay | `bypassed_clean_or_silent` | 120.00 dB | 120.00 dB | N/A | 120.00→120.00 dB | N/A | 0.00→0.00 | 1.0000 | 85.5 |
| Low-frequency bass notes (E1–B1 near 50/60 Hz) | `bypassed_clean_or_silent` | 120.00 dB | 120.00 dB | N/A | 120.00→120.00 dB | N/A | 0.00→0.00 | 1.0000 | 82.7 |
| Acoustic phrase + 60 Hz electrical hum & harmonics | `applied` | 10.06 dB | 24.26 dB | 14.20 dB | 10.05→24.25 dB | 14.20 dB | 3.97→2.59 | 0.9834 | 154.2 |
| Plucked phrase + broadband high-frequency hiss (>4.2 kHz) | `applied` | 7.84 dB | 14.19 dB | 6.35 dB | 7.84→14.06 dB | 6.22 dB | 27.88→19.83 | 0.9937 | 132.0 |
| Mid-register phrase + low-frequency rumble (22–85 Hz) | `applied` | 7.90 dB | 21.50 dB | 13.60 dB | 7.90→21.47 dB | 13.57 dB | 4.70→3.54 | 0.9194 | 64.3 |
| Stereo instrument with 50 Hz hum in Left channel only | `applied` | 14.51 dB | 28.85 dB | 14.34 dB | 14.51→28.85 dB | 14.34 dB | 2.08→1.41 | 0.9914 | 146.5 |
| Near-clean recording (-80 dBFS quiet ambient bed) | `bypassed_clean_or_silent` | 60.62 dB | 60.62 dB | N/A | 60.62→60.62 dB | N/A | 0.17→0.17 | 1.0000 | 132.2 |
