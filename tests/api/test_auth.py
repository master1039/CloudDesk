"""P3-2 tests for demo login, token issuance, and current profile."""

from __future__ import annotations

from datetime import UTC, datetime

import jwt
import pytest
from app.core.config import Settings, get_settings
from app.main import create_app
from app.schemas.common import Role
from app.services.auth_service import DEMO_PASSWORD, DEMO_TOKEN_TTL_SECONDS
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr


@pytest.mark.parametrize(
    ("email", "expected_role"),
    [
        ("admin@clouddesk.demo", "admin"),
        ("sam.agent@clouddesk.demo", "agent"),
        ("vic.viewer@clouddesk.demo", "viewer"),
    ],
)
def test_n1_demo_login_issues_eight_hour_token_and_me_profile(
    client: TestClient,
    email: str,
    expected_role: str,
) -> None:
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": email.upper(), "password": DEMO_PASSWORD},
    )

    assert login_response.status_code == 200
    payload = login_response.json()
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == DEMO_TOKEN_TTL_SECONDS
    assert payload["user"]["email"] == email
    assert payload["user"]["role"] == expected_role

    settings = get_settings()
    claims = jwt.decode(
        payload["access_token"],
        settings.effective_jwt_secret,
        algorithms=["HS256"],
        options={"verify_aud": False},
    )
    assert claims["aud"] == "authenticated"
    assert claims["role"] == "authenticated"
    assert claims["app_metadata"]["role"] == expected_role
    assert 28_795 <= claims["exp"] - claims["iat"] <= 28_800
    assert datetime.fromtimestamp(claims["exp"], UTC) > datetime.now(UTC)

    me_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert me_response.status_code == 200
    assert me_response.json() == payload["user"]


@pytest.mark.parametrize(
    "credentials",
    [
        {"email": "unknown@clouddesk.demo", "password": DEMO_PASSWORD},
        {"email": "sam.agent@clouddesk.demo", "password": "wrong-password"},
    ],
)
def test_demo_login_rejects_unknown_user_and_wrong_password_identically(
    client: TestClient, credentials: dict[str, str]
) -> None:
    response = client.post("/api/v1/auth/login", json=credentials)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_auth_me_requires_a_bearer_token(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_demo_login_is_disabled_outside_demo_mode() -> None:
    settings = Settings(
        demo_mode=False,
        environment="test",
        jwt_secret=SecretStr("disabled-demo-secret-with-at-least-32-bytes"),
    )
    app: FastAPI = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    response = TestClient(app).post(
        "/api/v1/auth/login",
        json={"email": "admin@clouddesk.demo", "password": DEMO_PASSWORD},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Demo authentication is disabled"}


def test_auth_response_role_is_one_of_the_locked_values(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "vic.viewer@clouddesk.demo", "password": DEMO_PASSWORD},
    )

    assert Role(response.json()["user"]["role"]) is Role.VIEWER
