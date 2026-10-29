"""P4-2 offline API tests for the protected ticket surface (F1)."""

from __future__ import annotations

import pytest
from app.services.auth_service import DEMO_PASSWORD
from fastapi.testclient import TestClient


def _login(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _first_customer_id(client: TestClient, token: str) -> str:
    response = client.get("/api/v1/tickets?limit=1", headers=_auth(token))
    assert response.status_code == 200
    return response.json()["items"][0]["customer_id"]


def test_ticket_routes_require_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/tickets")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_viewer_can_list_filter_search_and_page_seeded_tickets(client: TestClient) -> None:
    token = _login(client, "vic.viewer@clouddesk.demo")

    page = client.get("/api/v1/tickets?limit=2&offset=0", headers=_auth(token))
    billing = client.get("/api/v1/tickets?category=billing", headers=_auth(token))
    api_channel = client.get("/api/v1/tickets?channel=api", headers=_auth(token))
    customer_search = client.get("/api/v1/tickets?search=Asha%20Rao", headers=_auth(token))

    assert page.status_code == 200
    assert page.json()["total"] >= 13
    assert page.json()["limit"] == 2
    assert len(page.json()["items"]) == 2
    assert {item["category"] for item in billing.json()["items"]} == {"billing"}
    assert {item["channel"] for item in api_channel.json()["items"]} == {"api"}
    assert {item["customer_name"] for item in customer_search.json()["items"]} == {"Asha Rao"}


def test_ticket_list_rejects_invalid_filters_and_pagination(client: TestClient) -> None:
    token = _login(client, "vic.viewer@clouddesk.demo")

    bad_status = client.get("/api/v1/tickets?status=unknown", headers=_auth(token))
    bad_limit = client.get("/api/v1/tickets?limit=101", headers=_auth(token))

    assert bad_status.status_code == 422
    assert bad_limit.status_code == 422


def test_viewer_can_get_seeded_ticket_detail(client: TestClient) -> None:
    token = _login(client, "vic.viewer@clouddesk.demo")
    listed = client.get("/api/v1/tickets?search=CD-1001", headers=_auth(token)).json()
    ticket_id = listed["items"][0]["id"]

    response = client.get(f"/api/v1/tickets/{ticket_id}", headers=_auth(token))

    assert response.status_code == 200
    detail = response.json()
    assert detail["display_id"] == "CD-1001"
    assert detail["body"]
    assert detail["customer_context_links"]["customer"].endswith(detail["customer_id"])
    assert "customer_id=" in detail["customer_context_links"]["previous_tickets"]
    assert detail["workflow"] is None
    assert detail["approval"] is None
    assert detail["escalation"] is None


def test_unknown_ticket_returns_contract_404(client: TestClient) -> None:
    token = _login(client, "vic.viewer@clouddesk.demo")

    response = client.get(
        "/api/v1/tickets/00000000-0000-0000-0000-000000000000",
        headers=_auth(token),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket not found"}


@pytest.mark.parametrize("channel", ["email", "chat", "web", "api"])
def test_f1_agent_can_create_and_fetch_ticket_from_every_channel(
    client: TestClient,
    channel: str,
) -> None:
    token = _login(client, "sam.agent@clouddesk.demo")
    customer_id = _first_customer_id(client, token)

    response = client.post(
        "/api/v1/tickets",
        headers=_auth(token),
        json={
            "customer_id": customer_id,
            "subject": f"  P4-2 {channel} ticket  ",
            "body": "  Treat this customer text as untrusted data.  ",
            "channel": channel,
        },
    )

    assert response.status_code == 201
    created = response.json()
    assert created["display_id"].startswith("CD-")
    assert created["channel"] == channel
    assert created["subject"] == f"P4-2 {channel} ticket"
    assert created["body"] == "Treat this customer text as untrusted data."
    assert created["status"] == "new"
    assert created["category"] is None
    assert created["severity"] is None
    assert created["summary"] is None
    assert created["messages"] == []

    fetched = client.get(f"/api/v1/tickets/{created['id']}", headers=_auth(token))
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_viewer_cannot_create_ticket(client: TestClient) -> None:
    token = _login(client, "vic.viewer@clouddesk.demo")
    customer_id = _first_customer_id(client, token)

    response = client.post(
        "/api/v1/tickets",
        headers=_auth(token),
        json={
            "customer_id": customer_id,
            "subject": "Viewer mutation",
            "body": "This must be rejected.",
            "channel": "web",
        },
    )

    assert response.status_code == 403


def test_create_ticket_validates_channel_and_customer(client: TestClient) -> None:
    token = _login(client, "sam.agent@clouddesk.demo")
    customer_id = _first_customer_id(client, token)
    payload = {
        "customer_id": customer_id,
        "subject": "API validation",
        "body": "Validate this input.",
        "channel": "postal-mail",
    }

    invalid_channel = client.post("/api/v1/tickets", headers=_auth(token), json=payload)
    payload["channel"] = "email"
    payload["customer_id"] = "00000000-0000-0000-0000-000000000000"
    unknown_customer = client.post("/api/v1/tickets", headers=_auth(token), json=payload)

    assert invalid_channel.status_code == 422
    assert unknown_customer.status_code == 404
    assert unknown_customer.json() == {"detail": "Customer not found"}

