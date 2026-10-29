"""P4-3 offline API tests for the protected customer context surface (F4)."""

from __future__ import annotations

from app.services.auth_service import DEMO_PASSWORD
from fastapi.testclient import TestClient


def _login(client: TestClient, email: str = "vic.viewer@clouddesk.demo") -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_customer_routes_require_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/customers")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_viewer_can_list_search_filter_and_page_customers(client: TestClient) -> None:
    token = _login(client)

    page = client.get("/api/v1/customers?limit=3&offset=0", headers=_auth(token))
    search = client.get("/api/v1/customers?search=Acme", headers=_auth(token))
    enterprise = client.get("/api/v1/customers?plan=enterprise", headers=_auth(token))

    assert page.status_code == 200
    assert page.json()["total"] == 8
    assert page.json()["limit"] == 3
    assert len(page.json()["items"]) == 3
    assert [item["name"] for item in page.json()["items"]] == sorted(
        item["name"] for item in page.json()["items"]
    )
    assert [item["name"] for item in search.json()["items"]] == ["Asha Rao"]
    assert {item["plan"] for item in enterprise.json()["items"]} == {"enterprise"}


def test_customer_list_rejects_invalid_plan_and_pagination(client: TestClient) -> None:
    token = _login(client)

    bad_plan = client.get("/api/v1/customers?plan=unlimited", headers=_auth(token))
    bad_offset = client.get("/api/v1/customers?offset=-1", headers=_auth(token))

    assert bad_plan.status_code == 422
    assert bad_offset.status_code == 422


def test_f4_customer_detail_loads_bounded_account_context_without_raw_ticket_bodies(
    client: TestClient,
) -> None:
    token = _login(client)
    listed = client.get("/api/v1/customers?search=Asha", headers=_auth(token)).json()
    customer_id = listed["items"][0]["id"]

    response = client.get(f"/api/v1/customers/{customer_id}", headers=_auth(token))

    assert response.status_code == 200
    detail = response.json()
    assert detail["name"] == "Asha Rao"
    assert detail["company"] == "Acme Analytics"
    assert detail["subscription"]["plan"] == "enterprise"
    assert detail["subscription"]["seats"] == 120
    assert detail["workspace"]["slug"] == "acme-hq"
    assert {ticket["display_id"] for ticket in detail["previous_tickets"]} >= {
        "CD-1001",
        "CD-1007",
    }
    assert all("body" not in ticket for ticket in detail["previous_tickets"])
    assert len(detail["previous_tickets"]) <= 10
    assert len(detail["memory_notes"]) == 1
    assert detail["memory_notes"][0]["memory_type"] == "past_issue"
    assert "fingerprint" not in detail["memory_notes"][0]
    assert "attributes" not in detail["memory_notes"][0]
    assert detail["created_at"].endswith("Z")


def test_agent_role_inherits_customer_read_access(client: TestClient) -> None:
    token = _login(client, "sam.agent@clouddesk.demo")

    response = client.get("/api/v1/customers?limit=1", headers=_auth(token))

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


def test_unknown_customer_returns_contract_404(client: TestClient) -> None:
    token = _login(client)

    response = client.get(
        "/api/v1/customers/00000000-0000-0000-0000-000000000000",
        headers=_auth(token),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}

