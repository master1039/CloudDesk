"""P3-1 tests for N1 JWT authentication and role enforcement."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
import pytest
from app.core.config import get_settings
from app.core.security import get_current_user, require_role
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import Role
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

TEST_SECRET = "p3-1-offline-secret-with-at-least-32-bytes"
ViewerUser = Annotated[AuthenticatedUser, Depends(require_role(Role.VIEWER))]
AgentUser = Annotated[AuthenticatedUser, Depends(require_role(Role.AGENT))]
AdminUser = Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN))]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


def _token(
    role: str = "viewer",
    *,
    secret: str = TEST_SECRET,
    expires_delta: timedelta = timedelta(minutes=5),
    claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": "00000000-0000-0000-0000-000000000123",
        "email": "user@clouddesk.demo",
        "display_name": "Demo User",
        "role": role,
        "aud": "authenticated",
        "iat": now,
        "exp": now + expires_delta,
    }
    if claims:
        payload.update(claims)
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def protected_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    get_settings.cache_clear()
    app = FastAPI()

    @app.get("/viewer")
    async def viewer_route(user: ViewerUser) -> dict[str, str | None]:
        return {"id": user.id, "email": user.email, "role": user.role.value}

    @app.post("/agent")
    async def agent_route(user: AgentUser) -> dict[str, str]:
        return {"role": user.role.value}

    @app.post("/admin")
    async def admin_route(user: AdminUser) -> dict[str, str]:
        return {"role": user.role.value}

    return TestClient(app)


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_n1_missing_token_returns_bearer_401(protected_client: TestClient) -> None:
    response = protected_client.get("/viewer")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication credentials were not provided"}
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        _token(secret="wrong-secret-with-at-least-32-bytes"),
        _token(expires_delta=timedelta(seconds=-1)),
        jwt.encode({"sub": "missing-exp", "role": "viewer"}, TEST_SECRET, algorithm="HS256"),
        jwt.encode(
            {"sub": "missing-role", "exp": datetime.now(UTC) + timedelta(minutes=5)},
            TEST_SECRET,
            algorithm="HS256",
        ),
    ],
)
def test_n1_bad_or_expired_token_returns_401(protected_client: TestClient, token: str) -> None:
    response = protected_client.get("/viewer", headers=_authorization(token))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_n1_viewer_can_read_but_cannot_mutate(protected_client: TestClient) -> None:
    headers = _authorization(_token("viewer"))

    read_response = protected_client.get("/viewer", headers=headers)
    mutate_response = protected_client.post("/agent", headers=headers)

    assert read_response.status_code == 200
    assert read_response.json()["role"] == "viewer"
    assert mutate_response.status_code == 403
    assert mutate_response.json() == {"detail": "The agent role or higher is required"}


def test_n1_role_hierarchy_accepts_agent_and_admin(protected_client: TestClient) -> None:
    agent_headers = _authorization(_token("agent"))
    admin_headers = _authorization(_token("admin"))

    assert protected_client.post("/agent", headers=agent_headers).status_code == 200
    assert protected_client.post("/admin", headers=agent_headers).status_code == 403
    assert protected_client.get("/viewer", headers=admin_headers).status_code == 200
    assert protected_client.post("/agent", headers=admin_headers).status_code == 200
    assert protected_client.post("/admin", headers=admin_headers).status_code == 200


def test_n1_accepts_supabase_metadata_role_and_authenticated_audience(
    protected_client: TestClient,
) -> None:
    token = _token(
        "authenticated",
        claims={
            "app_metadata": {"role": "agent"},
            "user_metadata": {"full_name": "Supabase Agent"},
        },
    )

    response = protected_client.post("/agent", headers=_authorization(token))

    assert response.status_code == 200
    assert response.json() == {"role": "agent"}


def test_supabase_secret_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "local-secret-with-at-least-32-bytes")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
    get_settings.cache_clear()
    app = FastAPI()

    @app.get("/me")
    async def me(user: CurrentUser) -> dict[str, str]:
        return {"id": user.id}

    response = TestClient(app).get("/me", headers=_authorization(_token()))

    assert response.status_code == 200


def test_missing_jwt_configuration_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    get_settings.cache_clear()
    app = FastAPI()

    @app.get("/me")
    async def me(user: CurrentUser) -> dict[str, str]:
        return {"id": user.id}

    response = TestClient(app).get("/me", headers=_authorization(_token()))

    assert response.status_code == 503
    assert response.json() == {"detail": "JWT authentication is not configured"}
