"""Public process health endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    """Minimal response safe for frequent container probes."""

    status: Literal["ok"] = "ok"


class HealthResponse(LivenessResponse):
    """Application identity and aggregate process health."""

    version: str


class ReadinessResponse(HealthResponse):
    """Dependency readiness results as they become available."""

    dependencies: dict[str, str] = Field(default_factory=dict)


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return aggregate process health without authentication."""

    return HealthResponse(version=request.app.version)


@router.get("/health/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    """Confirm the process event loop is alive without dependency I/O."""

    return LivenessResponse()


@router.get("/health/ready", response_model=ReadinessResponse)
async def ready(request: Request) -> ReadinessResponse:
    """Report readiness; later phases add database, cache, vector, and LLM checks."""

    return ReadinessResponse(version=request.app.version)
