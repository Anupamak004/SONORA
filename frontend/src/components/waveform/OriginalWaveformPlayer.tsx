import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { resolveApiUrl } from "../../api/client";
import type { SessionDetail } from "../../types/api";

interface OriginalWaveformPlayerProps {
  session: SessionDetail;
}

function formatTimecode(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00.0";
  const mins = Math.floor(seconds / 60);
  const secs = seconds - mins * 60;
  return `${mins}:${secs.toFixed(1).padStart(4, "0")}`;
}

export function OriginalWaveformPlayer({
  session,
}: OriginalWaveformPlayerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const wavesurferRef = useRef<WaveSurfer | null>(null);

  const [isReady, setIsReady] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(session.metadata.duration_seconds);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [zoomPxPerSec, setZoomPxPerSec] = useState(0);
  const [playbackError, setPlaybackError] = useState<string | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    setIsReady(false);
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(session.metadata.duration_seconds);
    setPlaybackError(null);

    const ws = WaveSurfer.create({
      container,
      url: resolveApiUrl(session.original_audio_url),
      peaks: [session.waveform.peaks],
      duration: session.metadata.duration_seconds,
      height: 112,
      waveColor: "#3B4758",
      progressColor: "#2DD4BF",
      cursorColor: "#D99B26",
      cursorWidth: 2,
      barWidth: 2,
      barGap: 1,
      barRadius: 1,
      normalize: false,
      interact: true,
    });

    wavesurferRef.current = ws;

    ws.on("ready", (decodedDuration) => {
      setIsReady(true);
      if (Number.isFinite(decodedDuration) && decodedDuration > 0) {
        setDuration(decodedDuration);
      }
      ws.setVolume(muted ? 0 : volume);
    });

    ws.on("play", () => setIsPlaying(true));
    ws.on("pause", () => setIsPlaying(false));
    ws.on("finish", () => setIsPlaying(false));
    ws.on("timeupdate", (time) => setCurrentTime(time));
    ws.on("error", (err) => {
      setPlaybackError(
        err instanceof Error
          ? err.message
          : "Browser could not decode or stream this audio recording.",
      );
    });

    return () => {
      wavesurferRef.current = null;
      ws.destroy();
    };
  }, [
    session.session_id,
    session.original_audio_url,
    session.metadata.duration_seconds,
    session.waveform.peaks,
  ]);

  useEffect(() => {
    const ws = wavesurferRef.current;
    if (!ws) return;
    ws.setVolume(muted ? 0 : volume);
  }, [volume, muted]);

  useEffect(() => {
    const ws = wavesurferRef.current;
    if (!ws || !isReady) return;
    ws.zoom(zoomPxPerSec);
  }, [zoomPxPerSec, isReady]);

  const handlePlayPause = () => {
    const ws = wavesurferRef.current;
    if (!ws) return;
    void ws.playPause();
  };

  const handleStop = () => {
    const ws = wavesurferRef.current;
    if (!ws) return;
    ws.stop();
    setCurrentTime(0);
    setIsPlaying(false);
  };

  return (
    <div className="p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-studio-cyan" />
          <span className="text-xs font-medium text-studio-text">
            Original Recording Waveform
          </span>
        </div>
        <span className="font-mono text-xs tabular-nums text-studio-muted">
          {formatTimecode(currentTime)} / {formatTimecode(duration)}
        </span>
      </div>

      {/* WaveSurfer Canvas Host */}
      <div
        className="overflow-x-auto rounded border border-studio-border bg-studio-bg px-3 py-3"
        aria-label="Original audio waveform"
      >
        <div ref={containerRef} />
      </div>

      {playbackError && (
        <div
          role="alert"
          className="mt-3 rounded border border-studio-danger/40 bg-studio-danger/10 px-3.5 py-2 text-xs text-studio-danger"
        >
          Playback error: {playbackError}
        </div>
      )}

      {/* Transport & View Controls */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handlePlayPause}
            disabled={!isReady}
            className="rounded border border-studio-cyan/50 bg-studio-cyan/15 px-4 py-1.5 text-xs font-medium text-studio-cyan transition-colors hover:bg-studio-cyan/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isPlaying ? "Pause" : "Play Original"}
          </button>

          <button
            type="button"
            onClick={handleStop}
            disabled={!isReady}
            className="rounded border border-studio-border bg-studio-elevated px-3 py-1.5 text-xs text-studio-text transition-colors hover:border-studio-subtle disabled:cursor-not-allowed disabled:opacity-40"
          >
            Stop
          </button>

          {!isReady && !playbackError && (
            <span className="font-mono text-[11px] text-studio-subtle">
              Loading audio stream...
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-5 text-xs">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setMuted((prev) => !prev)}
              className="font-mono text-[11px] text-studio-muted hover:text-studio-text"
            >
              {muted ? "Muted" : "Monitor"}
            </button>
            <input
              type="range"
              aria-label="Playback volume"
              min={0}
              max={1}
              step={0.05}
              value={muted ? 0 : volume}
              onChange={(e) => {
                const next = Number(e.target.value);
                setVolume(next);
                if (next > 0 && muted) setMuted(false);
              }}
              className="h-1 w-24 accent-studio-cyan"
            />
          </div>

          <div className="flex items-center gap-2">
            <label
              htmlFor="waveform-zoom"
              className="font-mono text-[11px] text-studio-muted"
            >
              Zoom
            </label>
            <input
              id="waveform-zoom"
              type="range"
              min={0}
              max={200}
              step={10}
              value={zoomPxPerSec}
              disabled={!isReady}
              onChange={(e) => setZoomPxPerSec(Number(e.target.value))}
              className="h-1 w-24 accent-studio-amber disabled:opacity-40"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
