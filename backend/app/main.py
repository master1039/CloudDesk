"""CloudDesk FastAPI application factory and ASGI entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.middleware import REQUEST_ID_HEADER, RequestIdMiddleware


APP_VERSION = "0.1.0"


def create_app() -> FastAPI:
    """Build the API without performing database or network I/O."""

    settings = get_settings()
    application = FastAPI(
        title="CloudDesk Support API",
        version=APP_VERSION,
    )
    application.include_router(health_router)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    application.add_middleware(RequestIdMiddleware)
    return application


setup_logging()
app = create_app()
