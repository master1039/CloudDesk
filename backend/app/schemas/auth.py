"""Internal authentication principal shared by security dependencies."""

from __future__ import annotations

from typing import Literal

from app.schemas.common import Role
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class AuthenticatedUser(BaseModel):
    """Identity and application role established by a verified JWT."""

    model_config = ConfigDict(frozen=True)

    id: str
    email: str | None = None
    display_name: str
    role: Role


class LoginRequest(BaseModel):
    """Credentials accepted by the explicitly demo-only login route."""

    email: str = Field(min_length=3, max_length=320)
    password: SecretStr


class ProfileResponse(BaseModel):
    """Public support-agent profile returned by authentication routes."""

    id: str
    email: str
    display_name: str
    role: Role


class AuthResponse(BaseModel):
    """Bearer token and profile returned after a successful demo login."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: ProfileResponse
