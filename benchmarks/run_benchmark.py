"""Executable reproducible Stage 4 DSP benchmark runner."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Allow running directly as `python benchmarks/run_benchmark.py` from repo root
_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.dsp.pipeline import process_audio_pipeline  # noqa: E402
from benchmarks.metrics import evaluate_benchmark_pair  # noqa: E402
from benchmarks.scenarios import build_all_scenarios  # noqa: E402


def _fmt(val: float | None, suffix: str = "") -> str:
    return "N/A" if val is None else f"{val:.2f}{suffix}"


def run_stage4_benchmarks(write_results: bool = True) -> list[dict]:
    """Execute all deterministic Stage 4 DSP benchmark scenarios and return records."""
    scenarios = build_all_scenarios(seed=2026)
    records: list[dict] = []

    for sc in scenarios:
        out = process_audio_pipeline(sc.noisy_input, sc.sample_rate, sc.request)
        metrics = evaluate_benchmark_pair(
            clean=sc.clean,
            noisy_input=sc.noisy_input,
            processed=out.processed,
            sample_rate=sc.sample_rate,
            processing_time_ms=out.processing_time_ms,
            is_clean_reference_scenario=sc.is_clean_reference,
        )
        records.append(
            {
                "id": sc.id,
                "title": sc.title,
                "processing_mode": out.processing_mode,
                "sample_rate": sc.sample_rate,
                "channels": sc.clean.shape[1],
                "is_clean_reference": sc.is_clean_reference,
                "metrics": asdict(metrics),
                "actions": out.actions.model_dump(),
            }
        )

    if write_results:
        out_dir = _REPO_ROOT / "benchmarks" / "results"
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "disclaimer": (
                "Synthetic deterministic benchmark results verify DSP signal behavior and "
                "guardrails on controlled mixtures; they do NOT prove real-world musical "
                "listening quality."
            ),
            "engine": "precision_musical_dsp_stage4",
            "scenarios": records,
        }
        (out_dir / "stage4_dsp_benchmark.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

        lines = [
            "# SONORA Stage 4 — Precision Musical DSP Synthetic Benchmark Report",
            "",
            "> **Note:** These results are generated from **deterministic synthetic signals and controlled noise mixtures** for regression verification. They do **not** replace listening tests on real musical instrument recordings. SNR and SI-SDR are computed **jointly** across all channels (per-channel breakdowns are included in the JSON report).",
            "",
            "| Scenario | Mode | In SNR | Out SNR | ΔSNR | In→Out SI-SDR | ΔSI-SDR | In→Out LSD (dB) | Transients | Time (ms) |",
            "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for rec in records:
            m = rec["metrics"]
            trans_val = m["transient_preservation"]
            trans_str = "N/A" if trans_val is None else f"{trans_val:.4f}"
            lines.append(
                f"| {rec['title']} | `{rec['processing_mode']}` | "
                f"{_fmt(m['input_snr_db'], ' dB')} | {_fmt(m['output_snr_db'], ' dB')} | "
                f"{_fmt(m['snr_improvement_db'], ' dB')} | "
                f"{_fmt(m['input_si_sdr_db'])}→{_fmt(m['output_si_sdr_db'], ' dB')} | "
                f"{_fmt(m['si_sdr_improvement_db'], ' dB')} | "
                f"{m['input_log_spectral_distance_db']:.2f}→{m['log_spectral_distance_db']:.2f} | "
                f"{trans_str} | "
                f"{m['processing_time_ms']:.1f} |"
            )
        (out_dir / "stage4_dsp_benchmark.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    return records


def main() -> None:
    records = run_stage4_benchmarks(write_results=True)
    print(f"Ran {len(records)} synthetic Stage 4 DSP benchmark scenarios:")
    for rec in records:
        m = rec["metrics"]
        print(
            f"  - {rec['id']:<34} mode={rec['processing_mode']:<24} "
            f"SNR: {_fmt(m['input_snr_db'])} -> {_fmt(m['output_snr_db'])} (d={_fmt(m['snr_improvement_db'])})  "
            f"SI-SDR: {_fmt(m['output_si_sdr_db'])} (d={_fmt(m['si_sdr_improvement_db'])})  "
            f"LSD={m['log_spectral_distance_db']:.3f}dB  "
            f"Trans={m['transient_preservation']}  {m['processing_time_ms']:.1f}ms"
        )


if __name__ == "__main__":
    main()
