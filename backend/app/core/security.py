"""Supabase-compatible HS256 authentication and role enforcement."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

import jwt
from app.core.config import Settings, get_settings
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import Role
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

JWT_ALGORITHM = "HS256"
ROLE_LEVEL = {Role.VIEWER: 1, Role.AGENT: 2, Role.ADMIN: 3}

bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "Invalid or expired authentication token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _claim_mapping(payload: dict[str, Any], name: str) -> dict[str, Any]:
    value = payload.get(name)
    return value if isinstance(value, dict) else {}


def _role_from_claims(payload: dict[str, Any]) -> Role:
    """Read CloudDesk or Supabase metadata roles without trusting DB roles."""

    candidates = (
        payload.get("app_role"),
        _claim_mapping(payload, "app_metadata").get("role"),
        _claim_mapping(payload, "user_metadata").get("role"),
        payload.get("role"),
    )
    for candidate in candidates:
        try:
            return Role(candidate)
        except (TypeError, ValueError):
            continue
    raise _unauthorized("Authentication token has no valid CloudDesk role")


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def decode_access_token(token: str, settings: Settings | None = None) -> AuthenticatedUser:
    """Verify one HS256 bearer token and return its typed identity claims."""

    active_settings = settings or get_settings()
    secret = active_settings.effective_jwt_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT authentication is not configured",
        )

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp"], "verify_aud": False},
        )
        subject = _optional_text(payload.get("sub"))
        if subject is None:
            raise _unauthorized("Authentication token has no valid subject")
        role = _role_from_claims(payload)
    except HTTPException:
        raise
    except (InvalidTokenError, TypeError, ValueError) as error:
        raise _unauthorized() from error

    user_metadata = _claim_mapping(payload, "user_metadata")
    email = _optional_text(payload.get("email")) or _optional_text(user_metadata.get("email"))
    display_name = (
        _optional_text(payload.get("display_name"))
        or _optional_text(user_metadata.get("display_name"))
        or _optional_text(user_metadata.get("full_name"))
        or email
        or subject
    )
    return AuthenticatedUser(id=subject, email=email, display_name=display_name, role=role)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedUser:
    """FastAPI dependency that authenticates an Authorization bearer token."""

    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise _unauthorized("Authentication credentials were not provided")
    return decode_access_token(credentials.credentials, settings)


def require_role(
    minimum_role: Role,
) -> Callable[[AuthenticatedUser], AuthenticatedUser]:
    """Return a dependency enforcing the CloudDesk role hierarchy."""

    async def role_dependency(
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        if ROLE_LEVEL[user.role] < ROLE_LEVEL[minimum_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"The {minimum_role.value} role or higher is required",
            )
        return user

    return role_dependency
