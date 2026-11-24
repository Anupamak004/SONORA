import type { HealthResponse } from "../../types/api";

interface SystemStatusPanelProps {
  health: HealthResponse;
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rem = seconds % 60;
  return rem === 0 ? `${minutes} min` : `${minutes}m ${rem}s`;
}

export function SystemStatusPanel({ health }: SystemStatusPanelProps) {
  return (
    <section
      aria-labelledby="system-status-heading"
      className="border-b border-studio-border bg-studio-surface"
    >
      <div className="border-b border-studio-border px-5 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2
            id="system-status-heading"
            className="text-xs font-semibold uppercase tracking-[0.12em] text-studio-muted"
          >
            System Diagnostics &amp; Engine Readiness
          </h2>
          <span className="font-mono text-xs text-studio-cyan">
            {health.stage}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 divide-y divide-studio-border md:grid-cols-3 md:divide-x md:divide-y-0">
        {/* Media Tooling */}
        <div className="p-5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-studio-subtle">
            Local Media Toolchain
          </p>
          <dl className="mt-3 space-y-2.5 text-xs">
            <div className="flex items-center justify-between gap-2">
              <dt className="text-studio-muted">FFmpeg</dt>
              <dd
                className={`font-mono ${
                  health.ffmpeg.available
                    ? "text-studio-ok"
                    : "text-studio-warn"
                }`}
              >
                {health.ffmpeg.available ? "Detected" : "Missing (WAV/FLAC only)"}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-studio-muted">FFprobe</dt>
              <dd
                className={`font-mono ${
                  health.ffprobe.available
                    ? "text-studio-ok"
                    : "text-studio-warn"
                }`}
              >
                {health.ffprobe.available ? "Detected" : "Missing"}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-studio-muted">Python Runtime</dt>
              <dd className="font-mono tabular-nums text-studio-text">
                {health.python_version}
              </dd>
            </div>
          </dl>
          {health.ffmpeg.version && (
            <p
              className="mt-3 truncate font-mono text-[11px] text-studio-subtle"
              title={health.ffmpeg.version}
            >
              {health.ffmpeg.version}
            </p>
          )}
        </div>

        {/* Enforced Safety Limits */}
        <div className="p-5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-studio-subtle">
            Enforced Ingestion Limits
          </p>
          <dl className="mt-3 space-y-2.5 text-xs">
            <div className="flex items-center justify-between gap-2">
              <dt className="text-studio-muted">Max Upload Size</dt>
              <dd className="font-mono tabular-nums text-studio-text">
                {health.limits.max_upload_mb} MB
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-studio-muted">Max Duration</dt>
              <dd className="font-mono tabular-nums text-studio-text">
                {formatDuration(health.limits.max_duration_seconds)}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-studio-muted">Max Decoded PCM</dt>
              <dd className="font-mono tabular-nums text-studio-text">
                {health.limits.max_decoded_pcm_mb} MB
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-studio-muted">Allowed Formats</dt>
              <dd className="font-mono uppercase text-studio-text">
                {health.limits.supported_upload_formats.join(" / ")}
              </dd>
            </div>
          </dl>
        </div>

        {/* Scoped Temp Storage */}
        <div className="p-5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-studio-subtle">
            Session Workspace
          </p>
          <dl className="mt-3 space-y-2.5 text-xs">
            <div className="flex items-center justify-between gap-2">
              <dt className="text-studio-muted">Temp Store</dt>
              <dd
                className={`font-mono ${
                  health.storage.temp_dir_ready
                    ? "text-studio-ok"
                    : "text-studio-danger"
                }`}
              >
                {health.storage.temp_dir_ready ? "Writable" : "Unavailable"}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-studio-muted">Auto-Cleanup TTL</dt>
              <dd className="font-mono tabular-nums text-studio-text">
                {health.storage.session_ttl_minutes} min
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-studio-muted">Environment</dt>
              <dd className="font-mono text-studio-text">
                {health.environment}
              </dd>
            </div>
          </dl>
        </div>
      </div>

      {/* Engine Matrix */}
      <div className="border-t border-studio-border p-5">
        <p className="text-[11px] font-medium uppercase tracking-wider text-studio-subtle">
          Processing Engine Registry (Status Verified from Backend)
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-studio-border text-[11px] uppercase tracking-wider text-studio-subtle">
                <th className="py-2 pr-4 font-medium">Engine</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 pr-4 font-medium">Target</th>
                <th className="py-2 font-medium">Role &amp; Documented Limitations</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-studio-border/70">
              {health.engines.map((engine) => (
                <tr key={engine.id} className="align-top">
                  <td className="py-2.5 pr-4 font-medium text-studio-text">
                    <div>{engine.name}</div>
                    <div className="mt-0.5 font-mono text-[11px] text-studio-subtle">
                      {engine.optional_dependency
                        ? "Optional AI Dependency"
                        : "Core — Zero AI Downloads"}
                    </div>
                  </td>
                  <td className="py-2.5 pr-4">
                    <span
                      className={`inline-block rounded border px-2 py-0.5 font-mono text-[11px] ${
                        engine.available
                          ? "border-studio-ok/40 bg-studio-ok/10 text-studio-ok"
                          : "border-studio-border bg-studio-bg text-studio-muted"
                      }`}
                    >
                      {engine.available ? "Ready" : "Not Implemented Yet"}
                    </span>
                  </td>
                  <td className="py-2.5 pr-4 font-mono text-[11px] text-studio-amber">
                    {engine.target_stage}
                  </td>
                  <td className="py-2.5 text-studio-muted">
                    <p className="text-studio-text/90">{engine.role}</p>
                    <p className="mt-1 text-[11px] text-studio-subtle">
                      Limitation: {engine.limitations}
                    </p>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
