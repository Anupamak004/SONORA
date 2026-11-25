"""Pydantic API DTOs for SONORA."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class MediaToolStatus(BaseModel):
    """Availability and version status of an external media binary."""

    available: bool
    version: str | None = None
    notes: str | None = None


class EngineCapability(BaseModel):
    """Honest runtime capability record for a denoising/separation engine."""

    id: str
    name: str
    category: Literal["precision_dsp", "stem_separation", "music_ai", "experimental_ai"]
    implemented: bool
    available: bool
    optional_dependency: bool
    target_stage: str
    role: str
    limitations: str


class StorageStatus(BaseModel):
    """Scoped temporary workspace status."""

    temp_dir_ready: bool
    session_ttl_minutes: int


class UploadLimits(BaseModel):
    """Active server-enforced upload and safety limits."""

    max_upload_mb: int
    max_duration_seconds: int
    max_decoded_pcm_mb: int
    supported_upload_formats: list[str]


class HealthResponse(BaseModel):
    """Response schema for GET /api/v1/health."""

    status: Literal["ok", "degraded"]
    app_name: str
    version: str
    stage: str
    environment: str
    python_version: str
    ffmpeg: MediaToolStatus
    ffprobe: MediaToolStatus
    storage: StorageStatus
    limits: UploadLimits
    engines: list[EngineCapability]


class InstrumentProfile(BaseModel):
    """Configurable instrument-aware filtering and preservation defaults."""

    id: str
    name: str
    description: str
    fundamental_min_hz: float = Field(gt=0)
    fundamental_max_hz: float = Field(gt=0)
    default_hpf_hz: float = Field(ge=15.0, le=300.0)
    min_hpf_hz: float = Field(ge=15.0, le=300.0)
    max_hpf_hz: float = Field(ge=20.0, le=500.0)
    protect_fundamentals: bool = True
    protect_harmonics: bool = True
    pitch_safe_hum_guard: bool = True
    transient_protection: float = Field(ge=0.0, le=1.0)
    default_attenuation_limit_db: float = Field(ge=3.0, le=24.0)
    default_strength: float = Field(ge=0.0, le=1.0)
    hum_conflict_note: str


class ProfilesResponse(BaseModel):
    """Response schema for GET /api/v1/profiles."""

    profiles: list[InstrumentProfile]


SupportedAudioFormat = Literal["wav", "flac", "mp3"]


class AudioMetadata(BaseModel):
    """Verified audio stream properties and objective loudness/level measurements."""

    format: SupportedAudioFormat
    codec: str
    container: str
    sample_rate: int = Field(gt=0)
    channels: int = Field(ge=1, le=2)
    duration_seconds: float = Field(gt=0)
    frame_count: int = Field(gt=0)
    bit_depth: int | None = None
    bitrate_kbps: int | None = None
    file_size_bytes: int = Field(gt=0)
    sample_peak_dbfs: float | None = None
    true_peak_dbtp: float | None = None
    rms_dbfs: float | None = None
    integrated_lufs: float | None = None
    loudness_note: str | None = None


class WaveformPeaks(BaseModel):
    """Downsampled peak amplitude envelope for immediate WaveSurfer.js rendering."""

    bucket_count: int = Field(ge=1)
    peaks: list[float]


class SessionSummary(BaseModel):
    """Compact summary item for recent active sessions."""

    session_id: str
    display_name: str
    created_at: str
    expires_at: str
    format: SupportedAudioFormat
    duration_seconds: float
    sample_rate: int
    channels: int


class SessionDetail(BaseModel):
    """Full metadata and playback descriptors for an ingested audio session."""

    session_id: str
    display_name: str
    created_at: str
    expires_at: str
    metadata: AudioMetadata
    waveform: WaveformPeaks
    original_audio_url: str


class SessionsListResponse(BaseModel):
    """Response schema for GET /api/v1/sessions."""

    sessions: list[SessionSummary]


FrequencyScale = Literal["log", "linear"]
ConfidenceLevel = Literal["none", "low", "moderate", "high"]
SignalState = Literal["normal", "silence_or_near_silence", "very_short"]


class AnalysisRequest(BaseModel):
    """Configurable parameters for Stage 3 spectral & noise analysis."""

    freq_scale: FrequencyScale = Field(default="log")
    db_min: float = Field(default=-100.0, ge=-120.0, le=-40.0)
    db_max: float = Field(default=0.0, ge=-20.0, le=0.0)
    max_time_bins: int = Field(default=220, ge=32, le=400)
    max_freq_bins: int = Field(default=96, ge=24, le=160)

    @model_validator(mode="after")
    def validate_db_span(self) -> AnalysisRequest:
        if self.db_max - self.db_min < 20.0:
            raise ValueError("db_max must be at least 20 dB above db_min.")
        return self


class NoiseFloorEstimate(BaseModel):
    """Conservative silence-free noise floor estimate (explicitly separated from detection)."""

    method: str
    broadband_noise_floor_dbfs: float | None = None
    active_signal_dbfs: float | None = None
    estimated_snr_db: float | None = None
    confidence: ConfidenceLevel
    sustained_tonal_warning: bool
    notes: list[str]


class NoiseIndicator(BaseModel):
    """Possible spectral noise indicator with calibrated confidence, evidence, and caveats."""

    id: str
    label: str
    detected: bool
    confidence: ConfidenceLevel
    evidence: str
    caveat: str
    metrics: dict[str, float | int | str | bool | None] = Field(default_factory=dict)


class FrequencyBandSummary(BaseModel):
    """Per-band energy, estimated floor, and spectral flatness summary."""

    id: str
    label: str
    low_hz: float
    high_hz: float
    active_level_db: float | None = None
    median_level_db: float | None = None
    estimated_noise_floor_db: float | None = None
    estimated_band_snr_db: float | None = None
    spectral_flatness: float = Field(ge=0.0, le=1.0)


class PsdComparisonData(BaseModel):
    """Compact log-spaced PSD curves for active signal, median, and estimated noise floor."""

    frequencies_hz: list[float]
    active_p90_db: list[float]
    overall_median_db: list[float]
    estimated_noise_floor_db: list[float]


class SpectrogramData(BaseModel):
    """Bounded, quantized STFT spectrogram representation for canvas rendering."""

    freq_scale: FrequencyScale
    db_min: float
    db_max: float
    n_fft: int
    hop_length: int
    time_bins: int
    freq_bins: int
    times_sec: list[float]
    frequencies_hz: list[float]
    # Row-major [freq_idx][time_idx], values in 0..255 mapped linearly over [db_min, db_max]
    magnitudes_u8: list[list[int]]


class AnalysisResponse(BaseModel):
    """Response schema for POST /api/v1/sessions/{session_id}/analyze."""

    session_id: str
    sample_rate: int
    channels: int
    duration_seconds: float
    signal_state: SignalState
    noise_floor: NoiseFloorEstimate
    detected_indicators: list[NoiseIndicator]
    frequency_bands: list[FrequencyBandSummary]
    psd: PsdComparisonData
    spectrogram: SpectrogramData
    limitations: list[str]


ProcessingMode = Literal[
    "applied",
    "minimal",
    "bypassed",
    "bypassed_clean_or_silent",
]


ProcessingEngine = Literal["precision_musical_dsp", "audiosep_experimental"]


class ProcessRequest(BaseModel):
    """Validated controls for the selected processing engine."""

    engine: ProcessingEngine = "precision_musical_dsp"
    target_query: str | None = Field(default=None, min_length=1, max_length=120)
    strength: float = Field(default=0.45, ge=0.0, le=0.85)
    hum_reduction_enabled: bool = Field(default=True)
    hpf_enabled: bool = Field(default=False)
    hpf_cutoff_hz: float = Field(default=40.0, ge=20.0, le=150.0)
    dry_wet_mix: float = Field(default=1.0, ge=0.0, le=1.0)
    bypass: bool = Field(default=False)
    enable_limiter: bool = Field(default=False)
    limiter_ceiling_dbtp: float = Field(default=-1.0, ge=-3.0, le=-0.1)


class LevelSummary(BaseModel):
    """Objective amplitude and ITU-R BS.1770 loudness summary."""

    sample_peak_dbfs: float | None = None
    true_peak_dbtp: float | None = None
    rms_dbfs: float | None = None
    integrated_lufs: float | None = None
    loudness_note: str | None = None


class ProcessingActions(BaseModel):
    """Transparent record of which DSP stages actually engaged."""

    dc_offset_removed: bool
    hpf_applied: bool
    hpf_cutoff_hz: float | None = None
    hum_notches_applied: bool
    hum_notched_frequencies_hz: list[float] = Field(default_factory=list)
    broadband_applied_channels: list[int] = Field(default_factory=list)
    broadband_skipped_clean_channels: list[int] = Field(default_factory=list)
    limiter_engaged: bool
    limiter_gain_reduction_db: float = 0.0
    notes: list[str] = Field(default_factory=list)


class ProcessResponse(BaseModel):
    """Response schema for POST / GET /api/v1/sessions/{session_id}/process."""

    session_id: str
    status: Literal["completed"] = "completed"
    processing_mode: ProcessingMode
    cached: bool = False
    params_hash: str
    processing_time_ms: float
    sample_rate: int
    channels: int
    frame_count: int
    duration_seconds: float
    settings_applied: ProcessRequest
    actions: ProcessingActions
    original_levels: LevelSummary
    processed_levels: LevelSummary
    residual_levels: LevelSummary
    loudness_offset_db: float | None = None
    processed_waveform: WaveformPeaks
    residual_waveform: WaveformPeaks
    original_aligned_audio_url: str
    processed_audio_url: str
    residual_audio_url: str
    residual_disclosure: str
