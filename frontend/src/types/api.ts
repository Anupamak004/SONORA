export interface MediaToolStatus {
  available: boolean;
  version: string | null;
  notes: string | null;
}

export type EngineCategory =
  | "precision_dsp"
  | "stem_separation"
  | "music_ai"
  | "experimental_ai";

export interface EngineCapability {
  id: string;
  name: string;
  category: EngineCategory;
  implemented: boolean;
  available: boolean;
  optional_dependency: boolean;
  target_stage: string;
  role: string;
  limitations: string;
}

export interface StorageStatus {
  temp_dir_ready: boolean;
  session_ttl_minutes: number;
}

export interface UploadLimits {
  max_upload_mb: number;
  max_duration_seconds: number;
  max_decoded_pcm_mb: number;
  supported_upload_formats: string[];
}

export interface HealthResponse {
  status: "ok" | "degraded";
  app_name: string;
  version: string;
  stage: string;
  environment: string;
  python_version: string;
  ffmpeg: MediaToolStatus;
  ffprobe: MediaToolStatus;
  storage: StorageStatus;
  limits: UploadLimits;
  engines: EngineCapability[];
}

export interface InstrumentProfile {
  id: string;
  name: string;
  description: string;
  fundamental_min_hz: number;
  fundamental_max_hz: number;
  default_hpf_hz: number;
  min_hpf_hz: number;
  max_hpf_hz: number;
  protect_fundamentals: boolean;
  protect_harmonics: boolean;
  pitch_safe_hum_guard: boolean;
  transient_protection: number;
  default_attenuation_limit_db: number;
  default_strength: number;
  hum_conflict_note: string;
}

export interface ProfilesResponse {
  profiles: InstrumentProfile[];
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

export type SupportedAudioFormat = "wav" | "flac" | "mp3";

export interface AudioMetadata {
  format: SupportedAudioFormat;
  codec: string;
  container: string;
  sample_rate: number;
  channels: number;
  duration_seconds: number;
  frame_count: number;
  bit_depth: number | null;
  bitrate_kbps: number | null;
  file_size_bytes: number;
  sample_peak_dbfs: number | null;
  true_peak_dbtp: number | null;
  rms_dbfs: number | null;
  integrated_lufs: number | null;
  loudness_note: string | null;
}

export interface WaveformPeaks {
  bucket_count: number;
  peaks: number[];
}

export interface SessionSummary {
  session_id: string;
  display_name: string;
  created_at: string;
  expires_at: string;
  format: SupportedAudioFormat;
  duration_seconds: number;
  sample_rate: number;
  channels: number;
}

export interface SessionDetail {
  session_id: string;
  display_name: string;
  created_at: string;
  expires_at: string;
  metadata: AudioMetadata;
  waveform: WaveformPeaks;
  original_audio_url: string;
}

export interface SessionsListResponse {
  sessions: SessionSummary[];
}

export type FrequencyScale = "log" | "linear";
export type ConfidenceLevel = "none" | "low" | "moderate" | "high";
export type SignalState = "normal" | "silence_or_near_silence" | "very_short";

export interface AnalysisRequest {
  freq_scale?: FrequencyScale;
  db_min?: number;
  db_max?: number;
  max_time_bins?: number;
  max_freq_bins?: number;
}

export interface NoiseFloorEstimate {
  method: string;
  broadband_noise_floor_dbfs: number | null;
  active_signal_dbfs: number | null;
  estimated_snr_db: number | null;
  confidence: ConfidenceLevel;
  sustained_tonal_warning: boolean;
  notes: string[];
}

export interface NoiseIndicator {
  id: string;
  label: string;
  detected: boolean;
  confidence: ConfidenceLevel;
  evidence: string;
  caveat: string;
  metrics: Record<string, number | string | boolean | null>;
}

export interface FrequencyBandSummary {
  id: string;
  label: string;
  low_hz: number;
  high_hz: number;
  active_level_db: number | null;
  median_level_db: number | null;
  estimated_noise_floor_db: number | null;
  estimated_band_snr_db: number | null;
  spectral_flatness: number;
}

export interface PsdComparisonData {
  frequencies_hz: number[];
  active_p90_db: number[];
  overall_median_db: number[];
  estimated_noise_floor_db: number[];
}

export interface SpectrogramData {
  freq_scale: FrequencyScale;
  db_min: number;
  db_max: number;
  n_fft: number;
  hop_length: number;
  time_bins: number;
  freq_bins: number;
  times_sec: number[];
  frequencies_hz: number[];
  magnitudes_u8: number[][];
}

export interface AnalysisResponse {
  session_id: string;
  sample_rate: number;
  channels: number;
  duration_seconds: number;
  signal_state: SignalState;
  noise_floor: NoiseFloorEstimate;
  detected_indicators: NoiseIndicator[];
  frequency_bands: FrequencyBandSummary[];
  psd: PsdComparisonData;
  spectrogram: SpectrogramData;
  limitations: string[];
}

export type ProcessingMode =
  | "applied"
  | "minimal"
  | "bypassed"
  | "bypassed_clean_or_silent";

export interface ProcessRequest {
  strength: number;
  hum_reduction_enabled: boolean;
  hpf_enabled: boolean;
  hpf_cutoff_hz: number;
  dry_wet_mix: number;
  bypass: boolean;
  enable_limiter: boolean;
  limiter_ceiling_dbtp: number;
}

export interface LevelSummary {
  sample_peak_dbfs: number | null;
  true_peak_dbtp: number | null;
  rms_dbfs: number | null;
  integrated_lufs: number | null;
  loudness_note: string | null;
}

export interface ProcessingActions {
  dc_offset_removed: boolean;
  hpf_applied: boolean;
  hpf_cutoff_hz: number | null;
  hum_notches_applied: boolean;
  hum_notched_frequencies_hz: number[];
  broadband_applied_channels: number[];
  broadband_skipped_clean_channels: number[];
  limiter_engaged: boolean;
  limiter_gain_reduction_db: number;
  notes: string[];
}

export interface ProcessResponse {
  session_id: string;
  status: "completed";
  processing_mode: ProcessingMode;
  cached: boolean;
  params_hash: string;
  processing_time_ms: number;
  sample_rate: number;
  channels: number;
  frame_count: number;
  duration_seconds: number;
  settings_applied: ProcessRequest;
  actions: ProcessingActions;
  original_levels: LevelSummary;
  processed_levels: LevelSummary;
  residual_levels: LevelSummary;
  loudness_offset_db: number | null;
  processed_waveform: WaveformPeaks;
  residual_waveform: WaveformPeaks;
  original_aligned_audio_url: string;
  processed_audio_url: string;
  residual_audio_url: string;
  residual_disclosure: string;
}
