import { useCallback, useEffect, useState } from "react";
import { ApiClientError, analyzeSession } from "../../api/client";
import type {
  AnalysisResponse,
  ConfidenceLevel,
  FrequencyScale,
  SessionDetail,
} from "../../types/api";
import { FrequencySpectrumView } from "./FrequencySpectrumView";
import { SpectrogramView } from "./SpectrogramView";

interface NoiseAnalysisPanelProps {
  session: SessionDetail;
}

type VisualTab = "spectrogram" | "spectrum";

function confidenceBadgeClass(level: ConfidenceLevel): string {
  switch (level) {
    case "high":
      return "border-studio-amber/50 bg-studio-amber/15 text-studio-amber";
    case "moderate":
      return "border-studio-cyan/40 bg-studio-cyan/10 text-studio-cyan";
    case "low":
      return "border-studio-border bg-studio-elevated text-studio-muted";
    default:
      return "border-studio-border bg-studio-bg text-studio-subtle";
  }
}

function formatDbValue(value: number | null, suffix: string): string {
  return value === null ? "N/A" : `${value.toFixed(1)} ${suffix}`;
}

export function NoiseAnalysisPanel({ session }: NoiseAnalysisPanelProps) {
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<{ code: string; message: string } | null>(
    null,
  );
  const [freqScale, setFreqScale] = useState<FrequencyScale>("log");
  const [dbMin, setDbMin] = useState<number>(-100);
  const [activeTab, setActiveTab] = useState<VisualTab>("spectrogram");
  const [showNonTriggered, setShowNonTriggered] = useState<boolean>(false);

  const runAnalysis = useCallback(
    async (
      scale: FrequencyScale,
      floorDb: number,
      signal?: AbortSignal,
    ) => {
      setLoading(true);
      setError(null);
      try {
        const result = await analyzeSession(
          session.session_id,
          { freq_scale: scale, db_min: floorDb, db_max: 0 },
          signal,
        );
        setAnalysis(result);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        if (err instanceof ApiClientError) {
          setError({ code: err.code, message: err.message });
        } else if (err instanceof Error) {
          setError({ code: "ANALYSIS_ERROR", message: err.message });
        } else {
          setError({
            code: "ANALYSIS_ERROR",
            message: "Unable to analyze this audio recording.",
          });
        }
      } finally {
        setLoading(false);
      }
    },
    [session.session_id],
  );

  useEffect(() => {
    const controller = new AbortController();
    void runAnalysis(freqScale, dbMin, controller.signal);
    return () => controller.abort();
  }, [runAnalysis, freqScale, dbMin]);

  const detectedIndicators =
    analysis?.detected_indicators.filter((ind) => ind.detected) ?? [];
  const quietIndicators =
    analysis?.detected_indicators.filter((ind) => !ind.detected) ?? [];

  return (
    <div
      aria-labelledby="noise-analysis-heading"
      className="border-t border-studio-border"
    >
      {/* Header Strip */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-studio-border px-5 py-3">
        <div>
          <h3
            id="noise-analysis-heading"
            className="text-xs font-semibold uppercase tracking-[0.12em] text-studio-muted"
          >
            Noise &amp; Frequency Analysis
          </h3>
          <p className="mt-0.5 text-[11px] text-studio-subtle">
            Diagnostic spectral inspection only — distinguishes estimated noise floor from possible spectral indicators.
          </p>
        </div>

        <button
          type="button"
          disabled={loading}
          onClick={() => void runAnalysis(freqScale, dbMin)}
          className="rounded border border-studio-border bg-studio-elevated px-3 py-1 text-xs text-studio-text transition-colors hover:border-studio-subtle disabled:opacity-50"
        >
          {loading ? "Analyzing..." : "Re-analyze"}
        </button>
      </div>

      {/* Loading & Error States */}
      {loading && !analysis && (
        <div
          role="status"
          aria-live="polite"
          className="px-5 py-8 text-center font-mono text-xs text-studio-muted"
        >
          Running STFT spectral analysis and silence-free noise-floor estimation...
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="m-5 rounded border border-studio-danger/40 bg-studio-danger/10 px-4 py-3 text-xs"
        >
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-semibold text-studio-danger">
              Spectral analysis failed
            </span>
            <span className="font-mono text-[11px] text-studio-danger/90">
              {error.code}
            </span>
          </div>
          <p className="mt-1 text-studio-text/90">{error.message}</p>
        </div>
      )}

      {analysis && (
        <>
          {/* Two-Column Diagnostic Strip: Estimated Floor vs Possible Indicators */}
          <div className="grid grid-cols-1 divide-y divide-studio-border border-b border-studio-border lg:grid-cols-12 lg:divide-x lg:divide-y-0">
            {/* Estimated Noise Floor */}
            <div className="p-5 lg:col-span-5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-studio-subtle">
                  Estimated Noise Floor
                </span>
                <span
                  className={`rounded border px-2 py-0.5 font-mono text-[10px] uppercase ${confidenceBadgeClass(
                    analysis.noise_floor.confidence,
                  )}`}
                >
                  Est. Confidence: {analysis.noise_floor.confidence}
                </span>
              </div>

              <dl className="mt-3 grid grid-cols-3 gap-3 border-y border-studio-border py-3">
                <div>
                  <dt className="text-[10px] uppercase tracking-wider text-studio-subtle">
                    Est. Floor
                  </dt>
                  <dd className="mt-1 font-mono text-xs tabular-nums text-studio-amber">
                    {formatDbValue(
                      analysis.noise_floor.broadband_noise_floor_dbfs,
                      "dBFS",
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] uppercase tracking-wider text-studio-subtle">
                    Active (90%)
                  </dt>
                  <dd className="mt-1 font-mono text-xs tabular-nums text-studio-cyan">
                    {formatDbValue(
                      analysis.noise_floor.active_signal_dbfs,
                      "dBFS",
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] uppercase tracking-wider text-studio-subtle">
                    Est. SNR
                  </dt>
                  <dd className="mt-1 font-mono text-xs tabular-nums text-studio-text">
                    {formatDbValue(analysis.noise_floor.estimated_snr_db, "dB")}
                  </dd>
                </div>
              </dl>

              {analysis.noise_floor.sustained_tonal_warning && (
                <div className="mt-3 rounded border border-studio-amber/40 bg-studio-amber/10 px-3 py-2 text-[11px] text-studio-amber">
                  Sustained tonal energy detected across the recording — inter-harmonic
                  guarding applied so musical notes are not treated as stationary noise.
                </div>
              )}

              <ul className="mt-3 space-y-1 text-[11px] leading-relaxed text-studio-muted">
                {analysis.noise_floor.notes.map((note, idx) => (
                  <li key={idx}>· {note}</li>
                ))}
              </ul>
            </div>

            {/* Possible Noise Indicators */}
            <div className="p-5 lg:col-span-7">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-studio-subtle">
                  Possible Noise Indicators (Spectral Heuristics)
                </span>
                <span className="font-mono text-[11px] text-studio-subtle">
                  {detectedIndicators.length} flagged
                </span>
              </div>

              {detectedIndicators.length === 0 ? (
                <div className="mt-3 rounded border border-studio-border bg-studio-bg px-4 py-3 text-xs text-studio-muted">
                  <p className="font-medium text-studio-text">
                    No strong spectral noise indicators identified
                  </p>
                  <p className="mt-1 text-[11px] text-studio-subtle">
                    {analysis.signal_state === "silence_or_near_silence"
                      ? "Signal is silent or near-silent (< -80 dBFS RMS)."
                      : "Recording does not exhibit prominent hum, broadband hiss, rumble, or steady room-noise signatures. Spectral analysis cannot rule out subtle or overlapping background noise."}
                  </p>
                </div>
              ) : (
                <ul className="mt-3 divide-y divide-studio-border rounded border border-studio-border bg-studio-bg/60">
                  {detectedIndicators.map((ind) => (
                    <li key={ind.id} className="px-4 py-3 text-xs">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium text-studio-text">
                          {ind.label}
                        </span>
                        <span
                          className={`rounded border px-2 py-0.5 font-mono text-[10px] uppercase ${confidenceBadgeClass(
                            ind.confidence,
                          )}`}
                        >
                          Confidence: {ind.confidence}
                        </span>
                      </div>
                      <p className="mt-1 text-[11px] text-studio-muted">
                        {ind.evidence}
                      </p>
                      <p className="mt-1 text-[11px] text-studio-subtle">
                        Caveat: {ind.caveat}
                      </p>
                    </li>
                  ))}
                </ul>
              )}

              {quietIndicators.length > 0 && (
                <div className="mt-3">
                  <button
                    type="button"
                    onClick={() => setShowNonTriggered((prev) => !prev)}
                    className="font-mono text-[11px] text-studio-subtle hover:text-studio-text"
                  >
                    {showNonTriggered
                      ? `Hide ${quietIndicators.length} non-triggered check(s)`
                      : `Show ${quietIndicators.length} non-triggered check(s)`}
                  </button>
                  {showNonTriggered && (
                    <ul className="mt-2 space-y-1.5 rounded border border-studio-border/60 bg-studio-bg/40 p-3 text-[11px] text-studio-subtle">
                      {quietIndicators.map((ind) => (
                        <li key={ind.id}>
                          <span className="font-medium text-studio-muted">
                            {ind.label}:
                          </span>{" "}
                          {ind.evidence}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Interactive Visualization Tabs: Spectrogram | PSD & Frequency Bands */}
          <div className="p-5">
            <div className="mb-4 flex items-center gap-2 border-b border-studio-border pb-3">
              <div role="tablist" aria-label="Frequency analysis views" className="inline-flex gap-2">
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === "spectrogram"}
                  onClick={() => setActiveTab("spectrogram")}
                  className={`rounded border px-3 py-1.5 text-xs font-medium transition-colors ${
                    activeTab === "spectrogram"
                      ? "border-studio-cyan/50 bg-studio-cyan/15 text-studio-cyan"
                      : "border-studio-border bg-studio-bg text-studio-muted hover:text-studio-text"
                  }`}
                >
                  Spectrogram
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === "spectrum"}
                  onClick={() => setActiveTab("spectrum")}
                  className={`rounded border px-3 py-1.5 text-xs font-medium transition-colors ${
                    activeTab === "spectrum"
                      ? "border-studio-cyan/50 bg-studio-cyan/15 text-studio-cyan"
                      : "border-studio-border bg-studio-bg text-studio-muted hover:text-studio-text"
                  }`}
                >
                  PSD &amp; Frequency Bands
                </button>
              </div>
            </div>

            {activeTab === "spectrogram" ? (
              <SpectrogramView
                spectrogram={analysis.spectrogram}
                freqScale={freqScale}
                dbMin={dbMin}
                loading={loading}
                onFreqScaleChange={setFreqScale}
                onDbMinChange={setDbMin}
              />
            ) : (
              <FrequencySpectrumView
                psd={analysis.psd}
                frequencyBands={analysis.frequency_bands}
              />
            )}

            {/* Honest Methodological Limitations */}
            <div className="mt-5 border-t border-studio-border pt-3 text-[11px] text-studio-subtle">
              <p className="font-medium text-studio-muted">
                Analysis Scope &amp; Limitations
              </p>
              <ul className="mt-1 space-y-0.5">
                {analysis.limitations.map((item, idx) => (
                  <li key={idx}>· {item}</li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
