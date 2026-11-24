import { useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent } from "react";
import type { FrequencyScale, SpectrogramData } from "../../types/api";

interface SpectrogramViewProps {
  spectrogram: SpectrogramData;
  freqScale: FrequencyScale;
  dbMin: number;
  loading: boolean;
  onFreqScaleChange: (scale: FrequencyScale) => void;
  onDbMinChange: (dbMin: number) => void;
}

interface HoverReadout {
  timeSec: number;
  freqHz: number;
  db: number;
  xPct: number;
  yPct: number;
}

/**
 * Perceptually legible dark-studio colormap (u8 0..255 -> RGBA).
 * Obsidian -> Deep Indigo -> Studio Teal -> Warm Amber -> Soft Gold.
 */
function buildColorLut(): Uint8ClampedArray {
  const stops: [number, number, number, number][] = [
    [0, 11, 13, 16],
    [55, 22, 36, 66],
    [115, 17, 94, 89],
    [175, 45, 212, 191],
    [225, 217, 155, 38],
    [255, 254, 243, 199],
  ];

  const lut = new Uint8ClampedArray(256 * 4);
  for (let i = 0; i < 256; i++) {
    let s0 = stops[0];
    let s1 = stops[stops.length - 1];
    for (let k = 0; k < stops.length - 1; k++) {
      if (i >= stops[k][0] && i <= stops[k + 1][0]) {
        s0 = stops[k];
        s1 = stops[k + 1];
        break;
      }
    }
    const span = Math.max(1, s1[0] - s0[0]);
    const t = (i - s0[0]) / span;
    lut[i * 4] = Math.round(s0[1] + (s1[1] - s0[1]) * t);
    lut[i * 4 + 1] = Math.round(s0[2] + (s1[2] - s0[2]) * t);
    lut[i * 4 + 2] = Math.round(s0[3] + (s1[3] - s0[3]) * t);
    lut[i * 4 + 3] = 255;
  }
  return lut;
}

const COLOR_LUT = buildColorLut();

function formatFreq(hz: number): string {
  if (hz >= 1000) {
    const khz = hz / 1000;
    return `${khz >= 10 ? khz.toFixed(0) : khz.toFixed(1)} kHz`;
  }
  return `${Math.round(hz)} Hz`;
}

export function SpectrogramView({
  spectrogram,
  freqScale,
  dbMin,
  loading,
  onFreqScaleChange,
  onDbMinChange,
}: SpectrogramViewProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [hover, setHover] = useState<HoverReadout | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const width = spectrogram.time_bins;
    const height = spectrogram.freq_bins;
    if (width <= 0 || height <= 0) return;

    canvas.width = width;
    canvas.height = height;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const img = ctx.createImageData(width, height);
    const data = img.data;

    // Flip vertically so low frequencies sit at the bottom and high frequencies at the top
    for (let fIdx = 0; fIdx < height; fIdx++) {
      const row = spectrogram.magnitudes_u8[fIdx];
      const canvasY = height - 1 - fIdx;
      const rowOffset = canvasY * width * 4;
      for (let tIdx = 0; tIdx < width; tIdx++) {
        const val = row?.[tIdx] ?? 0;
        const lutIdx = (val & 0xff) * 4;
        const px = rowOffset + tIdx * 4;
        data[px] = COLOR_LUT[lutIdx];
        data[px + 1] = COLOR_LUT[lutIdx + 1];
        data[px + 2] = COLOR_LUT[lutIdx + 2];
        data[px + 3] = 255;
      }
    }

    ctx.putImageData(img, 0, 0);
  }, [spectrogram]);

  const yTicks = useMemo(() => {
    const freqs = spectrogram.frequencies_hz;
    if (freqs.length === 0) return [];
    const maxFreq = freqs[freqs.length - 1];
    const indices = [
      freqs.length - 1,
      Math.floor((freqs.length - 1) * 0.75),
      Math.floor((freqs.length - 1) * 0.5),
      Math.floor((freqs.length - 1) * 0.25),
      0,
    ];
    return indices
      .filter((idx, pos, arr) => arr.indexOf(idx) === pos)
      .map((idx) => ({
        freqHz: freqs[idx] ?? maxFreq,
        label: formatFreq(freqs[idx] ?? 0),
      }));
  }, [spectrogram.frequencies_hz]);

  const xTicks = useMemo(() => {
    const times = spectrogram.times_sec;
    if (times.length === 0) return [];
    const last = times[times.length - 1] ?? 0;
    return [0, 0.25, 0.5, 0.75, 1].map((frac) => ({
      label: `${(last * frac).toFixed(last < 10 ? 2 : 1)}s`,
    }));
  }, [spectrogram.times_sec]);

  const handleMouseMove = (event: MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || spectrogram.time_bins === 0 || spectrogram.freq_bins === 0) {
      return;
    }
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;

    const xFrac = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const yFrac = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));

    const tIdx = Math.min(
      spectrogram.time_bins - 1,
      Math.floor(xFrac * spectrogram.time_bins),
    );
    const fIdx = Math.min(
      spectrogram.freq_bins - 1,
      Math.floor((1 - yFrac) * spectrogram.freq_bins),
    );

    const u8 = spectrogram.magnitudes_u8[fIdx]?.[tIdx] ?? 0;
    const db =
      spectrogram.db_min +
      (u8 / 255) * (spectrogram.db_max - spectrogram.db_min);

    setHover({
      timeSec: spectrogram.times_sec[tIdx] ?? 0,
      freqHz: spectrogram.frequencies_hz[fIdx] ?? 0,
      db,
      xPct: xFrac * 100,
      yPct: yFrac * 100,
    });
  };

  return (
    <div>
      {/* Controls & Cursor Readout Bar */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex flex-wrap items-center gap-3">
          <div className="inline-flex rounded border border-studio-border bg-studio-bg p-0.5">
            {(["log", "linear"] as const).map((scale) => (
              <button
                key={scale}
                type="button"
                disabled={loading}
                aria-pressed={freqScale === scale}
                onClick={() => onFreqScaleChange(scale)}
                className={`rounded px-2.5 py-1 font-mono text-[11px] uppercase transition-colors ${
                  freqScale === scale
                    ? "bg-studio-elevated text-studio-cyan"
                    : "text-studio-muted hover:text-studio-text"
                }`}
              >
                {scale}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-2 font-mono text-[11px] text-studio-muted">
            <span>Floor</span>
            <select
              aria-label="Spectrogram dB floor"
              value={dbMin}
              disabled={loading}
              onChange={(e) => onDbMinChange(Number(e.target.value))}
              className="rounded border border-studio-border bg-studio-bg px-2 py-1 text-studio-text focus:border-studio-cyan focus:outline-none"
            >
              <option value={-80}>-80 dB</option>
              <option value={-100}>-100 dB</option>
              <option value={-120}>-120 dB</option>
            </select>
          </label>

          <span className="font-mono text-[11px] text-studio-subtle">
            STFT {spectrogram.n_fft} · {spectrogram.freq_bins}×{spectrogram.time_bins}
          </span>
        </div>

        <div
          aria-live="polite"
          className="font-mono text-[11px] tabular-nums text-studio-muted"
        >
          {hover ? (
            <span>
              <span className="text-studio-text">{hover.timeSec.toFixed(2)}s</span> ·{" "}
              <span className="text-studio-cyan">{formatFreq(hover.freqHz)}</span> ·{" "}
              <span className="text-studio-amber">{hover.db.toFixed(1)} dBFS</span>
            </span>
          ) : (
            <span>Hover spectrogram to inspect time / frequency / level</span>
          )}
        </div>
      </div>

      {/* Spectrogram Plot with Axes */}
      <div className="flex gap-2">
        {/* Frequency Y-Axis */}
        <div
          aria-hidden="true"
          className="flex h-52 w-14 shrink-0 flex-col justify-between py-0.5 text-right font-mono text-[10px] tabular-nums text-studio-subtle"
        >
          {yTicks.map((tick) => (
            <span key={tick.label}>{tick.label}</span>
          ))}
        </div>

        <div className="min-w-0 flex-1">
          <div className="relative h-52 w-full overflow-hidden rounded border border-studio-border bg-studio-bg">
            <canvas
              ref={canvasRef}
              aria-label="Interactive audio spectrogram"
              onMouseMove={handleMouseMove}
              onMouseLeave={() => setHover(null)}
              className="h-full w-full cursor-crosshair [image-rendering:pixelated]"
            />
            {hover && (
              <>
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute top-0 bottom-0 w-px bg-studio-text/40"
                  style={{ left: `${hover.xPct}%` }}
                />
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute right-0 left-0 h-px bg-studio-text/40"
                  style={{ top: `${hover.yPct}%` }}
                />
              </>
            )}
          </div>

          {/* Time X-Axis */}
          <div
            aria-hidden="true"
            className="mt-1.5 flex justify-between font-mono text-[10px] tabular-nums text-studio-subtle"
          >
            {xTicks.map((tick, idx) => (
              <span key={`${tick.label}-${idx}`}>{tick.label}</span>
            ))}
          </div>
        </div>
      </div>

      {/* Compact dB Legend */}
      <div className="mt-2.5 flex items-center justify-end gap-2 font-mono text-[10px] tabular-nums text-studio-subtle">
        <span>{spectrogram.db_min} dB</span>
        <div
          aria-hidden="true"
          className="h-2 w-28 rounded-sm border border-studio-border"
          style={{
            background:
              "linear-gradient(90deg, #0B0D10 0%, #162442 22%, #115E59 45%, #2DD4BF 68%, #D99B26 88%, #FEF3C7 100%)",
          }}
        />
        <span>{spectrogram.db_max} dB</span>
      </div>
    </div>
  );
}
