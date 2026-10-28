"""CloudDesk FastAPI application factory and ASGI entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.database import create_tables, dispose_database, get_session_factory
from app.core.logging import setup_logging
from app.core.redis import close_redis
from app.middleware import (
    RATE_LIMIT_HEADER,
    RATE_LIMIT_REMAINING_HEADER,
    RATE_LIMIT_RESET_HEADER,
    REQUEST_ID_HEADER,
    RETRY_AFTER_HEADER,
    RateLimitMiddleware,
    RequestIdMiddleware,
)
from app.services.seed_service import bootstrap_demo_data
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

APP_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize and optionally seed the offline database, then release it."""

    settings = get_settings()
    await create_tables()
    if settings.demo_mode:
        async with get_session_factory().begin() as session:
            await bootstrap_demo_data(session, settings.sample_data_dir)
    try:
        yield
    finally:
        try:
            await close_redis()
        finally:
            await dispose_database()


def create_app() -> FastAPI:
    """Build the API; database I/O is deferred to the lifespan context."""

    settings = get_settings()
    application = FastAPI(
        title="CloudDesk Support API",
        version=APP_VERSION,
        lifespan=lifespan,
    )
    application.include_router(auth_router)
    application.include_router(health_router)

    application.add_middleware(
        RateLimitMiddleware,
        limit=settings.rate_limit_per_minute,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            REQUEST_ID_HEADER,
            RATE_LIMIT_HEADER,
            RATE_LIMIT_REMAINING_HEADER,
            RATE_LIMIT_RESET_HEADER,
            RETRY_AFTER_HEADER,
        ],
    )
    application.add_middleware(RequestIdMiddleware)
    return application


setup_logging()
app = create_app()
