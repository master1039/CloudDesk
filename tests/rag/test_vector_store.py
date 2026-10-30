"""P5-2 tests for deterministic fake embeddings and interchangeable vector stores (F5)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from app.core.config import Settings
from pydantic import SecretStr
from qdrant_client import AsyncQdrantClient

from rag.chunking import chunk_articles, load_article_files
from rag.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingService,
    FakeEmbeddings,
    get_embedding_service,
)
from rag.vector_store import (
    InMemoryVectorStore,
    QdrantVectorStore,
    VectorDocument,
    VectorStoreConfigurationError,
    VectorStoreService,
    get_vector_store,
    vector_documents_from_chunks,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = PROJECT_ROOT / "sample_data" / "knowledge_base"


async def test_fake_embeddings_are_deterministic_normalized_and_384_dimensional() -> None:
    first = FakeEmbeddings()
    second = FakeEmbeddings()

    vectors = await first.embed_documents(
        ["MFA recovery after lockout", "mfa, RECOVERY after lockout!", ""]
    )

    assert isinstance(first, EmbeddingService)
    assert first.dimensions == 384
    assert vectors[0] == vectors[1] == await second.embed_query("MFA recovery after lockout")
    assert len(vectors[0]) == 384
    assert math.isclose(math.sqrt(sum(value * value for value in vectors[0])), 1.0)
    assert vectors[2] == (0.0,) * 384


async def test_fake_embeddings_preserve_lexical_similarity_for_offline_search() -> None:
    embeddings = FakeEmbeddings()
    query = await embeddings.embed_query("MFA account recovery")
    [related, unrelated] = await embeddings.embed_documents(
        ["MFA recovery and account lockout", "billing invoice seat refund"]
    )
    store = InMemoryVectorStore(embeddings.dimensions)
    await store.add_documents(
        [
            VectorDocument("related", "MFA article", related, {"category": "login_issue"}),
            VectorDocument("unrelated", "Billing article", unrelated, {"category": "billing"}),
        ]
    )

    results = await store.search(query, limit=2)

    assert [result.id for result in results] == ["related", "unrelated"]
    assert results[0].score > results[1].score


async def test_chunks_embed_into_portable_documents_with_citation_metadata() -> None:
    chunks = chunk_articles(load_article_files(KNOWLEDGE_DIR))

    documents = await vector_documents_from_chunks(chunks, FakeEmbeddings())

    assert len(documents) == 30
    assert all(len(document.vector) == 384 for document in documents)
    mfa = next(document for document in documents if document.id == "mfa-recovery:01:00")
    assert mfa.metadata["category"] == "login_issue"
    assert mfa.metadata["source"] == "kb://mfa-recovery#reset"
    assert mfa.metadata["tags"] == ["mfa", "recovery", "lockout"]
    assert mfa.content.startswith("Recover access after MFA lockout - Reset")


async def _exercise_store_contract(store: VectorStoreService) -> None:
    embeddings = FakeEmbeddings(store.dimensions)
    related, unrelated, query = await embeddings.embed_documents(
        [
            "API HTTP 429 rate limit retry",
            "MFA authentication reset",
            "429 retry after rate limit",
        ]
    )
    documents = [
        VectorDocument(
            "api-rate:00",
            "API rate-limit guidance",
            related,
            {"category": "api_failure", "tags": ["api", "429"]},
        ),
        VectorDocument(
            "mfa:00",
            "MFA recovery guidance",
            unrelated,
            {"category": "login_issue", "tags": ["mfa"]},
        ),
    ]

    assert await store.count() == 0
    await store.add_documents(documents)
    assert await store.count() == 2
    assert await store.health() is True

    results = await store.search(query, limit=2)
    assert [result.id for result in results] == ["api-rate:00", "mfa:00"]
    assert results[0].score > results[1].score

    filtered = await store.search(query, filters={"category": "login_issue"})
    assert [result.id for result in filtered] == ["mfa:00"]

    tag_filtered = await store.search(query, filters={"tags": "429"})
    assert [result.id for result in tag_filtered] == ["api-rate:00"]

    replacement = VectorDocument(
        "api-rate:00",
        "Updated API guidance",
        related,
        {"category": "api_failure", "tags": ["api", "429"]},
    )
    await store.add_documents([replacement])
    assert await store.count() == 2
    assert (await store.search(query, limit=1))[0].content == "Updated API guidance"

    await store.delete(["api-rate:00", "missing-id"])
    assert await store.count() == 1


async def test_in_memory_store_satisfies_the_vector_store_contract() -> None:
    store = InMemoryVectorStore(384)

    assert isinstance(store, VectorStoreService)
    await _exercise_store_contract(store)


async def test_qdrant_adapter_satisfies_contract_in_embedded_local_mode() -> None:
    client = AsyncQdrantClient(location=":memory:")
    store = QdrantVectorStore(
        dimensions=384,
        collection="p5_2_contract",
        client=client,
    )
    try:
        assert await store.health() is False
        await _exercise_store_contract(store)
    finally:
        await client.close()


async def test_vector_store_validates_dimensions_limits_and_non_finite_values() -> None:
    store = InMemoryVectorStore(3)
    valid = VectorDocument("valid", "content", (1.0, 0.0, 0.0), {})

    with pytest.raises(ValueError, match="3-dimensional"):
        await store.add_documents([VectorDocument("bad", "content", (1.0, 0.0), {})])
    await store.add_documents([valid])
    with pytest.raises(ValueError, match="finite"):
        await store.search((math.nan, 0.0, 0.0))
    with pytest.raises(ValueError, match="positive"):
        await store.search((1.0, 0.0, 0.0), limit=0)


def test_factories_select_offline_services_and_reject_unknown_providers() -> None:
    settings = Settings(
        embedding_provider="fake",
        embedding_dimensions=12,
        vector_store="memory",
    )

    embeddings = get_embedding_service(settings)
    store = get_vector_store(settings)

    assert isinstance(embeddings, FakeEmbeddings)
    assert embeddings.dimensions == 12
    assert isinstance(store, InMemoryVectorStore)
    assert store.dimensions == 12

    with pytest.raises(EmbeddingConfigurationError, match="Unsupported"):
        get_embedding_service(Settings(embedding_provider="unknown"))
    with pytest.raises(VectorStoreConfigurationError, match="Unsupported"):
        get_vector_store(Settings(vector_store="unknown"))


async def test_qdrant_configuration_never_exposes_or_requires_a_key_for_injected_client() -> None:
    settings = Settings(
        vector_store="qdrant",
        embedding_dimensions=8,
        qdrant_collection="test_collection",
        qdrant_api_key=SecretStr("test-only-secret"),
    )
    client = AsyncQdrantClient(location=":memory:")
    try:
        store = get_vector_store(settings, qdrant_client=client)
        assert isinstance(store, QdrantVectorStore)
        assert store.dimensions == 8
        assert "test-only-secret" not in repr(store)
    finally:
        await client.close()

