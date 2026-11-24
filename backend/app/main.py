"""FastAPI application factory for SONORA backend."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_v1_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.services.session_store import SessionStore

logger = logging.getLogger("sonora.app")


async def _periodic_session_cleanup(store: SessionStore, interval_seconds: int = 300) -> None:
    """Periodically sweep expired temporary audio sessions."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await asyncio.to_thread(store.cleanup_expired_sessions)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Periodic session cleanup encountered an error: %s", exc)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application instance."""
    cfg = settings or get_settings()
    configure_logging(cfg.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        temp_dir = cfg.resolved_temp_dir
        temp_dir.mkdir(parents=True, exist_ok=True)
        store = SessionStore(temp_root=temp_dir, ttl_minutes=cfg.session_ttl_minutes)
        store.cleanup_expired_sessions()
        cleanup_task = asyncio.create_task(_periodic_session_cleanup(store))
        logger.info(
            "Starting %s %s (env=%s, temp_dir=%s)",
            cfg.app_name,
            cfg.app_version,
            cfg.env,
            temp_dir,
        )
        try:
            yield
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("Shutting down %s", cfg.app_name)

    app = FastAPI(
        title=f"{cfg.app_name} API",
        version=cfg.app_version,
        description="Local-first musical instrument noise reduction and audio analysis API.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.allowed_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )

    register_exception_handlers(app)
    app.include_router(api_v1_router)

    # Allow dependency override when custom settings are passed in tests
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: cfg

    return app


app = create_app()
