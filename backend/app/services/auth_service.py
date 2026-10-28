"""Demo authentication orchestration and HS256 token issuance."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import jwt
from app.core.config import Settings
from app.core.security import JWT_ALGORITHM
from app.models import Profile
from app.repositories import ProfileRepository
from app.schemas.auth import AuthenticatedUser
from sqlalchemy.ext.asyncio import AsyncSession

DEMO_PASSWORD = "clouddesk-demo"
DEMO_TOKEN_TTL = timedelta(hours=8)
DEMO_TOKEN_TTL_SECONDS = int(DEMO_TOKEN_TTL.total_seconds())


class InvalidDemoCredentialsError(ValueError):
    """Raised for every invalid demo login to avoid account enumeration."""


class DemoAuthenticationDisabledError(RuntimeError):
    """Raised when the local credential route is used outside demo mode."""


class AuthenticationConfigurationError(RuntimeError):
    """Raised when token signing has no configured secret."""


async def authenticate_demo_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    settings: Settings,
) -> Profile:
    """Authenticate one active seeded profile with the public demo credential."""

    if not settings.demo_mode:
        raise DemoAuthenticationDisabledError

    profile = await ProfileRepository(session).get_by_email(email.strip())
    password_matches = secrets.compare_digest(password, DEMO_PASSWORD)
    if profile is None or not profile.is_active or not password_matches:
        raise InvalidDemoCredentialsError
    return profile


def issue_demo_access_token(
    profile: Profile,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> str:
    """Issue an eight-hour token shaped like a Supabase authenticated JWT."""

    secret = settings.effective_jwt_secret
    if not secret:
        raise AuthenticationConfigurationError
    issued_at = now or datetime.now(UTC)
    role = profile.role.value
    payload = {
        "sub": profile.id,
        "email": profile.email,
        "display_name": profile.display_name,
        "role": "authenticated",
        "app_role": role,
        "app_metadata": {"role": role},
        "user_metadata": {"display_name": profile.display_name},
        "aud": "authenticated",
        "iat": issued_at,
        "exp": issued_at + DEMO_TOKEN_TTL,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


async def get_active_profile(session: AsyncSession, user: AuthenticatedUser) -> Profile | None:
    """Resolve a verified token subject to its current active database profile."""

    profile = await ProfileRepository(session).get(user.id)
    if profile is None or not profile.is_active or profile.role is not user.role:
        return None
    return profile
