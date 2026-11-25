import type { ProcessRequest } from "../../types/api";

interface ProcessingControlsPanelProps {
  settings: ProcessRequest;
  processing: boolean;
  error: { code: string; message: string } | null;
  onChange: (next: ProcessRequest) => void;
  onProcess: () => void;
}

export const DEFAULT_PROCESS_SETTINGS: ProcessRequest = {
  engine: "precision_musical_dsp",
  strength: 0.45,
  hum_reduction_enabled: true,
  hpf_enabled: false,
  hpf_cutoff_hz: 40,
  dry_wet_mix: 1.0,
  bypass: false,
  enable_limiter: false,
  limiter_ceiling_dbtp: -1.0,
};

export function ProcessingControlsPanel({
  settings,
  processing,
  error,
  onChange,
  onProcess,
}: ProcessingControlsPanelProps) {
  const controlsDisabled = processing || settings.bypass;

  return (
    <div
      aria-labelledby="dsp-controls-heading"
      className="border-t border-studio-border"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-studio-border px-5 py-3">
        <div>
          <h3
            id="dsp-controls-heading"
            className="text-xs font-semibold uppercase tracking-[0.12em] text-studio-muted"
          >
            Precision Musical DSP Controls
          </h3>
          <p className="mt-0.5 text-[11px] text-studio-subtle">
            Conservative CPU DSP preserving native sample rate, stereo channels, harmonics, and transients.
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <label htmlFor="processing-engine" className="text-studio-muted">Engine</label>
          <select
            id="processing-engine"
            value={settings.engine}
            disabled={processing}
            onChange={(e) =>
              onChange({
                ...settings,
                engine: e.target.value as ProcessRequest["engine"],
              })
            }
            className="border border-studio-border bg-studio-bg px-2 py-1.5 text-studio-text"
          >
            <option value="precision_musical_dsp">Precision Musical DSP (Available)</option>
            <option value="audiosep_experimental" disabled>AudioSep AI (Experimental — Not installed)</option>
          </select>
        </div>

        <label className="flex cursor-pointer items-center gap-2 font-mono text-xs text-studio-muted">
          <input
            type="checkbox"
            checked={settings.bypass}
            disabled={processing}
            onChange={(e) =>
              onChange({ ...settings, bypass: e.target.checked })
            }
            className="h-3.5 w-3.5 accent-studio-amber"
          />
          <span>Bypass Processing</span>
        </label>
      </div>

      <div className="p-5">
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
          {/* Noise Reduction Strength */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <label
                htmlFor="dsp-strength"
                className="font-medium text-studio-text"
              >
                Noise Reduction Strength
              </label>
              <span className="font-mono text-[11px] tabular-nums text-studio-cyan">
                {Math.round(settings.strength * 100)}%
              </span>
            </div>
            <input
              id="dsp-strength"
              type="range"
              min={0}
              max={0.85}
              step={0.05}
              disabled={controlsDisabled}
              value={settings.strength}
              onChange={(e) =>
                onChange({ ...settings, strength: Number(e.target.value) })
              }
              className="h-1.5 w-full accent-studio-cyan disabled:opacity-40"
            />
            <p className="text-[11px] text-studio-subtle">
              Capped at 85% (-14.5 dB max attenuation) to prevent watery musical artifacts.
            </p>
          </div>

          {/* Render Dry/Wet Mix */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <label
                htmlFor="dsp-dry-wet"
                className="font-medium text-studio-text"
              >
                Output Dry / Wet Mix
              </label>
              <span className="font-mono text-[11px] tabular-nums text-studio-amber">
                {Math.round(settings.dry_wet_mix * 100)}% Wet
              </span>
            </div>
            <input
              id="dsp-dry-wet"
              type="range"
              min={0}
              max={1}
              step={0.05}
              disabled={controlsDisabled}
              value={settings.dry_wet_mix}
              onChange={(e) =>
                onChange({ ...settings, dry_wet_mix: Number(e.target.value) })
              }
              className="h-1.5 w-full accent-studio-amber disabled:opacity-40"
            />
            <p className="text-[11px] text-studio-subtle">
              Parallel blend into the rendered cleaned file (live A/B blend also available after processing).
            </p>
          </div>

          {/* Optional High-Pass Filter */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <label className="flex cursor-pointer items-center gap-2 font-medium text-studio-text">
                <input
                  type="checkbox"
                  checked={settings.hpf_enabled}
                  disabled={controlsDisabled}
                  onChange={(e) =>
                    onChange({ ...settings, hpf_enabled: e.target.checked })
                  }
                  className="h-3.5 w-3.5 accent-studio-cyan"
                />
                <span>High-Pass Filter (Rumble)</span>
              </label>
              <span className="font-mono text-[11px] tabular-nums text-studio-muted">
                {settings.hpf_enabled ? `${settings.hpf_cutoff_hz} Hz` : "Off"}
              </span>
            </div>
            <input
              id="dsp-hpf-cutoff"
              aria-label="High-pass filter cutoff frequency"
              type="range"
              min={20}
              max={150}
              step={5}
              disabled={controlsDisabled || !settings.hpf_enabled}
              value={settings.hpf_cutoff_hz}
              onChange={(e) =>
                onChange({ ...settings, hpf_cutoff_hz: Number(e.target.value) })
              }
              className="h-1.5 w-full accent-studio-cyan disabled:opacity-40"
            />
            <p className="text-[11px] text-studio-subtle">
              Off by default so low bass/piano fundamentals stay untouched unless rumble is present.
            </p>
          </div>
        </div>

        {/* Toggle Safeguards & Process Action */}
        <div className="mt-5 flex flex-wrap items-center justify-between gap-4 border-t border-studio-border pt-4">
          <div className="flex flex-wrap items-center gap-5 text-xs">
            <label className="flex cursor-pointer items-center gap-2 text-studio-text">
              <input
                type="checkbox"
                checked={settings.hum_reduction_enabled}
                disabled={controlsDisabled}
                onChange={(e) =>
                  onChange({
                    ...settings,
                    hum_reduction_enabled: e.target.checked,
                  })
                }
                className="h-3.5 w-3.5 accent-studio-cyan"
              />
              <span>50/60 Hz Hum Reduction</span>
              <span className="font-mono text-[10px] text-studio-subtle">
                (evidence-gated, pitch-safe)
              </span>
            </label>

            <label className="flex cursor-pointer items-center gap-2 text-studio-text">
              <input
                type="checkbox"
                checked={settings.enable_limiter}
                disabled={controlsDisabled}
                onChange={(e) =>
                  onChange({ ...settings, enable_limiter: e.target.checked })
                }
                className="h-3.5 w-3.5 accent-studio-amber"
              />
              <span>Optional True-Peak Limiter (-1.0 dBTP)</span>
            </label>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={processing}
              onClick={() => onChange(DEFAULT_PROCESS_SETTINGS)}
              className="rounded border border-studio-border bg-studio-bg px-3 py-1.5 text-xs text-studio-muted transition-colors hover:text-studio-text disabled:opacity-40"
            >
              Reset Defaults
            </button>

            <button
              type="button"
              disabled={processing}
              onClick={onProcess}
              className="rounded border border-studio-amber/70 bg-studio-amber/20 px-4 py-1.5 text-xs font-semibold text-studio-amber transition-colors hover:bg-studio-amber/30 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {processing ? "Processing Audio..." : "Process Audio"}
            </button>
          </div>
        </div>

        {processing && (
          <div
            role="status"
            aria-live="polite"
            className="mt-4 rounded border border-studio-border bg-studio-bg px-4 py-2.5 font-mono text-xs text-studio-amber"
          >
            Running Precision Musical DSP pipeline on native sample-rate float32 audio...
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="mt-4 rounded border border-studio-danger/40 bg-studio-danger/10 px-4 py-3 text-xs"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-semibold text-studio-danger">
                Audio processing failed
              </span>
              <span className="font-mono text-[11px] text-studio-danger/90">
                {error.code}
              </span>
            </div>
            <p className="mt-1 text-studio-text/90">{error.message}</p>
          </div>
        )}
      </div>
    </div>
  );
}
