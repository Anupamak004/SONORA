"""Top-level /api/v1 router aggregator."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.analysis import router as analysis_router
from app.api.health import router as health_router
from app.api.processing import router as processing_router
from app.api.profiles import router as profiles_router
from app.api.sessions import router as sessions_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health_router)
api_v1_router.include_router(profiles_router)
api_v1_router.include_router(sessions_router)
api_v1_router.include_router(analysis_router)
api_v1_router.include_router(processing_router)
