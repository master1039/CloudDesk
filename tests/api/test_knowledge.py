"""P5-4 offline API tests for knowledge browsing, cited search, and reindex RBAC (F5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.services.auth_service import DEMO_PASSWORD
from app.services.knowledge_service import get_knowledge_runtime
from fastapi.testclient import TestClient

from rag.vector_store import VectorDocument

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _login(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_knowledge_routes_require_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/knowledge").status_code == 401
    assert client.post("/api/v1/knowledge/search", json={"query": "MFA"}).status_code == 401
    assert client.get("/api/v1/knowledge/mfa-recovery").status_code == 401


def test_knowledge_http_contract_is_synchronized_with_frontend_types() -> None:
    contract = (PROJECT_ROOT / "docs" / "API_CONTRACT.md").read_text(encoding="utf-8")
    frontend = (PROJECT_ROOT / "frontend" / "lib" / "types.ts").read_text(encoding="utf-8")

    for route in (
        "/api/v1/knowledge",
        "/api/v1/knowledge/{article_id}",
        "/api/v1/knowledge/search",
        "/api/v1/knowledge/reindex",
    ):
        assert route in contract
    for transport_type in (
        "KnowledgeArticleSummary",
        "KnowledgeArticle",
        "KnowledgeSearchRequest",
        "Evidence",
        "ReindexJob",
    ):
        assert f"interface {transport_type}" in frontend


def test_viewer_can_list_filter_search_and_page_articles(client: TestClient) -> None:
    token = _login(client, "vic.viewer@clouddesk.demo")

    page = client.get("/api/v1/knowledge?limit=4&offset=0", headers=_auth(token))
    category = client.get(
        "/api/v1/knowledge?category=api_failure",
        headers=_auth(token),
    )
    search = client.get("/api/v1/knowledge?search=authenticator", headers=_auth(token))

    assert page.status_code == 200
    assert page.json()["total"] == 15
    assert page.json()["limit"] == 4
    assert len(page.json()["items"]) == 4
    assert [item["title"] for item in page.json()["items"]] == sorted(
        item["title"] for item in page.json()["items"]
    )
    assert {item["slug"] for item in category.json()["items"]} == {
        "api-authentication",
        "api-rate-limits",
    }
    assert [item["slug"] for item in search.json()["items"]] == ["mfa-recovery"]
    assert all("body" not in item for item in page.json()["items"])


def test_viewer_can_get_article_by_slug_or_uuid_and_unknown_is_404(client: TestClient) -> None:
    token = _login(client, "vic.viewer@clouddesk.demo")
    headers = _auth(token)

    by_slug = client.get("/api/v1/knowledge/mfa-recovery", headers=headers)
    article_id = by_slug.json()["id"]
    by_id = client.get(f"/api/v1/knowledge/{article_id}", headers=headers)
    missing = client.get("/api/v1/knowledge/not-an-article", headers=headers)

    assert by_slug.status_code == by_id.status_code == 200
    assert by_slug.json() == by_id.json()
    assert by_slug.json()["category"] == "login_issue"
    assert "MFA recovery" in by_slug.json()["body"]
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Knowledge article not found"}


@pytest.mark.parametrize("mode", ["semantic", "keyword", "hybrid"])
def test_viewer_search_returns_structured_cited_evidence_in_every_mode(
    client: TestClient,
    mode: str,
) -> None:
    token = _login(client, "vic.viewer@clouddesk.demo")

    response = client.post(
        "/api/v1/knowledge/search",
        headers=_auth(token),
        json={
            "query": "HTTP 429 Retry-After rate limit",
            "category": "api_failure",
            "mode": mode,
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["article_id"] == "api-rate-limits"
    assert items[0]["source"].startswith("kb://api-rate-limits#")
    assert items[0]["url"] == "/knowledge/api-rate-limits"
    assert len({item["article_id"] for item in items}) == len(items)


def test_knowledge_request_validation_matches_the_contract(client: TestClient) -> None:
    token = _login(client, "vic.viewer@clouddesk.demo")
    headers = _auth(token)

    assert client.get("/api/v1/knowledge?limit=0", headers=headers).status_code == 422
    assert (
        client.post(
            "/api/v1/knowledge/search",
            headers=headers,
            json={"query": " ", "mode": "hybrid"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/knowledge/search",
            headers=headers,
            json={"query": "MFA", "mode": "unsupported"},
        ).status_code
        == 422
    )


def test_reindex_is_admin_only_and_recreates_the_active_index(client: TestClient) -> None:
    viewer = _login(client, "vic.viewer@clouddesk.demo")
    agent = _login(client, "sam.agent@clouddesk.demo")
    admin = _login(client, "admin@clouddesk.demo")

    assert client.post("/api/v1/knowledge/reindex", headers=_auth(viewer)).status_code == 403
    assert client.post("/api/v1/knowledge/reindex", headers=_auth(agent)).status_code == 403

    search = client.post(
        "/api/v1/knowledge/search",
        headers=_auth(viewer),
        json={"query": "MFA recovery"},
    )
    assert search.status_code == 200
    runtime = get_knowledge_runtime()
    original = runtime.index
    assert original is not None
    rogue = VectorDocument(
        "rogue:00:00",
        "rogue content",
        (0.0,) * original.vector_store.dimensions,
        {
            "article_slug": "rogue",
            "title": "Rogue",
            "source": "kb://rogue#rogue",
        },
    )
    client.portal.call(original.vector_store.add_documents, [rogue])
    assert client.portal.call(original.vector_store.count) == 31

    response = client.post("/api/v1/knowledge/reindex", headers=_auth(admin))

    assert response.status_code == 202
    assert response.json()["status"] == "completed"
    assert response.json()["article_count"] == 15
    assert response.json()["chunk_count"] == 30
    assert response.json()["indexed_count"] == 30
    assert runtime.index is not original
    assert runtime.index is not None
    assert client.portal.call(runtime.index.vector_store.count) == 30


def test_reindex_rejects_an_unsupported_provider_without_exposing_secrets(
    client: TestClient,
) -> None:
    admin = _login(client, "admin@clouddesk.demo")

    response = client.post(
        "/api/v1/knowledge/reindex",
        headers=_auth(admin),
        json={"embedding_provider": "unknown-provider"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Unsupported embedding provider: unknown-provider"}
