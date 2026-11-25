import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import * as apiClient from "../api/client";
import type {
  AnalysisResponse,
  HealthResponse,
  ProcessResponse,
  ProfilesResponse,
  SessionDetail,
  SessionsListResponse,
} from "../types/api";

// Mock WaveSurfer for original waveform
vi.mock("wavesurfer.js", () => ({
  default: {
    create: vi.fn((options: Record<string, unknown>) => ({
      on: (event: string, cb: (...args: unknown[]) => void) => {
        if (event === "ready") cb(options.duration ?? 2.0);
      },
      playPause: vi.fn(),
      stop: vi.fn(),
      destroy: vi.fn(),
      setVolume: vi.fn(),
      zoom: vi.fn(),
    })),
  },
}));

// Mock AbAudioEngine so JSDOM tests verify real mode switching, dry/wet, and transport wiring
const mockEngineLoad = vi.fn();
const mockEnginePlay = vi.fn();
const mockEnginePause = vi.fn();
const mockEngineStop = vi.fn();
const mockEngineSetMode = vi.fn();
const mockEngineSetWetMix = vi.fn();
const mockEngineSeek = vi.fn();
const mockEngineDispose = vi.fn();

vi.mock("../audio/abAudioEngine", () => ({
  AbAudioEngine: vi.fn().mockImplementation((listener: (s: unknown) => void) => {
    return {
      load: mockEngineLoad.mockImplementation(async () => {
        listener({
          ready: true,
          loading: false,
          playing: false,
          currentTime: 0,
          duration: 2.4,
          error: null,
        });
      }),
      play: mockEnginePlay.mockImplementation(async () => {
        listener({
          ready: true,
          loading: false,
          playing: true,
          currentTime: 0.4,
          duration: 2.4,
          error: null,
        });
      }),
      pause: mockEnginePause,
      stop: mockEngineStop,
      setMode: mockEngineSetMode,
      setWetMix: mockEngineSetWetMix,
      setVolume: vi.fn(),
      setMuted: vi.fn(),
      seek: mockEngineSeek,
      dispose: mockEngineDispose,
    };
  }),
}));

const MOCK_HEALTH: HealthResponse = {
  status: "ok",
  app_name: "SONORA",
  version: "0.1.0-stage1",
  stage: "Stage 4 — Precision Musical DSP & Playable Comparison",
  environment: "test",
  python_version: "3.13.1",
  ffmpeg: { available: true, version: "ffmpeg 7.1", notes: null },
  ffprobe: { available: true, version: "ffprobe 7.1", notes: null },
  storage: { temp_dir_ready: true, session_ttl_minutes: 60 },
  limits: {
    max_upload_mb: 150,
    max_duration_seconds: 900,
    max_decoded_pcm_mb: 512,
    supported_upload_formats: ["wav", "flac", "mp3"],
  },
  engines: [],
};

const MOCK_SESSION: SessionDetail = {
  session_id: "22222222-3333-4444-8555-666666666666",
  display_name: "acoustic_with_hum.wav",
  created_at: "2026-11-24T05:00:00Z",
  expires_at: "2026-11-24T06:00:00Z",
  metadata: {
    format: "wav",
    codec: "pcm_s24le",
    container: "wav",
    sample_rate: 48000,
    channels: 2,
    duration_seconds: 2.4,
    frame_count: 115200,
    bit_depth: 24,
    bitrate_kbps: null,
    file_size_bytes: 691244,
    sample_peak_dbfs: -9.1,
    true_peak_dbtp: -9.0,
    rms_dbfs: -20.0,
    integrated_lufs: -19.2,
    loudness_note: null,
  },
  waveform: { bucket_count: 4, peaks: [0.2, 0.45, 0.35, 0.15] },
  original_audio_url:
    "/api/v1/sessions/22222222-3333-4444-8555-666666666666/audio/original",
};

const MOCK_ANALYSIS: AnalysisResponse = {
  session_id: MOCK_SESSION.session_id,
  sample_rate: 48000,
  channels: 2,
  duration_seconds: 2.4,
  signal_state: "normal",
  noise_floor: {
    method: "minimum_statistics_spectral_floor",
    broadband_noise_floor_dbfs: -60.0,
    active_signal_dbfs: -18.0,
    estimated_snr_db: 42.0,
    confidence: "moderate",
    sustained_tonal_warning: false,
    notes: ["Estimated automatically."],
  },
  detected_indicators: [],
  frequency_bands: [],
  psd: {
    frequencies_hz: [20, 1000, 20000],
    active_p90_db: [-40, -20, -60],
    overall_median_db: [-50, -30, -70],
    estimated_noise_floor_db: [-65, -65, -75],
  },
  spectrogram: {
    freq_scale: "log",
    db_min: -100,
    db_max: 0,
    n_fft: 2048,
    hop_length: 512,
    time_bins: 2,
    freq_bins: 2,
    times_sec: [0, 2.4],
    frequencies_hz: [20, 24000],
    magnitudes_u8: [
      [10, 20],
      [30, 40],
    ],
  },
  limitations: ["Diagnostic only."],
};

const MOCK_PROCESS_RESULT: ProcessResponse = {
  session_id: MOCK_SESSION.session_id,
  status: "completed",
  processing_mode: "applied",
  cached: false,
  params_hash: "abc123def4567890",
  processing_time_ms: 215.4,
  sample_rate: 48000,
  channels: 2,
  frame_count: 115200,
  duration_seconds: 2.4,
  settings_applied: {
    engine: "precision_musical_dsp",
    strength: 0.45,
    hum_reduction_enabled: true,
    hpf_enabled: false,
    hpf_cutoff_hz: 40,
    dry_wet_mix: 1.0,
    bypass: false,
    enable_limiter: false,
    limiter_ceiling_dbtp: -1.0,
  },
  actions: {
    dc_offset_removed: false,
    hpf_applied: false,
    hpf_cutoff_hz: null,
    hum_notches_applied: true,
    hum_notched_frequencies_hz: [60, 120, 180],
    broadband_applied_channels: [],
    broadband_skipped_clean_channels: [1, 2],
    limiter_engaged: false,
    limiter_gain_reduction_db: 0,
    notes: [
      "Channel 1: applied pitch-safe narrow-Q 60 Hz hum notches at 60.0 Hz, 120.0 Hz, 180.0 Hz.",
    ],
  },
  original_levels: {
    sample_peak_dbfs: -9.1,
    true_peak_dbtp: -9.0,
    rms_dbfs: -20.0,
    integrated_lufs: -19.2,
    loudness_note: null,
  },
  processed_levels: {
    sample_peak_dbfs: -9.8,
    true_peak_dbtp: -9.7,
    rms_dbfs: -20.4,
    integrated_lufs: -19.5,
    loudness_note: null,
  },
  residual_levels: {
    sample_peak_dbfs: -26.5,
    true_peak_dbtp: -26.4,
    rms_dbfs: -31.2,
    integrated_lufs: -32.0,
    loudness_note: null,
  },
  loudness_offset_db: 0.3,
  processed_waveform: { bucket_count: 4, peaks: [0.18, 0.42, 0.33, 0.14] },
  residual_waveform: { bucket_count: 4, peaks: [0.04, 0.04, 0.04, 0.04] },
  original_aligned_audio_url:
    "/api/v1/sessions/22222222-3333-4444-8555-666666666666/audio/original-aligned?v=abc123def4567890",
  processed_audio_url:
    "/api/v1/sessions/22222222-3333-4444-8555-666666666666/audio/processed?v=abc123def4567890",
  residual_audio_url:
    "/api/v1/sessions/22222222-3333-4444-8555-666666666666/audio/residual?v=abc123def4567890",
  residual_disclosure:
    "Processing Difference / Residual is computed sample-aligned as original[n] - final_processed[n] with no independent normalization.",
};

describe("Stage 4 Precision Musical DSP Controls & A/B Comparison Workflow", () => {
  const originalGetContext = HTMLCanvasElement.prototype.getContext;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(apiClient, "fetchHealth").mockResolvedValue(MOCK_HEALTH);
    vi.spyOn(apiClient, "fetchProfiles").mockResolvedValue({
      profiles: [],
    } satisfies ProfilesResponse);
    vi.spyOn(apiClient, "fetchSessions").mockResolvedValue({
      sessions: [],
    } satisfies SessionsListResponse);
    vi.spyOn(apiClient, "uploadAudioFile").mockResolvedValue(MOCK_SESSION);
    vi.spyOn(apiClient, "analyzeSession").mockResolvedValue(MOCK_ANALYSIS);
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

  it("runs DSP processing, loads playable comparison audio, supports A/B switching, live dry/wet, and residual disclosure", async () => {
    const user = userEvent.setup();
    let resolveProcess: ((val: ProcessResponse) => void) | null = null;
    const processSpy = vi
      .spyOn(apiClient, "processSession")
      .mockImplementation(
        () =>
          new Promise<ProcessResponse>((resolve) => {
            resolveProcess = resolve;
          }),
      );

    render(<App />);
    await waitFor(() =>
      expect(screen.getByText("Audio Ingestion")).toBeInTheDocument(),
    );

    // Upload a file to enter studio workflow
    const input = screen.getByLabelText("Select audio recording");
    const wavFile = new File([new Uint8Array(1024)], "acoustic_with_hum.wav", {
      type: "audio/wav",
    });
    fireEvent.change(input, { target: { files: [wavFile] } });

    await waitFor(() =>
      expect(screen.getByText("Precision Musical DSP Controls")).toBeInTheDocument(),
    );

    // Click Process Audio and verify honest loading state
    await user.click(screen.getByRole("button", { name: /^Process Audio$/i }));
    expect(
      screen.getByText(/Running Precision Musical DSP pipeline/i),
    ).toBeInTheDocument();
    expect(processSpy).toHaveBeenCalledWith(
      MOCK_SESSION.session_id,
      expect.objectContaining({
        strength: 0.45,
        hum_reduction_enabled: true,
        hpf_enabled: false,
        dry_wet_mix: 1.0,
        bypass: false,
      }),
    );

    resolveProcess!(MOCK_PROCESS_RESULT);

    await waitFor(() =>
      expect(screen.getByText("Processing Applied")).toBeInTheDocument(),
    );

    // Verify engine loaded sample-aligned original, processed, and residual streams
    expect(mockEngineLoad).toHaveBeenCalledWith(
      MOCK_PROCESS_RESULT.original_aligned_audio_url,
      MOCK_PROCESS_RESULT.processed_audio_url,
      MOCK_PROCESS_RESULT.residual_audio_url,
      2.4,
    );

    // Play comparison audio
    await user.click(screen.getByRole("button", { name: /Play Comparison/i }));
    expect(mockEnginePlay).toHaveBeenCalledTimes(1);

    // Switch Original (A) <-> Cleaned (B)
    await user.click(screen.getByRole("button", { name: /Original \(A\)/i }));
    expect(mockEngineSetMode).toHaveBeenCalledWith("original");

    await user.click(screen.getByRole("button", { name: /Cleaned \(B\)/i }));
    expect(mockEngineSetMode).toHaveBeenCalledWith("processed");

    // Adjust live dry/wet comparison slider
    const liveMixSlider = screen.getByLabelText(/Live A\/B Dry\/Wet Compare/i);
    fireEvent.change(liveMixSlider, { target: { value: "0.5" } });
    expect(mockEngineSetMode).toHaveBeenCalledWith("mix");
    expect(mockEngineSetWetMix).toHaveBeenCalledWith(0.5);

    // Switch to Processing Difference / Residual and verify disclosure banner
    await user.click(
      screen.getByRole("button", { name: /Processing Difference \/ Residual/i }),
    );
    expect(mockEngineSetMode).toHaveBeenCalledWith("residual");
    expect(
      screen.getByText(/original\[n\] - final_processed\[n\]/i),
    ).toBeInTheDocument();
  });

  it("displays structured error alert if processing fails", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiClient, "processSession").mockRejectedValue(
      new apiClient.ApiClientError(
        "Processing parameters failed validation.",
        "REQUEST_VALIDATION_ERROR",
        422,
      ),
    );

    render(<App />);
    await waitFor(() =>
      expect(screen.getByText("Audio Ingestion")).toBeInTheDocument(),
    );

    const input = screen.getByLabelText("Select audio recording");
    fireEvent.change(input, {
      target: { files: [new File([new Uint8Array(512)], "test.wav")] },
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Process Audio$/i })).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /^Process Audio$/i }));

    await waitFor(() =>
      expect(screen.getByText("Audio processing failed")).toBeInTheDocument(),
    );
    expect(screen.getByText("REQUEST_VALIDATION_ERROR")).toBeInTheDocument();
  });
});
