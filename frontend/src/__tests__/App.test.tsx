import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type {
  HealthResponse,
  ProfilesResponse,
  SessionsListResponse,
} from "../types/api";

const MOCK_HEALTH: HealthResponse = {
  status: "ok",
  app_name: "SONORA",
  version: "0.1.0-stage1",
  stage: "Stage 2 — Secure Audio Ingestion & Playback",
  environment: "test",
  python_version: "3.13.1",
  ffmpeg: { available: true, version: "ffmpeg version 7.1", notes: null },
  ffprobe: { available: true, version: "ffprobe version 7.1", notes: null },
  storage: { temp_dir_ready: true, session_ttl_minutes: 60 },
  limits: {
    max_upload_mb: 150,
    max_duration_seconds: 900,
    max_decoded_pcm_mb: 512,
    supported_upload_formats: ["wav", "flac", "mp3"],
  },
  engines: [
    {
      id: "precision_musical_dsp",
      name: "Precision Musical DSP (MMSE-LSA + Pitch-Safe Filters)",
      category: "precision_dsp",
      implemented: false,
      available: false,
      optional_dependency: false,
      target_stage: "Stage 4",
      role: "Primary offline and real-time foundation.",
      limitations: "Cannot cleanly separate overlapping non-stationary speech.",
    },
  ],
};

const MOCK_PROFILES: ProfilesResponse = {
  profiles: [
    {
      id: "general",
      name: "General / Balanced Instrument",
      description: "Balanced protection for mixed instruments.",
      fundamental_min_hz: 40,
      fundamental_max_hz: 4200,
      default_hpf_hz: 35,
      min_hpf_hz: 20,
      max_hpf_hz: 120,
      protect_fundamentals: true,
      protect_harmonics: true,
      pitch_safe_hum_guard: true,
      transient_protection: 0.75,
      default_attenuation_limit_db: 12,
      default_strength: 0.55,
      hum_conflict_note: "Pitch-safe hum guard enabled.",
    },
    {
      id: "piano",
      name: "Piano / Keys",
      description: "Full-bandwidth protection from A0 (27.5 Hz).",
      fundamental_min_hz: 27.5,
      fundamental_max_hz: 4186,
      default_hpf_hz: 24,
      min_hpf_hz: 18,
      max_hpf_hz: 80,
      protect_fundamentals: true,
      protect_harmonics: true,
      pitch_safe_hum_guard: true,
      transient_protection: 0.85,
      default_attenuation_limit_db: 10,
      default_strength: 0.5,
      hum_conflict_note: "Left-hand fundamentals overlap 50/60 Hz.",
    },
  ],
};

const EMPTY_SESSIONS: SessionsListResponse = { sessions: [] };

describe("App workspace shell", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders backend health diagnostics, upload zone, and allows switching instrument profiles", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (url: string) => {
        if (url.endsWith("/api/v1/health")) {
          return { ok: true, json: async () => MOCK_HEALTH };
        }
        if (url.endsWith("/api/v1/profiles")) {
          return { ok: true, json: async () => MOCK_PROFILES };
        }
        if (url.endsWith("/api/v1/sessions")) {
          return { ok: true, json: async () => EMPTY_SESSIONS };
        }
        return { ok: false, status: 404, json: async () => ({}) };
      }),
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Backend Online")).toBeInTheDocument();
    });

    expect(screen.getByText("Audio Ingestion")).toBeInTheDocument();
    expect(screen.getByText("150 MB")).toBeInTheDocument();
    expect(screen.getByText("Not Implemented Yet")).toBeInTheDocument();
    expect(screen.getByText("id: general")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Piano \/ Keys/i }));

    expect(screen.getByText("id: piano")).toBeInTheDocument();
    expect(
      screen.getByText(/Left-hand fundamentals overlap 50\/60 Hz/i),
    ).toBeInTheDocument();
  });

  it("shows an actionable error banner when the backend is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Failed to fetch")),
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("Backend Offline")).toBeInTheDocument();
    expect(screen.getByText(/Backend connection failed/i)).toBeInTheDocument();
  });
});
