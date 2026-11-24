import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as apiClient from "../api/client";
import { NoiseAnalysisPanel } from "../components/analysis/NoiseAnalysisPanel";
import type { AnalysisResponse, SessionDetail } from "../types/api";

const MOCK_SESSION: SessionDetail = {
  session_id: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
  display_name: "cello_sustained_take.wav",
  created_at: "2026-11-23T18:00:00Z",
  expires_at: "2026-11-23T19:00:00Z",
  metadata: {
    format: "wav",
    codec: "pcm_s24le",
    container: "wav",
    sample_rate: 48000,
    channels: 2,
    duration_seconds: 4.0,
    frame_count: 192000,
    bit_depth: 24,
    bitrate_kbps: null,
    file_size_bytes: 1152044,
    sample_peak_dbfs: -9.5,
    true_peak_dbtp: -9.4,
    rms_dbfs: -20.1,
    integrated_lufs: -19.5,
    loudness_note: null,
  },
  waveform: { bucket_count: 4, peaks: [0.2, 0.3, 0.25, 0.15] },
  original_audio_url:
    "/api/v1/sessions/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee/audio/original",
};

const MOCK_ANALYSIS: AnalysisResponse = {
  session_id: MOCK_SESSION.session_id,
  sample_rate: 48000,
  channels: 2,
  duration_seconds: 4.0,
  signal_state: "normal",
  noise_floor: {
    method: "minimum_statistics_spectral_floor",
    broadband_noise_floor_dbfs: -54.2,
    active_signal_dbfs: -18.4,
    estimated_snr_db: 35.8,
    confidence: "moderate",
    sustained_tonal_warning: true,
    notes: [
      "Noise floor is estimated automatically without requiring a silent gap.",
    ],
  },
  detected_indicators: [
    {
      id: "electrical_hum",
      label: "Possible 60 Hz electrical hum",
      detected: true,
      confidence: "high",
      evidence:
        "Steady narrowband peaks observed near 60 Hz, 120 Hz, 180 Hz (avg +18.2 dB).",
      caveat:
        "Sustained low-register notes (e.g., B1 = 61.7 Hz) can sit near 60 Hz harmonics.",
      metrics: { base_freq_hz: 60.0, matched_harmonics: 3 },
    },
    {
      id: "broadband_hiss",
      label: "Possible broadband hiss",
      detected: false,
      confidence: "none",
      evidence: "High-frequency estimated floor is -74.0 dBFS.",
      caveat: "Subtle hiss may remain audible.",
      metrics: {},
    },
  ],
  frequency_bands: [
    {
      id: "sub_bass",
      label: "Sub-Bass / Rumble",
      low_hz: 20,
      high_hz: 80,
      active_level_db: -28.0,
      median_level_db: -35.0,
      estimated_noise_floor_db: -52.0,
      estimated_band_snr_db: 24.0,
      spectral_flatness: 0.14,
    },
    {
      id: "brilliance",
      label: "Brilliance / Air / Hiss",
      low_hz: 6000,
      high_hz: 20000,
      active_level_db: -48.0,
      median_level_db: -60.0,
      estimated_noise_floor_db: -74.0,
      estimated_band_snr_db: 26.0,
      spectral_flatness: 0.55,
    },
  ],
  psd: {
    frequencies_hz: [20, 60, 200, 1000, 5000, 16000],
    active_p90_db: [-40, -25, -18, -22, -45, -65],
    overall_median_db: [-48, -30, -24, -28, -52, -72],
    estimated_noise_floor_db: [-62, -58, -60, -64, -70, -76],
  },
  spectrogram: {
    freq_scale: "log",
    db_min: -100,
    db_max: 0,
    n_fft: 2048,
    hop_length: 512,
    time_bins: 4,
    freq_bins: 3,
    times_sec: [0.0, 1.33, 2.66, 4.0],
    frequencies_hz: [20, 600, 24000],
    magnitudes_u8: [
      [10, 20, 30, 40],
      [80, 120, 140, 100],
      [5, 10, 15, 20],
    ],
  },
  limitations: [
    "Spectral indicators identify possible noise patterns and cannot guarantee definitive noise classification.",
    "Stage 3 performs read-only diagnostic analysis only.",
  ],
};

describe("Stage 3 NoiseAnalysisPanel", () => {
  const putImageDataSpy = vi.fn();
  const createImageDataSpy = vi.fn((w: number, h: number) => ({
    width: w,
    height: h,
    data: new Uint8ClampedArray(w * h * 4),
  }));

  const originalGetContext = HTMLCanvasElement.prototype.getContext;

  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
      configurable: true,
      writable: true,
      value: vi.fn(() => ({
        createImageData: createImageDataSpy,
        putImageData: putImageDataSpy,
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

  it("shows loading state, renders estimated floor, possible indicators with caveats, spectrogram, and PSD tab", async () => {
    const user = userEvent.setup();
    let resolveAnalysis: ((val: AnalysisResponse) => void) | null = null;
    const analyzeSpy = vi
      .spyOn(apiClient, "analyzeSession")
      .mockImplementation(
        () =>
          new Promise<AnalysisResponse>((resolve) => {
            resolveAnalysis = resolve;
          }),
      );

    render(<NoiseAnalysisPanel session={MOCK_SESSION} />);

    // Loading state displayed before response resolves
    expect(
      screen.getByText(/Running STFT spectral analysis/i),
    ).toBeInTheDocument();

    resolveAnalysis!(MOCK_ANALYSIS);

    await waitFor(() =>
      expect(
        screen.getByText("Possible 60 Hz electrical hum"),
      ).toBeInTheDocument(),
    );

    // Distinct Estimated Noise Floor vs Possible Noise Indicators
    expect(screen.getByText("Estimated Noise Floor")).toBeInTheDocument();
    expect(screen.getByText("-54.2 dBFS")).toBeInTheDocument();
    expect(screen.getByText("35.8 dB")).toBeInTheDocument();
    expect(screen.getByText(/Est. Confidence: moderate/i)).toBeInTheDocument();
    expect(screen.getByText(/Sustained tonal energy detected/i)).toBeInTheDocument();
    expect(screen.getByText(/Confidence: high/i)).toBeInTheDocument();
    expect(screen.getByText(/Caveat:.*B1 = 61\.7 Hz/i)).toBeInTheDocument();

    // Spectrogram rendered onto Canvas with exact bounded dimensions
    expect(createImageDataSpy).toHaveBeenCalledWith(4, 3);
    expect(putImageDataSpy).toHaveBeenCalledTimes(1);

    // Interactive spectrogram hover readout
    const canvas = screen.getByLabelText("Interactive audio spectrogram");
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      width: 200,
      height: 100,
      right: 200,
      bottom: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    fireEvent.mouseMove(canvas, { clientX: 100, clientY: 50 });
    expect(screen.getAllByText(/600 Hz/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/2\.66s/i)).toBeInTheDocument();

    // Switching spectrogram scale triggers new analysis call with linear param
    analyzeSpy.mockResolvedValue({
      ...MOCK_ANALYSIS,
      spectrogram: { ...MOCK_ANALYSIS.spectrogram, freq_scale: "linear" },
    });
    await user.click(screen.getByRole("button", { name: /^linear$/i }));
    await waitFor(() =>
      expect(analyzeSpy).toHaveBeenCalledWith(
        MOCK_SESSION.session_id,
        expect.objectContaining({ freq_scale: "linear", db_min: -100 }),
        expect.anything(),
      ),
    );

    // Switch to PSD & Frequency Bands view
    await user.click(
      screen.getByRole("tab", { name: /PSD & Frequency Bands/i }),
    );
    expect(
      screen.getByRole("img", {
        name: /Power spectral density comparison chart/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Sub-Bass / Rumble")).toBeInTheDocument();
    expect(screen.getByText("Brilliance / Air / Hiss")).toBeInTheDocument();
  });

  it("displays an actionable error alert when analysis fails", async () => {
    vi.spyOn(apiClient, "analyzeSession").mockRejectedValue(
      new apiClient.ApiClientError(
        "Decoded float32 audio working copy is no longer available.",
        "RESOURCE_NOT_FOUND",
        404,
      ),
    );

    render(<NoiseAnalysisPanel session={MOCK_SESSION} />);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toBeInTheDocument(),
    );
    expect(screen.getByText("Spectral analysis failed")).toBeInTheDocument();
    expect(screen.getByText("RESOURCE_NOT_FOUND")).toBeInTheDocument();
  });
});
