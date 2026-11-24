import type { InstrumentProfile } from "../../types/api";

interface ProfilePreviewPanelProps {
  profiles: InstrumentProfile[];
  selectedId: string;
  onSelect: (profileId: string) => void;
}

export function ProfilePreviewPanel({
  profiles,
  selectedId,
  onSelect,
}: ProfilePreviewPanelProps) {
  const activeProfile =
    profiles.find((profile) => profile.id === selectedId) ?? profiles[0];

  if (!activeProfile) {
    return null;
  }

  return (
    <section
      aria-labelledby="profiles-heading"
      className="bg-studio-surface"
    >
      <div className="border-b border-studio-border px-5 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2
            id="profiles-heading"
            className="text-xs font-semibold uppercase tracking-[0.12em] text-studio-muted"
          >
            Instrument Preservation Profiles
          </h2>
          <span className="font-mono text-[11px] text-studio-subtle">
            Configurable defaults loaded from /api/v1/profiles
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 divide-y divide-studio-border lg:grid-cols-12 lg:divide-x lg:divide-y-0">
        {/* Profile Selector List */}
        <div
          role="tablist"
          aria-label="Instrument profiles"
          className="divide-y divide-studio-border/60 lg:col-span-4"
        >
          {profiles.map((profile) => {
            const isSelected = profile.id === activeProfile.id;
            return (
              <button
                key={profile.id}
                type="button"
                role="tab"
                aria-selected={isSelected}
                onClick={() => onSelect(profile.id)}
                className={`flex w-full items-center justify-between px-5 py-3 text-left text-xs transition-colors ${
                  isSelected
                    ? "bg-studio-elevated text-studio-text"
                    : "text-studio-muted hover:bg-studio-elevated/50 hover:text-studio-text"
                }`}
              >
                <span className="font-medium">{profile.name}</span>
                <span
                  className={`font-mono text-[11px] tabular-nums ${
                    isSelected ? "text-studio-amber" : "text-studio-subtle"
                  }`}
                >
                  HPF {profile.default_hpf_hz} Hz
                </span>
              </button>
            );
          })}
        </div>

        {/* Active Profile Parameter Readout */}
        <div role="tabpanel" className="p-5 lg:col-span-8">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-studio-text">
              {activeProfile.name}
            </h3>
            <span className="font-mono text-[11px] text-studio-cyan">
              id: {activeProfile.id}
            </span>
          </div>
          <p className="mt-1.5 text-xs leading-relaxed text-studio-muted">
            {activeProfile.description}
          </p>

          <dl className="mt-5 grid grid-cols-2 gap-4 border-y border-studio-border py-4 sm:grid-cols-4">
            <div>
              <dt className="text-[11px] uppercase tracking-wider text-studio-subtle">
                Fundamental Band
              </dt>
              <dd className="mt-1 font-mono text-xs tabular-nums text-studio-text">
                {activeProfile.fundamental_min_hz}–{activeProfile.fundamental_max_hz} Hz
              </dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wider text-studio-subtle">
                HPF Range (Default)
              </dt>
              <dd className="mt-1 font-mono text-xs tabular-nums text-studio-text">
                {activeProfile.min_hpf_hz}–{activeProfile.max_hpf_hz} Hz (
                {activeProfile.default_hpf_hz})
              </dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wider text-studio-subtle">
                Transient Guard
              </dt>
              <dd className="mt-1 font-mono text-xs tabular-nums text-studio-text">
                {Math.round(activeProfile.transient_protection * 100)}%
              </dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wider text-studio-subtle">
                Max Attenuation Cap
              </dt>
              <dd className="mt-1 font-mono text-xs tabular-nums text-studio-text">
                -{activeProfile.default_attenuation_limit_db} dB
              </dd>
            </div>
          </dl>

          <div className="mt-4 flex flex-wrap gap-2 text-[11px] font-mono">
            {activeProfile.protect_fundamentals && (
              <span className="rounded border border-studio-border bg-studio-bg px-2 py-0.5 text-studio-ok">
                Fundamental Protection: ON
              </span>
            )}
            {activeProfile.protect_harmonics && (
              <span className="rounded border border-studio-border bg-studio-bg px-2 py-0.5 text-studio-ok">
                Harmonic Protection: ON
              </span>
            )}
            {activeProfile.pitch_safe_hum_guard && (
              <span className="rounded border border-studio-border bg-studio-bg px-2 py-0.5 text-studio-amber">
                Pitch-Safe 50/60 Hz Hum Guard: ON
              </span>
            )}
          </div>

          <p className="mt-3 text-xs leading-relaxed text-studio-muted">
            <span className="font-medium text-studio-text">Hum / Pitch Note: </span>
            {activeProfile.hum_conflict_note}
          </p>
        </div>
      </div>
    </section>
  );
}
