"""P5-3 tests for cited hybrid retrieval, reranking, filtering, and cache behavior (F5)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from rag.chunking import chunk_articles, load_article_files
from rag.embeddings import FakeEmbeddings
from rag.retriever import (
    RETRIEVAL_CACHE_TTL_SECONDS,
    Evidence,
    HybridRetriever,
    RetrievalMode,
    heuristic_rerank,
    reciprocal_rank_fusion,
    retrieval_cache_key,
)
from rag.vector_store import InMemoryVectorStore, VectorDocument, vector_documents_from_chunks

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = PROJECT_ROOT / "sample_data" / "knowledge_base"


class SpyCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, int]] = []

    async def get(self, name: str) -> str | None:
        self.get_calls.append(name)
        return self.values.get(name)

    async def set(self, name: str, value: str, *, ex: int) -> bool:
        self.values[name] = value
        self.set_calls.append((name, ex))
        return True


class PromoteMfaReranker:
    async def rerank(self, query: str, evidence: Sequence[Evidence]) -> Sequence[str]:
        del query
        promoted = next(item.id for item in evidence if item.article_id == "mfa-recovery")
        return [promoted, *(item.id for item in evidence if item.id != promoted)]


async def _build_retriever(
    *,
    cache: SpyCache | None = None,
    reranker: PromoteMfaReranker | None = None,
) -> HybridRetriever:
    chunks = chunk_articles(load_article_files(KNOWLEDGE_DIR))
    embeddings = FakeEmbeddings()
    documents = await vector_documents_from_chunks(chunks, embeddings)
    store = InMemoryVectorStore(embeddings.dimensions)
    await store.add_documents(documents)
    return HybridRetriever(
        documents,
        embeddings=embeddings,
        vector_store=store,
        cache=cache,
        reranker=reranker,
    )


@pytest.mark.parametrize(
    ("query", "article_id"),
    [
        ("lost authenticator MFA lockout reset", "mfa-recovery"),
        ("HTTP 429 Retry-After exponential backoff", "api-rate-limits"),
        ("storage quota upload blocked", "storage-quota"),
        ("Slack integration reconnect OAuth", "slack-integration"),
    ],
)
async def test_hybrid_retrieval_returns_expected_article_in_top_three_for_key_queries(
    query: str,
    article_id: str,
) -> None:
    retriever = await _build_retriever()

    evidence = await retriever.retrieve(query, top_k=3)

    assert article_id in [item.article_id for item in evidence]


@pytest.mark.parametrize("mode", list(RetrievalMode))
async def test_semantic_keyword_and_hybrid_modes_return_cited_evidence(
    mode: RetrievalMode,
) -> None:
    retriever = await _build_retriever()

    evidence = await retriever.retrieve(
        "HTTP 429 Retry-After rate limit",
        mode=mode,
        top_k=3,
    )

    assert evidence
    assert evidence[0].article_id == "api-rate-limits"
    assert evidence[0].source.startswith("kb://api-rate-limits#")
    assert evidence[0].url == "/knowledge/api-rate-limits"
    assert evidence[0].snippet


def test_reciprocal_rank_fusion_uses_k_60_and_rewards_cross_source_results() -> None:
    scores = reciprocal_rank_fusion([["semantic-only", "shared"], ["shared", "keyword-only"]])

    assert scores["shared"] > scores["semantic-only"]
    assert scores["shared"] > scores["keyword-only"]
    assert scores["semantic-only"] == pytest.approx(1 / 61)


def test_heuristic_rerank_boosts_category_and_title_overlap() -> None:
    documents = {
        "generic": VectorDocument(
            "generic",
            "generic content",
            (1.0,),
            {"title": "General troubleshooting", "category": "other"},
        ),
        "specific": VectorDocument(
            "specific",
            "specific content",
            (1.0,),
            {"title": "Storage quota limits", "category": "storage_quota"},
        ),
    }

    reranked = heuristic_rerank(
        documents,
        {"generic": 0.5, "specific": 0.5},
        query="storage quota",
        category="storage_quota",
    )

    assert [document_id for document_id, _ in reranked] == ["specific", "generic"]


async def test_filters_apply_to_semantic_and_keyword_candidates() -> None:
    retriever = await _build_retriever()

    by_category = await retriever.retrieve(
        "account access troubleshooting",
        filters={"category": "api_failure"},
        top_k=5,
    )
    by_tag = await retriever.retrieve(
        "retry response",
        filters={"tags": "429"},
        top_k=5,
    )

    assert by_category
    assert {item.article_id for item in by_category} <= {
        "api-authentication",
        "api-rate-limits",
    }
    assert [item.article_id for item in by_tag] == ["api-rate-limits"]


async def test_results_keep_only_the_best_chunk_per_article() -> None:
    retriever = await _build_retriever()

    evidence = await retriever.retrieve("support troubleshooting account API storage", top_k=15)

    article_ids = [item.article_id for item in evidence]
    assert len(article_ids) == len(set(article_ids))
    assert all(item.id and item.title and item.source for item in evidence)


async def test_retrieval_cache_uses_documented_key_and_300_second_ttl() -> None:
    cache = SpyCache()
    retriever = await _build_retriever(cache=cache)
    query = "MFA recovery after lockout"

    first = await retriever.retrieve(query, mode="hybrid", category="login_issue", top_k=3)
    second = await retriever.retrieve(query, mode="hybrid", category="login_issue", top_k=3)

    key = retrieval_cache_key(
        query,
        mode=RetrievalMode.HYBRID,
        category="login_issue",
        top_k=3,
    )
    assert first == second
    assert cache.get_calls == [key, key]
    assert cache.set_calls == [(key, RETRIEVAL_CACHE_TTL_SECONDS)]
    assert key == "rag:hybrid:login_issue:3:mfa recovery after lockout"


async def test_optional_reranker_can_reorder_but_cannot_invent_evidence() -> None:
    retriever = await _build_retriever(reranker=PromoteMfaReranker())

    evidence = await retriever.retrieve(
        "account access support recovery authentication",
        top_k=5,
    )

    assert evidence[0].article_id == "mfa-recovery"
    assert len({item.id for item in evidence}) == len(evidence)


async def test_retriever_rejects_invalid_requests() -> None:
    retriever = await _build_retriever()

    with pytest.raises(ValueError, match="must not be blank"):
        await retriever.retrieve(" ")
    with pytest.raises(ValueError, match="unsupported retrieval mode"):
        await retriever.retrieve("query", mode="unknown")
    with pytest.raises(ValueError, match="top_k must be positive"):
        await retriever.retrieve("query", top_k=0)


async def test_corrupt_cache_entry_is_ignored_and_replaced() -> None:
    cache = SpyCache()
    key = "rag:hybrid:all:2:mfa recovery"
    cache.values[key] = "not-json"
    retriever = await _build_retriever(cache=cache)

    evidence = await retriever.retrieve("MFA recovery", top_k=2)

    assert evidence
    assert cache.set_calls == [(key, RETRIEVAL_CACHE_TTL_SECONDS)]
