"""API route for Stage 3 read-only spectral, PSD, and noise analysis."""

from __future__ import annotations

import asyncio
from pathlib import Path

import soundfile as sf
from fastapi import APIRouter, Body, Depends

from app.analysis.analyzer import analyze_audio
from app.api.sessions import get_session_store
from app.core.exceptions import AudioValidationError
from app.models.schemas import AnalysisRequest, AnalysisResponse
from app.services.session_store import SessionStore

router = APIRouter(prefix="/sessions", tags=["analysis"])


def _load_and_analyze(
    decoded_wav_path: Path,
    session_id: str,
    params: AnalysisRequest,
) -> AnalysisResponse:
    """Load native-SR float32 audio and execute spectral & noise analysis."""
    try:
        samples, sample_rate = sf.read(
            str(decoded_wav_path), dtype="float32", always_2d=True
        )
    except (sf.LibsndfileError, RuntimeError, OSError) as exc:
        raise AudioValidationError(
            code="ANALYSIS_LOAD_FAILED",
            message="Failed to read decoded audio working copy for analysis.",
            details={"reason": str(exc)},
        ) from exc

    return analyze_audio(
        samples=samples,
        sample_rate=int(sample_rate),
        session_id=session_id,
        params=params,
    )


@router.post("/{session_id}/analyze", response_model=AnalysisResponse)
async def analyze_session_audio(
    session_id: str,
    params: AnalysisRequest | None = Body(default=None),
    store: SessionStore = Depends(get_session_store),
) -> AnalysisResponse:
    """Run conservative noise estimation, spectral indicators, PSD, and spectrogram analysis."""
    decoded_path = store.get_decoded_audio_file(session_id)
    effective_params = params or AnalysisRequest()
    return await asyncio.to_thread(
        _load_and_analyze, decoded_path, session_id, effective_params
    )
