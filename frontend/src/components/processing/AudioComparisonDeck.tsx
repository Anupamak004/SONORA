import { useEffect, useRef, useState } from "react";
import type { MouseEvent } from "react";
import { resolveApiUrl } from "../../api/client";
import {
  AbAudioEngine,
  type AbAudioState,
  type CompareListenMode,
} from "../../audio/abAudioEngine";
import type {
  ProcessingMode,
  ProcessResponse,
  SessionDetail,
  WaveformPeaks,
} from "../../types/api";

interface AudioComparisonDeckProps {
  session: SessionDetail;
  result: ProcessResponse;
}

function formatTimecode(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00.0";
  const mins = Math.floor(seconds / 60);
  const secs = seconds - mins * 60;
  return `${mins}:${secs.toFixed(1).padStart(4, "0")}`;
}

function formatDb(value: number | null, unit: string): string {
  return value === null ? "N/A" : `${value.toFixed(2)} ${unit}`;
}

function modeBadge(mode: ProcessingMode): { label: string; className: string } {
  switch (mode) {
    case "applied":
      return {
        label: "Processing Applied",
        className: "border-studio-ok/40 bg-studio-ok/10 text-studio-ok",
      };
    case "minimal":
      return {
        label: "Minimal Processing Applied",
        className: "border-studio-cyan/40 bg-studio-cyan/10 text-studio-cyan",
      };
    case "bypassed":
      return {
        label: "Bypassed (User)",
        className: "border-studio-amber/40 bg-studio-amber/10 text-studio-amber",
      };
    case "bypassed_clean_or_silent":
      return {
        label: "Auto-Bypassed (Clean / Silent)",
        className: "border-studio-amber/40 bg-studio-amber/10 text-studio-amber",
      };
  }
}

interface WaveformStripProps {
  label: string;
  waveform: WaveformPeaks;
  progressFrac: number;
  active: boolean;
  accentColor: string;
  onSeekFraction: (frac: number) => void;
}

function WaveformStrip({
  label,
  waveform,
  progressFrac,
  active,
  accentColor,
  onSeekFraction,
}: WaveformStripProps) {
  const peaks = waveform.peaks;
  const barCount = Math.min(180, peaks.length);
  const step = Math.max(1, peaks.length / barCount);

  const sampled: number[] = [];
  for (let i = 0; i < barCount; i++) {
    const start = Math.floor(i * step);
    const end = Math.min(peaks.length, Math.max(start + 1, Math.floor((i + 1) * step)));
    let maxVal = 0;
    for (let j = start; j < end; j++) {
      if (peaks[j] > maxVal) maxVal = peaks[j];
    }
    sampled.push(maxVal);
  }

  const handleClick = (event: MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const frac = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    onSeekFraction(frac);
  };

  return (
    <div
      className={`rounded border px-3 py-2.5 transition-colors ${
        active
          ? "border-studio-cyan/50 bg-studio-bg"
          : "border-studio-border bg-studio-bg/60"
      }`}
    >
      <div className="mb-1.5 flex items-center justify-between text-[11px]">
        <span className={active ? "font-medium text-studio-text" : "text-studio-muted"}>
          {label}
        </span>
        {active && (
          <span className="font-mono text-[10px] uppercase text-studio-cyan">
            Auditioning
          </span>
        )}
      </div>

      <div
        role="slider"
        tabIndex={0}
        aria-label={`${label} seek bar`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progressFrac * 100)}
        onClick={handleClick}
        className="relative flex h-14 cursor-pointer items-center gap-[1px] overflow-hidden"
      >
        {sampled.map((peak, idx) => {
          const frac = idx / Math.max(1, sampled.length - 1);
          const heightPct = Math.max(4, Math.min(100, Math.round(peak * 100)));
          const played = frac <= progressFrac;
          return (
            <div
              key={idx}
              className="flex-1 rounded-[1px]"
              style={{
                height: `${heightPct}%`,
                backgroundColor: played ? accentColor : "#334155",
              }}
            />
          );
        })}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute top-0 bottom-0 w-0.5 bg-studio-amber"
          style={{ left: `${progressFrac * 100}%` }}
        />
      </div>
    </div>
  );
}

export function AudioComparisonDeck({
  session,
  result,
}: AudioComparisonDeckProps) {
  const engineRef = useRef<AbAudioEngine | null>(null);
  const [listenMode, setListenMode] = useState<CompareListenMode>("processed");
  const [liveWetMix, setLiveWetMix] = useState<number>(1.0);
  const [volume, setVolume] = useState<number>(1.0);
  const [muted, setMuted] = useState<boolean>(false);
  const [audioState, setAudioState] = useState<AbAudioState>({
    ready: false,
    loading: true,
    playing: false,
    currentTime: 0,
    duration: result.duration_seconds,
    error: null,
  });

  useEffect(() => {
    const engine = new AbAudioEngine((next) => setAudioState(next));
    engineRef.current = engine;
    engine.setMode("processed");
    setListenMode("processed");
    setLiveWetMix(1.0);

    void engine.load(
      resolveApiUrl(result.original_aligned_audio_url),
      resolveApiUrl(result.processed_audio_url),
      resolveApiUrl(result.residual_audio_url),
      result.duration_seconds,
    );

    return () => {
      engineRef.current = null;
      engine.dispose();
    };
  }, [
    result.original_aligned_audio_url,
    result.processed_audio_url,
    result.residual_audio_url,
    result.duration_seconds,
  ]);

  const handleModeSwitch = (mode: CompareListenMode) => {
    setListenMode(mode);
    engineRef.current?.setMode(mode);
  };

  const handleLiveMixChange = (wet: number) => {
    setLiveWetMix(wet);
    if (listenMode !== "mix") {
      setListenMode("mix");
      engineRef.current?.setMode("mix");
    }
    engineRef.current?.setWetMix(wet);
  };

  const handlePlayPause = () => {
    const engine = engineRef.current;
    if (!engine) return;
    if (audioState.playing) {
      engine.pause();
    } else {
      void engine.play();
    }
  };

  const handleStop = () => {
    engineRef.current?.stop();
  };

  const handleSeekFraction = (frac: number) => {
    engineRef.current?.seek(frac * audioState.duration);
  };

  const badge = modeBadge(result.processing_mode);
  const progressFrac =
    audioState.duration > 0
      ? Math.min(1, Math.max(0, audioState.currentTime / audioState.duration))
      : 0;

  return (
    <div
      aria-labelledby="comparison-deck-heading"
      className="border-t border-studio-border bg-studio-surface"
    >
      {/* Result Header & Bypass/Applied Status */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-studio-border px-5 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <h3
            id="comparison-deck-heading"
            className="text-xs font-semibold uppercase tracking-[0.12em] text-studio-muted"
          >
            Processed Output &amp; A/B Comparison
          </h3>
          <span
            className={`rounded border px-2 py-0.5 font-mono text-[10px] uppercase ${badge.className}`}
          >
            {badge.label}
          </span>
          {result.cached && (
            <span className="rounded border border-studio-border bg-studio-bg px-2 py-0.5 font-mono text-[10px] text-studio-subtle">
              Cached
            </span>
          )}
        </div>

        <span className="font-mono text-[11px] tabular-nums text-studio-subtle">
          {(result.sample_rate / 1000).toFixed(
            result.sample_rate % 1000 === 0 ? 0 : 1,
          )}{" "}
          kHz · {result.channels === 1 ? "Mono" : "Stereo"} ·{" "}
          {result.processing_time_ms.toFixed(0)} ms
        </span>
      </div>

      {/* Synchronized A / B / Dry-Wet / Residual Audition Controls */}
      <div className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div
            role="group"
            aria-label="Audio comparison source"
            className="inline-flex flex-wrap rounded border border-studio-border bg-studio-bg p-0.5"
          >
            {(
              [
                { id: "original", label: "Original (A)" },
                { id: "processed", label: "Cleaned (B)" },
                { id: "mix", label: "Dry / Wet Mix" },
                { id: "residual", label: "Processing Difference / Residual" },
              ] as const
            ).map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={listenMode === item.id}
                onClick={() => handleModeSwitch(item.id)}
                className={`rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                  listenMode === item.id
                    ? item.id === "residual"
                      ? "bg-studio-amber/20 text-studio-amber"
                      : "bg-studio-cyan/20 text-studio-cyan"
                    : "text-studio-muted hover:text-studio-text"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          <span className="font-mono text-xs tabular-nums text-studio-muted">
            {formatTimecode(audioState.currentTime)} /{" "}
            {formatTimecode(audioState.duration)}
          </span>
        </div>

        {/* Live Sample-Locked Dry/Wet Comparison Slider */}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded border border-studio-border bg-studio-bg/60 px-4 py-2.5 text-xs">
          <div className="flex items-center gap-3">
            <label
              htmlFor="live-dry-wet-compare"
              className="font-medium text-studio-text"
            >
              Live A/B Dry/Wet Compare
            </label>
            <span className="font-mono text-[11px] tabular-nums text-studio-cyan">
              {Math.round((1 - liveWetMix) * 100)}% Original /{" "}
              {Math.round(liveWetMix * 100)}% Cleaned
            </span>
          </div>
          <input
            id="live-dry-wet-compare"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={liveWetMix}
            onChange={(e) => handleLiveMixChange(Number(e.target.value))}
            className="h-1.5 w-48 accent-studio-cyan"
          />
        </div>

        {listenMode === "residual" && (
          <div className="mt-3 rounded border border-studio-amber/40 bg-studio-amber/10 px-4 py-2.5 text-[11px] leading-relaxed text-studio-amber">
            <span className="font-semibold">Processing Difference / Residual: </span>
            {result.residual_disclosure}
          </div>
        )}

        {/* Dual Synchronized Waveforms (Original & Cleaned + Optional Residual) */}
        <div className="mt-4 space-y-2.5">
          <WaveformStrip
            label="Original (A) Waveform"
            waveform={session.waveform}
            progressFrac={progressFrac}
            active={listenMode === "original" || listenMode === "mix"}
            accentColor="#94A3B8"
            onSeekFraction={handleSeekFraction}
          />
          <WaveformStrip
            label="Cleaned (B) Waveform"
            waveform={result.processed_waveform}
            progressFrac={progressFrac}
            active={listenMode === "processed" || listenMode === "mix"}
            accentColor="#2DD4BF"
            onSeekFraction={handleSeekFraction}
          />
          {listenMode === "residual" && (
            <WaveformStrip
              label="Processing Difference / Residual Waveform (Unnormalized)"
              waveform={result.residual_waveform}
              progressFrac={progressFrac}
              active={true}
              accentColor="#D99B26"
              onSeekFraction={handleSeekFraction}
            />
          )}
        </div>

        {audioState.error && (
          <div
            role="alert"
            className="mt-3 rounded border border-studio-danger/40 bg-studio-danger/10 px-4 py-2.5 text-xs text-studio-danger"
          >
            Comparison playback error: {audioState.error}
          </div>
        )}

        {/* Transport Bar */}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!audioState.ready}
              onClick={handlePlayPause}
              className="rounded border border-studio-cyan/60 bg-studio-cyan/15 px-4 py-1.5 text-xs font-medium text-studio-cyan transition-colors hover:bg-studio-cyan/25 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {audioState.playing ? "Pause Comparison" : "Play Comparison"}
            </button>

            <button
              type="button"
              disabled={!audioState.ready}
              onClick={handleStop}
              className="rounded border border-studio-border bg-studio-elevated px-3 py-1.5 text-xs text-studio-text transition-colors hover:border-studio-subtle disabled:cursor-not-allowed disabled:opacity-40"
            >
              Stop
            </button>

            {audioState.loading && (
              <span className="font-mono text-[11px] text-studio-subtle">
                Decoding synchronized comparison buffers...
              </span>
            )}
          </div>

          <div className="flex items-center gap-2 text-xs">
            <button
              type="button"
              onClick={() => {
                const next = !muted;
                setMuted(next);
                engineRef.current?.setMuted(next);
              }}
              className="font-mono text-[11px] text-studio-muted hover:text-studio-text"
            >
              {muted ? "Muted" : "Output"}
            </button>
            <input
              type="range"
              aria-label="Comparison monitor volume"
              min={0}
              max={1}
              step={0.05}
              value={muted ? 0 : volume}
              onChange={(e) => {
                const next = Number(e.target.value);
                setVolume(next);
                engineRef.current?.setVolume(next);
                if (next > 0 && muted) {
                  setMuted(false);
                  engineRef.current?.setMuted(false);
                }
              }}
              className="h-1 w-24 accent-studio-cyan"
            />
          </div>
        </div>

        {/* Output Metadata, Level Comparison & Transparent Action Log */}
        <div className="mt-5 grid grid-cols-1 gap-4 border-t border-studio-border pt-4 lg:grid-cols-12">
          <div className="lg:col-span-6">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-studio-subtle">
              Objective Output Levels (Before → After)
            </p>
            <dl className="mt-2.5 grid grid-cols-2 gap-3 text-xs">
              <div>
                <dt className="text-[10px] uppercase text-studio-subtle">
                  Sample Peak
                </dt>
                <dd className="mt-0.5 font-mono text-[11px] tabular-nums text-studio-text">
                  {formatDb(result.original_levels.sample_peak_dbfs, "dBFS")} →{" "}
                  {formatDb(result.processed_levels.sample_peak_dbfs, "dBFS")}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase text-studio-subtle">
                  True Peak (4x)
                </dt>
                <dd className="mt-0.5 font-mono text-[11px] tabular-nums text-studio-text">
                  {formatDb(result.original_levels.true_peak_dbtp, "dBTP")} →{" "}
                  {formatDb(result.processed_levels.true_peak_dbtp, "dBTP")}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase text-studio-subtle">
                  Integrated Loudness
                </dt>
                <dd className="mt-0.5 font-mono text-[11px] tabular-nums text-studio-amber">
                  {formatDb(result.original_levels.integrated_lufs, "LUFS")} →{" "}
                  {formatDb(result.processed_levels.integrated_lufs, "LUFS")}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase text-studio-subtle">
                  Residual Difference RMS
                </dt>
                <dd className="mt-0.5 font-mono text-[11px] tabular-nums text-studio-muted">
                  {formatDb(result.residual_levels.rms_dbfs, "dBFS")}
                </dd>
              </div>
            </dl>
          </div>

          <div className="lg:col-span-6">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-studio-subtle">
              Applied DSP Actions &amp; Safeguards
            </p>
            <ul className="mt-2 space-y-1 text-[11px] leading-relaxed text-studio-muted">
              {result.actions.notes.map((note, idx) => (
                <li key={idx}>· {note}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
