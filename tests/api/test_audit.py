"""P3-4 tests for N6 audit persistence and final middleware order."""

from __future__ import annotations

from typing import Annotated, Any

from app.core.database import get_session
from app.core.security import require_role
from app.main import create_app
from app.middleware import AuditMiddleware, RateLimitMiddleware, RequestIdMiddleware
from app.middleware.request_id import REQUEST_ID_HEADER
from app.models import AuditLog
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import Role
from app.services.auth_service import DEMO_PASSWORD
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

AgentUser = Annotated[AuthenticatedUser, Depends(require_role(Role.AGENT))]
DatabaseSession = Annotated[AsyncSession, Depends(get_session)]


def _app_with_test_routes() -> FastAPI:
    app = create_app()

    @app.post("/_test/change")
    async def change(_: AgentUser) -> dict[str, str]:
        return {"status": "changed"}

    @app.get("/_test/audit")
    async def audit_rows(session: DatabaseSession) -> list[dict[str, Any]]:
        rows = (
            await session.scalars(select(AuditLog).order_by(AuditLog.created_at, AuditLog.id))
        ).all()
        return [
            {
                "actor_id": row.actor_id,
                "actor_role": row.actor_role.value if row.actor_role else None,
                "method": row.method,
                "path": row.path,
                "status_code": row.status_code,
                "request_id": row.request_id,
                "change_summary": row.change_summary,
            }
            for row in rows
        ]

    return app


def _login(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_n6_non_get_request_writes_scrubbed_authenticated_audit_row() -> None:
    with TestClient(_app_with_test_routes()) as client:
        token = _login(client, "sam.agent@clouddesk.demo")
        response = client.post(
            "/_test/change?api_key=must-not-be-audited",
            json={"password": "must-not-be-audited"},
            headers={
                "Authorization": f"Bearer {token}",
                REQUEST_ID_HEADER: "audit-request-123",
            },
        )
        rows = client.get("/_test/audit").json()

    assert response.status_code == 200
    row = next(item for item in rows if item["path"] == "/_test/change")
    assert row["actor_role"] == "agent"
    assert row["method"] == "POST"
    assert row["status_code"] == 200
    assert row["request_id"] == "audit-request-123"
    assert row["change_summary"] == {"outcome": "success", "authenticated": True}
    assert "must-not-be-audited" not in str(row)
    assert "api_key" not in str(row)


def test_n6_rejected_viewer_mutation_is_audited_but_get_is_not() -> None:
    with TestClient(_app_with_test_routes()) as client:
        before = client.get("/_test/audit").json()
        token = _login(client, "vic.viewer@clouddesk.demo")
        response = client.post(
            "/_test/change",
            headers={"Authorization": f"Bearer {token}"},
        )
        after = client.get("/_test/audit").json()

    assert response.status_code == 403
    assert len(after) == len(before) + 2  # login plus rejected mutation
    rejected = after[-1]
    assert rejected["actor_role"] == "viewer"
    assert rejected["status_code"] == 403
    assert rejected["change_summary"] == {
        "outcome": "client_error",
        "authenticated": True,
    }


def test_phase_three_middleware_registration_order_is_locked() -> None:
    app = create_app()
    registration_order = [item.cls for item in reversed(app.user_middleware)]

    assert registration_order == [
        CORSMiddleware,
        RequestIdMiddleware,
        RateLimitMiddleware,
        AuditMiddleware,
    ]


def test_audit_failure_never_replaces_successful_response() -> None:
    async def failing_writer(_: object) -> None:
        raise RuntimeError("audit unavailable")

    app = FastAPI()

    @app.post("/change")
    async def change() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(AuditMiddleware, writer=failing_writer)
    response = TestClient(app).post("/change")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
