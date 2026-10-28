"""Demo login and authenticated profile routes."""

from __future__ import annotations

from typing import Annotated

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.core.security import require_role
from app.schemas.auth import AuthenticatedUser, AuthResponse, LoginRequest, ProfileResponse
from app.schemas.common import Role
from app.services.auth_service import (
    DEMO_TOKEN_TTL_SECONDS,
    AuthenticationConfigurationError,
    DemoAuthenticationDisabledError,
    InvalidDemoCredentialsError,
    authenticate_demo_user,
    get_active_profile,
    issue_demo_access_token,
)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
ViewerUser = Annotated[AuthenticatedUser, Depends(require_role(Role.VIEWER))]
DatabaseSession = Annotated[AsyncSession, Depends(get_session)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


def _profile_response(profile: object) -> ProfileResponse:
    return ProfileResponse.model_validate(profile, from_attributes=True)


@router.post("/login", response_model=AuthResponse)
async def login(
    request: LoginRequest,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> AuthResponse:
    """Authenticate a seeded demo user and issue an eight-hour bearer token."""

    try:
        profile = await authenticate_demo_user(
            session,
            email=request.email,
            password=request.password.get_secret_value(),
            settings=settings,
        )
        token = issue_demo_access_token(profile, settings)
    except DemoAuthenticationDisabledError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo authentication is disabled",
        ) from error
    except InvalidDemoCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    except AuthenticationConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT authentication is not configured",
        ) from error

    return AuthResponse(
        access_token=token,
        expires_in=DEMO_TOKEN_TTL_SECONDS,
        user=_profile_response(profile),
    )


@router.get("/me", response_model=ProfileResponse)
async def me(user: ViewerUser, session: DatabaseSession) -> ProfileResponse:
    """Return the current active profile represented by the bearer token."""

    profile = await get_active_profile(session, user)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated profile is unavailable",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _profile_response(profile)
