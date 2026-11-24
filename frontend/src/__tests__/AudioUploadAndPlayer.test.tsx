import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import * as apiClient from "../api/client";
import type {
  HealthResponse,
  ProfilesResponse,
  SessionDetail,
  SessionsListResponse,
} from "../types/api";

// Mock WaveSurfer.js for JSDOM component verification
const mockPlayPause = vi.fn();
const mockStop = vi.fn();
const mockDestroy = vi.fn();
const mockSetVolume = vi.fn();
const mockZoom = vi.fn();
const wsHandlers: Record<string, ((...args: unknown[]) => void)[]> = {};

vi.mock("wavesurfer.js", () => ({
  default: {
    create: vi.fn((options: Record<string, unknown>) => {
      Object.keys(wsHandlers).forEach((k) => delete wsHandlers[k]);
      return {
        options,
        on: (event: string, cb: (...args: unknown[]) => void) => {
          wsHandlers[event] = wsHandlers[event] ?? [];
          wsHandlers[event].push(cb);
          if (event === "ready") {
            // Simulate immediate WaveSurfer ready callback
            cb(options.duration ?? 2.5);
          }
        },
        playPause: mockPlayPause,
        stop: mockStop,
        destroy: mockDestroy,
        setVolume: mockSetVolume,
        zoom: mockZoom,
      };
    }),
  },
}));

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
    max_upload_mb: 1,
    max_duration_seconds: 900,
    max_decoded_pcm_mb: 512,
    supported_upload_formats: ["wav", "flac", "mp3"],
  },
  engines: [],
};

const MOCK_PROFILES: ProfilesResponse = { profiles: [] };

const MOCK_SESSION: SessionDetail = {
  session_id: "11111111-2222-4333-8444-555555555555",
  display_name: "acoustic_guitar_take1.wav",
  created_at: "2026-11-23T17:00:00Z",
  expires_at: "2026-11-23T18:00:00Z",
  metadata: {
    format: "wav",
    codec: "pcm_s24le",
    container: "wav",
    sample_rate: 48000,
    channels: 2,
    duration_seconds: 12.5,
    frame_count: 600000,
    bit_depth: 24,
    bitrate_kbps: null,
    file_size_bytes: 3600044,
    sample_peak_dbfs: -6.2,
    true_peak_dbtp: -6.05,
    rms_dbfs: -18.4,
    integrated_lufs: -17.9,
    loudness_note: null,
  },
  waveform: {
    bucket_count: 4,
    peaks: [0.2, 0.5, 0.35, 0.1],
  },
  original_audio_url:
    "/api/v1/sessions/11111111-2222-4333-8444-555555555555/audio/original",
};

describe("Stage 2 Audio Upload, Metadata & WaveSurfer Playback", () => {
  const originalGetContext = HTMLCanvasElement.prototype.getContext;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(apiClient, "fetchHealth").mockResolvedValue(MOCK_HEALTH);
    vi.spyOn(apiClient, "fetchProfiles").mockResolvedValue(MOCK_PROFILES);
    vi.spyOn(apiClient, "fetchSessions").mockResolvedValue({
      sessions: [],
    } satisfies SessionsListResponse);
    vi.spyOn(apiClient, "analyzeSession").mockResolvedValue({
      session_id: MOCK_SESSION.session_id,
      sample_rate: 48000,
      channels: 2,
      duration_seconds: 12.5,
      signal_state: "normal",
      noise_floor: {
        method: "minimum_statistics_spectral_floor",
        broadband_noise_floor_dbfs: -68.0,
        active_signal_dbfs: -18.0,
        estimated_snr_db: 50.0,
        confidence: "high",
        sustained_tonal_warning: false,
        notes: ["Automatic silence-free estimate."],
      },
      detected_indicators: [],
      frequency_bands: [],
      psd: {
        frequencies_hz: [20, 1000, 20000],
        active_p90_db: [-40, -20, -50],
        overall_median_db: [-50, -30, -60],
        estimated_noise_floor_db: [-70, -70, -75],
      },
      spectrogram: {
        freq_scale: "log",
        db_min: -100,
        db_max: 0,
        n_fft: 2048,
        hop_length: 512,
        time_bins: 2,
        freq_bins: 2,
        times_sec: [0, 12.5],
        frequencies_hz: [20, 24000],
        magnitudes_u8: [
          [10, 20],
          [30, 40],
        ],
      },
      limitations: ["Read-only analysis."],
    });
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
      configurable: true,
      writable: true,
      value: vi.fn(() => ({
        createImageData: (w: number, h: number) => ({
          width: w,
          height: h,
          data: new Uint8ClampedArray(w * h * 4),
        }),
        putImageData: vi.fn(),
      })),
    });
  });

  afterEach(() => {
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
      configurable: true,
      writable: true,
      value: originalGetContext,
    });
    vi.restoreAllMocks();
  });

  it("uploads a valid recording, displays metadata & loudness, plays via WaveSurfer, and deletes session", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiClient, "uploadAudioFile").mockImplementation(
      async (_file, options) => {
        options?.onProgress?.({
          loadedBytes: 512,
          totalBytes: 1024,
          percent: 50,
        });
        options?.onProgress?.({
          loadedBytes: 1024,
          totalBytes: 1024,
          percent: 100,
        });
        return MOCK_SESSION;
      },
    );
    const deleteSpy = vi
      .spyOn(apiClient, "deleteSession")
      .mockResolvedValue(undefined);

    render(<App />);
    await waitFor(() =>
      expect(screen.getByText("Audio Ingestion")).toBeInTheDocument(),
    );

    const fileInput = screen.getByLabelText("Select audio recording");
    const wavFile = new File([new Uint8Array(1024)], "acoustic_guitar_take1.wav", {
      type: "audio/wav",
    });
    fireEvent.change(fileInput, { target: { files: [wavFile] } });

    await waitFor(() =>
      expect(screen.getByText("acoustic_guitar_take1.wav")).toBeInTheDocument(),
    );

    // Accurate metadata & loudness readouts
    expect(screen.getByText("48 kHz (48000 Hz)")).toBeInTheDocument();
    expect(screen.getByText("Stereo (2 ch)")).toBeInTheDocument();
    expect(screen.getByText("24-bit")).toBeInTheDocument();
    expect(screen.getByText("-6.20 dBFS")).toBeInTheDocument();
    expect(screen.getByText("-6.05 dBTP")).toBeInTheDocument();
    expect(screen.getByText("-17.90 LUFS")).toBeInTheDocument();

    // WaveSurfer transport interaction
    const playBtn = screen.getByRole("button", { name: /Play Original/i });
    await user.click(playBtn);
    expect(mockPlayPause).toHaveBeenCalledTimes(1);

    // Session deletion cleans up WaveSurfer instance
    const removeBtn = screen.getByRole("button", { name: /Remove Session/i });
    await user.click(removeBtn);
    await waitFor(() => expect(deleteSpy).toHaveBeenCalledWith(MOCK_SESSION.session_id));
    expect(mockDestroy).toHaveBeenCalled();
  });

  it("rejects oversized files immediately before uploading", async () => {
    const uploadSpy = vi.spyOn(apiClient, "uploadAudioFile");

    render(<App />);
    await waitFor(() =>
      expect(screen.getByText("Audio Ingestion")).toBeInTheDocument(),
    );

    const fileInput = screen.getByLabelText("Select audio recording");
    // Limit in MOCK_HEALTH is 1 MB
    const hugeFile = new File(
      [new Uint8Array(1024 * 1024 + 100)],
      "too_large.wav",
      { type: "audio/wav" },
    );
    fireEvent.change(fileInput, { target: { files: [hugeFile] } });

    await waitFor(() =>
      expect(screen.getByText("FILE_TOO_LARGE")).toBeInTheDocument(),
    );
    expect(uploadSpy).not.toHaveBeenCalled();
  });

  it("displays meaningful backend validation errors for malformed or unsupported files", async () => {
    vi.spyOn(apiClient, "uploadAudioFile").mockRejectedValue(
      new apiClient.ApiClientError(
        "File content does not match a supported WAV, FLAC, or MP3 header.",
        "UNSUPPORTED_AUDIO_FORMAT",
        422,
      ),
    );

    render(<App />);
    await waitFor(() =>
      expect(screen.getByText("Audio Ingestion")).toBeInTheDocument(),
    );

    const fileInput = screen.getByLabelText("Select audio recording");
    const fakeWav = new File(["plain text"], "spoofed.wav", {
      type: "audio/wav",
    });
    fireEvent.change(fileInput, { target: { files: [fakeWav] } });

    await waitFor(() =>
      expect(screen.getByText("UNSUPPORTED_AUDIO_FORMAT")).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/does not match a supported WAV, FLAC, or MP3 header/i),
    ).toBeInTheDocument();
  });
});
