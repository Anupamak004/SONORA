import type { SessionDetail } from "../../types/api";

interface AudioMetadataInspectorProps {
  session: SessionDetail;
  onDelete: (sessionId: string) => void;
  deleting: boolean;
}

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds - mins * 60;
  return `${mins}:${secs.toFixed(2).padStart(5, "0")}`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatDb(value: number | null, unit: string): string {
  if (value === null) return "N/A";
  return `${value.toFixed(2)} ${unit}`;
}

export function AudioMetadataInspector({
  session,
  onDelete,
  deleting,
}: AudioMetadataInspectorProps) {
  const { metadata } = session;
  const channelLabel =
    metadata.channels === 1
      ? "Mono (1 ch)"
      : metadata.channels === 2
        ? "Stereo (2 ch)"
        : `${metadata.channels} ch`;

  const precisionLabel =
    metadata.bit_depth !== null
      ? `${metadata.bit_depth}-bit`
      : metadata.bitrate_kbps !== null
        ? `Lossy (${metadata.bitrate_kbps} kbps)`
        : "Lossy (N/A)";

  return (
    <div className="border-b border-studio-border">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-studio-border px-5 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <span className="rounded border border-studio-cyan/40 bg-studio-cyan/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase text-studio-cyan">
              {metadata.format}
            </span>
            <h3 className="truncate text-sm font-semibold text-studio-text" title={session.display_name}>
              {session.display_name}
            </h3>
          </div>
          <p className="mt-0.5 font-mono text-[11px] text-studio-subtle">
            Session {session.session_id.slice(0, 8)} · Codec: {metadata.codec} · Size:{" "}
            {formatFileSize(metadata.file_size_bytes)}
          </p>
        </div>

        <button
          type="button"
          onClick={() => onDelete(session.session_id)}
          disabled={deleting}
          className="rounded border border-studio-border bg-studio-elevated px-3 py-1 text-xs text-studio-muted transition-colors hover:border-studio-danger/50 hover:text-studio-danger disabled:opacity-50"
        >
          {deleting ? "Removing..." : "Remove Session"}
        </button>
      </div>

      {/* Stream Format Readouts */}
      <dl className="grid grid-cols-2 divide-y divide-studio-border sm:grid-cols-4 sm:divide-x sm:divide-y-0">
        <div className="px-5 py-3">
          <dt className="text-[11px] uppercase tracking-wider text-studio-subtle">
            Sample Rate
          </dt>
          <dd className="mt-1 font-mono text-xs tabular-nums text-studio-text">
            {(metadata.sample_rate / 1000).toFixed(
              metadata.sample_rate % 1000 === 0 ? 0 : 1,
            )}{" "}
            kHz ({metadata.sample_rate} Hz)
          </dd>
        </div>
        <div className="px-5 py-3">
          <dt className="text-[11px] uppercase tracking-wider text-studio-subtle">
            Channels
          </dt>
          <dd className="mt-1 font-mono text-xs text-studio-text">
            {channelLabel}
          </dd>
        </div>
        <div className="px-5 py-3">
          <dt className="text-[11px] uppercase tracking-wider text-studio-subtle">
            Duration
          </dt>
          <dd className="mt-1 font-mono text-xs tabular-nums text-studio-text">
            {formatDuration(metadata.duration_seconds)}
          </dd>
        </div>
        <div className="px-5 py-3">
          <dt className="text-[11px] uppercase tracking-wider text-studio-subtle">
            Bit Depth / Rate
          </dt>
          <dd className="mt-1 font-mono text-xs tabular-nums text-studio-text">
            {precisionLabel}
          </dd>
        </div>
      </dl>

      {/* Objective Level & ITU-R BS.1770 Loudness Readouts */}
      <dl className="grid grid-cols-2 divide-y divide-studio-border border-t border-studio-border bg-studio-bg/40 sm:grid-cols-4 sm:divide-x sm:divide-y-0">
        <div className="px-5 py-3">
          <dt className="text-[11px] uppercase tracking-wider text-studio-subtle">
            Sample Peak
          </dt>
          <dd className="mt-1 font-mono text-xs tabular-nums text-studio-text">
            {formatDb(metadata.sample_peak_dbfs, "dBFS")}
          </dd>
        </div>
        <div className="px-5 py-3">
          <dt className="text-[11px] uppercase tracking-wider text-studio-subtle">
            True Peak (4x)
          </dt>
          <dd
            className={`mt-1 font-mono text-xs tabular-nums ${
              metadata.true_peak_dbtp !== null && metadata.true_peak_dbtp > -0.3
                ? "text-studio-warn"
                : "text-studio-text"
            }`}
          >
            {formatDb(metadata.true_peak_dbtp, "dBTP")}
          </dd>
        </div>
        <div className="px-5 py-3">
          <dt className="text-[11px] uppercase tracking-wider text-studio-subtle">
            RMS Level
          </dt>
          <dd className="mt-1 font-mono text-xs tabular-nums text-studio-text">
            {formatDb(metadata.rms_dbfs, "dBFS")}
          </dd>
        </div>
        <div className="px-5 py-3">
          <dt className="text-[11px] uppercase tracking-wider text-studio-subtle">
            Integrated Loudness
          </dt>
          <dd className="mt-1 font-mono text-xs tabular-nums text-studio-amber">
            {formatDb(metadata.integrated_lufs, "LUFS")}
          </dd>
        </div>
      </dl>

      {metadata.loudness_note && (
        <div className="border-t border-studio-border bg-studio-bg/60 px-5 py-2 text-[11px] text-studio-muted">
          Loudness note: {metadata.loudness_note}
        </div>
      )}
    </div>
  );
}
