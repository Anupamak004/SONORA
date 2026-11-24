import type { SessionSummary } from "../../types/api";

interface RecentSessionsBarProps {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
}

export function RecentSessionsBar({
  sessions,
  activeSessionId,
  onSelect,
  onDelete,
}: RecentSessionsBarProps) {
  if (sessions.length === 0) {
    return null;
  }

  return (
    <section
      aria-labelledby="recent-sessions-heading"
      className="border border-studio-border bg-studio-surface"
    >
      <div className="flex items-center justify-between border-b border-studio-border px-5 py-2.5">
        <h2
          id="recent-sessions-heading"
          className="text-xs font-semibold uppercase tracking-[0.12em] text-studio-muted"
        >
          Active Local Sessions
        </h2>
        <span className="font-mono text-[11px] tabular-nums text-studio-subtle">
          {sessions.length} stored in temp workspace
        </span>
      </div>

      <ul className="divide-y divide-studio-border/70">
        {sessions.map((item) => {
          const isActive = item.session_id === activeSessionId;
          return (
            <li
              key={item.session_id}
              className={`flex flex-wrap items-center justify-between gap-3 px-5 py-2.5 text-xs ${
                isActive ? "bg-studio-elevated" : "hover:bg-studio-elevated/40"
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(item.session_id)}
                className="flex min-w-0 flex-1 items-center gap-3 text-left"
              >
                <span className="rounded border border-studio-border bg-studio-bg px-1.5 py-0.5 font-mono text-[10px] uppercase text-studio-amber">
                  {item.format}
                </span>
                <span className="truncate font-medium text-studio-text">
                  {item.display_name}
                </span>
                <span className="hidden font-mono text-[11px] tabular-nums text-studio-subtle sm:inline">
                  {(item.sample_rate / 1000).toFixed(
                    item.sample_rate % 1000 === 0 ? 0 : 1,
                  )}{" "}
                  kHz · {item.channels === 1 ? "Mono" : "Stereo"} ·{" "}
                  {item.duration_seconds.toFixed(1)}s
                </span>
              </button>

              <button
                type="button"
                onClick={() => onDelete(item.session_id)}
                aria-label={`Delete session ${item.display_name}`}
                className="font-mono text-[11px] text-studio-subtle transition-colors hover:text-studio-danger"
              >
                Delete
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
