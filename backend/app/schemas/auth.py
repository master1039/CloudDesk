"""Internal authentication principal shared by security dependencies."""

from __future__ import annotations

from app.schemas.common import Role
from pydantic import BaseModel, ConfigDict


class AuthenticatedUser(BaseModel):
    """Identity and application role established by a verified JWT."""

    model_config = ConfigDict(frozen=True)

    id: str
    email: str | None = None
    display_name: str
    role: Role
