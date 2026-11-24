import { useMemo, useState } from "react";
import type { MouseEvent } from "react";
import type { FrequencyBandSummary, PsdComparisonData } from "../../types/api";

interface FrequencySpectrumViewProps {
  psd: PsdComparisonData;
  frequencyBands: FrequencyBandSummary[];
}

const CHART_W = 720;
const CHART_H = 210;
const PAD_L = 44;
const PAD_R = 16;
const PAD_T = 14;
const PAD_B = 26;
const DB_MIN = -110;
const DB_MAX = 0;

function formatFreqShort(hz: number): string {
  return hz >= 1000 ? `${hz / 1000}k` : `${hz}`;
}

function formatDb(val: number | null): string {
  return val === null ? "N/A" : `${val.toFixed(1)} dB`;
}

export function FrequencySpectrumView({
  psd,
  frequencyBands,
}: FrequencySpectrumViewProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const { minLog, maxLog, activePath, medianPath, floorPath, refMarkers } =
    useMemo(() => {
      const freqs = psd.frequencies_hz;
      if (freqs.length === 0) {
        return {
          minLog: Math.log10(20),
          maxLog: Math.log10(20000),
          activePath: "",
          medianPath: "",
          floorPath: "",
          refMarkers: [] as { hz: number; x: number; label: string; isHum: boolean }[],
        };
      }

      const fMin = Math.max(10, freqs[0]);
      const fMax = Math.max(fMin * 2, freqs[freqs.length - 1]);
      const lo = Math.log10(fMin);
      const hi = Math.log10(fMax);

      const plotW = CHART_W - PAD_L - PAD_R;
      const plotH = CHART_H - PAD_T - PAD_B;

      const xOf = (hz: number) =>
        PAD_L + ((Math.log10(Math.max(fMin, hz)) - lo) / (hi - lo)) * plotW;
      const yOf = (db: number) => {
        const clamped = Math.min(DB_MAX, Math.max(DB_MIN, db));
        return PAD_T + ((DB_MAX - clamped) / (DB_MAX - DB_MIN)) * plotH;
      };

      const toPath = (values: number[]) =>
        freqs
          .map(
            (hz, idx) =>
              `${idx === 0 ? "M" : "L"}${xOf(hz).toFixed(1)},${yOf(values[idx] ?? DB_MIN).toFixed(1)}`,
          )
          .join(" ");

      const candidates = [
        { hz: 50, isHum: true },
        { hz: 60, isHum: true },
        { hz: 100, isHum: false },
        { hz: 250, isHum: false },
        { hz: 1000, isHum: false },
        { hz: 4000, isHum: false },
        { hz: 10000, isHum: false },
        { hz: 20000, isHum: false },
      ];
      const markers = candidates
        .filter((c) => c.hz >= fMin && c.hz <= fMax)
        .map((c) => ({
          hz: c.hz,
          x: xOf(c.hz),
          label: formatFreqShort(c.hz),
          isHum: c.isHum,
        }));

      return {
        minLog: lo,
        maxLog: hi,
        activePath: toPath(psd.active_p90_db),
        medianPath: toPath(psd.overall_median_db),
        floorPath: toPath(psd.estimated_noise_floor_db),
        refMarkers: markers,
      };
    }, [psd]);

  const handleMouseMove = (event: MouseEvent<SVGSVGElement>) => {
    if (psd.frequencies_hz.length === 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;

    const svgX = ((event.clientX - rect.left) / rect.width) * CHART_W;
    const plotW = CHART_W - PAD_L - PAD_R;
    const frac = Math.min(1, Math.max(0, (svgX - PAD_L) / plotW));
    const targetFreq = 10 ** (minLog + frac * (maxLog - minLog));

    let nearest = 0;
    let bestDiff = Infinity;
    for (let i = 0; i < psd.frequencies_hz.length; i++) {
      const diff = Math.abs(psd.frequencies_hz[i] - targetFreq);
      if (diff < bestDiff) {
        bestDiff = diff;
        nearest = i;
      }
    }
    setHoverIdx(nearest);
  };

  const hovered =
    hoverIdx !== null && hoverIdx < psd.frequencies_hz.length
      ? {
          hz: psd.frequencies_hz[hoverIdx],
          active: psd.active_p90_db[hoverIdx],
          median: psd.overall_median_db[hoverIdx],
          floor: psd.estimated_noise_floor_db[hoverIdx],
        }
      : null;

  return (
    <div className="space-y-5">
      {/* Legend & Hover Readout */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex flex-wrap items-center gap-4 font-mono text-[11px]">
          <span className="flex items-center gap-1.5 text-studio-cyan">
            <span className="h-0.5 w-4 bg-studio-cyan" /> Active (90th pct)
          </span>
          <span className="flex items-center gap-1.5 text-studio-muted">
            <span className="h-0.5 w-4 bg-slate-400" /> Median Spectrum
          </span>
          <span className="flex items-center gap-1.5 text-studio-amber">
            <span className="h-0.5 w-4 border-t border-dashed border-studio-amber" />{" "}
            Estimated Noise Floor
          </span>
        </div>

        <div className="font-mono text-[11px] tabular-nums text-studio-muted">
          {hovered ? (
            <span>
              {hovered.hz >= 1000
                ? `${(hovered.hz / 1000).toFixed(2)} kHz`
                : `${Math.round(hovered.hz)} Hz`}{" "}
              · Active <span className="text-studio-cyan">{hovered.active.toFixed(1)} dB</span> ·
              Est. Floor <span className="text-studio-amber">{hovered.floor.toFixed(1)} dB</span>
            </span>
          ) : (
            <span>Hover spectrum to compare active energy vs estimated floor</span>
          )}
        </div>
      </div>

      {/* SVG PSD Comparison Plot */}
      <div className="rounded border border-studio-border bg-studio-bg p-2">
        <svg
          viewBox={`0 0 ${CHART_W} ${CHART_H}`}
          role="img"
          aria-label="Power spectral density comparison chart"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoverIdx(null)}
          className="h-52 w-full cursor-crosshair"
        >
          {/* Horizontal dB grid lines */}
          {[0, -20, -40, -60, -80, -100].map((db) => {
            const y =
              PAD_T + ((DB_MAX - db) / (DB_MAX - DB_MIN)) * (CHART_H - PAD_T - PAD_B);
            return (
              <g key={db}>
                <line
                  x1={PAD_L}
                  y1={y}
                  x2={CHART_W - PAD_R}
                  y2={y}
                  stroke="#1E2530"
                  strokeWidth="1"
                />
                <text
                  x={PAD_L - 6}
                  y={y + 3}
                  textAnchor="end"
                  fill="#64748B"
                  fontSize="9"
                  fontFamily="monospace"
                >
                  {db}
                </text>
              </g>
            );
          })}

          {/* Vertical Frequency & 50/60 Hz reference markers */}
          {refMarkers.map((m) => (
            <g key={m.hz}>
              <line
                x1={m.x}
                y1={PAD_T}
                x2={m.x}
                y2={CHART_H - PAD_B}
                stroke={m.isHum ? "#47371A" : "#1E2530"}
                strokeDasharray={m.isHum ? "2 3" : undefined}
                strokeWidth="1"
              />
              {!m.isHum && (
                <text
                  x={m.x}
                  y={CHART_H - 8}
                  textAnchor="middle"
                  fill="#64748B"
                  fontSize="9"
                  fontFamily="monospace"
                >
                  {m.label}
                </text>
              )}
            </g>
          ))}

          {/* Curves */}
          {medianPath && (
            <path
              d={medianPath}
              fill="none"
              stroke="#94A3B8"
              strokeWidth="1.25"
              strokeOpacity="0.65"
            />
          )}
          {activePath && (
            <path
              d={activePath}
              fill="none"
              stroke="#2DD4BF"
              strokeWidth="1.75"
            />
          )}
          {floorPath && (
            <path
              d={floorPath}
              fill="none"
              stroke="#D99B26"
              strokeWidth="1.5"
              strokeDasharray="4 3"
            />
          )}
        </svg>
      </div>

      {/* Frequency-Band Summary Table */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-studio-border text-[11px] uppercase tracking-wider text-studio-subtle">
              <th className="py-2 pr-4 font-medium">Frequency Band</th>
              <th className="py-2 pr-4 font-medium">Range</th>
              <th className="py-2 pr-4 font-medium">Active Level</th>
              <th className="py-2 pr-4 font-medium">Est. Noise Floor</th>
              <th className="py-2 pr-4 font-medium">Est. Band SNR</th>
              <th className="py-2 font-medium">Flatness (Tonal → Noisy)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-studio-border/60 font-mono text-[11px] tabular-nums">
            {frequencyBands.map((band) => (
              <tr key={band.id}>
                <td className="py-2 pr-4 font-sans text-xs text-studio-text">
                  {band.label}
                </td>
                <td className="py-2 pr-4 text-studio-muted">
                  {Math.round(band.low_hz)}–{Math.round(band.high_hz)} Hz
                </td>
                <td className="py-2 pr-4 text-studio-cyan">
                  {formatDb(band.active_level_db)}
                </td>
                <td className="py-2 pr-4 text-studio-amber">
                  {formatDb(band.estimated_noise_floor_db)}
                </td>
                <td className="py-2 pr-4 text-studio-text">
                  {formatDb(band.estimated_band_snr_db)}
                </td>
                <td className="py-2 text-studio-muted">
                  {band.spectral_flatness.toFixed(2)}{" "}
                  <span className="font-sans text-[10px] text-studio-subtle">
                    (
                    {band.spectral_flatness >= 0.45
                      ? "broadband"
                      : band.spectral_flatness >= 0.2
                        ? "mixed"
                        : "tonal"}
                    )
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
