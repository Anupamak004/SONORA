import type { HealthResponse } from "../../types/api";

interface StudioHeaderProps {
  health: HealthResponse | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}

export function StudioHeader({
  health,
  loading,
  error,
  onRefresh,
}: StudioHeaderProps) {
  const isConnected = health !== null && !error;
  const isHealthy = health?.status === "ok";

  return (
    <header className="border-b border-studio-border bg-studio-surface/95">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-3.5 sm:px-6">
        <div className="flex items-center gap-3.5">
          <div
            aria-hidden="true"
            className="flex h-8 w-8 items-center justify-center rounded border border-studio-border bg-studio-elevated font-mono text-xs font-semibold tracking-wider text-studio-amber"
          >
            SN
          </div>
          <div>
            <div className="flex items-baseline gap-2.5">
              <h1 className="text-sm font-semibold tracking-[0.14em] text-studio-text">
                SONORA
              </h1>
              <span className="font-mono text-[11px] text-studio-muted">
                {health ? health.version : "v0.1.0"}
              </span>
            </div>
            <p className="text-xs text-studio-muted">
              Musical Instrument Audio Restoration Workspace
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div
            role="status"
            aria-live="polite"
            className="flex items-center gap-2 rounded border border-studio-border bg-studio-bg px-2.5 py-1 text-xs"
          >
            <span
              className={`h-2 w-2 rounded-full ${
                loading
                  ? "bg-studio-muted"
                  : isConnected && isHealthy
                    ? "bg-studio-ok"
                    : isConnected
                      ? "bg-studio-warn"
                      : "bg-studio-danger"
              }`}
            />
            <span className="font-mono text-[11px] text-studio-text">
              {loading
                ? "Checking backend..."
                : isConnected && isHealthy
                  ? "Backend Online"
                  : isConnected
                    ? "Backend Degraded"
                    : "Backend Offline"}
            </span>
          </div>

          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="rounded border border-studio-border bg-studio-elevated px-2.5 py-1 text-xs font-medium text-studio-text transition-colors hover:border-studio-subtle hover:bg-studio-border/60 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Refresh
          </button>
        </div>
      </div>
    </header>
  );
}
