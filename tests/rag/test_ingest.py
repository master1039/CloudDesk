"""P5-4 ingestion and measured offline retrieval tests (F5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.core.config import Settings
from qdrant_client import AsyncQdrantClient

from rag.ingest import ingest_from_settings
from rag.vector_store import (
    QdrantVectorStore,
    VectorDocument,
    close_vector_store,
    recreate_vector_store,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "sample_data_dir": SAMPLE_DATA_DIR,
        "embedding_provider": "fake",
        "embedding_dimensions": 384,
        "vector_store": "memory",
    }
    values.update(overrides)
    return Settings(**values)


async def test_ingest_reports_all_articles_chunks_and_indexed_vectors() -> None:
    index = await ingest_from_settings(_settings(), recreate=True)
    try:
        assert index.report.article_count == 15
        assert index.report.chunk_count == 30
        assert index.report.indexed_count == 30
        assert len(index.articles) == 15
        assert len(index.documents) == 30
        assert await index.vector_store.count() == 30
    finally:
        await close_vector_store(index.vector_store)


async def test_f5_measured_hybrid_hit_rate_at_three_meets_phase_threshold() -> None:
    index = await ingest_from_settings(_settings(), recreate=True)
    cases = [
        ("lost authenticator MFA lockout reset", "mfa-recovery"),
        ("HTTP 429 Retry-After exponential backoff", "api-rate-limits"),
        ("storage quota upload blocked", "storage-quota"),
        ("Slack integration reconnect OAuth", "slack-integration"),
        ("delete account GDPR retention", "account-deletion"),
        ("billing payment charge dispute", "billing-disputes"),
        ("recover a deleted file", "file-recovery"),
        ("workspace member roles permissions", "workspace-roles"),
    ]
    try:
        hits = 0
        for query, expected_article in cases:
            evidence = await index.retriever.retrieve(query, top_k=3)
            hits += expected_article in {item.article_id for item in evidence}

        hit_rate_at_three = hits / len(cases)
        assert hit_rate_at_three >= 0.75
    finally:
        await close_vector_store(index.vector_store)


async def test_qdrant_recreate_removes_the_existing_collection() -> None:
    client = AsyncQdrantClient(location=":memory:")
    settings = Settings(
        vector_store="qdrant",
        embedding_dimensions=3,
        qdrant_collection="p5_4_recreate",
    )
    original = QdrantVectorStore(
        dimensions=3,
        collection=settings.qdrant_collection,
        client=client,
    )
    await original.add_documents([VectorDocument("old", "old content", (1.0, 0.0, 0.0), {})])
    assert await original.count() == 1

    recreated = await recreate_vector_store(settings, qdrant_client=client)
    try:
        assert await recreated.count() == 0
        assert await recreated.health() is False
    finally:
        await close_vector_store(recreated)


async def test_ingest_rejects_an_unavailable_embedding_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        await ingest_from_settings(_settings(embedding_provider="unknown"), recreate=True)
