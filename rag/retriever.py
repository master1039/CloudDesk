"""Offline-capable semantic, BM25, and hybrid retrieval for CloudDesk knowledge."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from rank_bm25 import BM25Okapi

from .embeddings import EmbeddingService
from .vector_store import MetadataScalar, VectorDocument, VectorStoreService

RRF_K = 60
RETRIEVAL_CACHE_TTL_SECONDS = 300
DEFAULT_CANDIDATE_LIMIT = 20
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class RetrievalMode(StrEnum):
    """Supported knowledge retrieval strategies."""

    HYBRID = "hybrid"
    SEMANTIC = "semantic"
    KEYWORD = "keyword"


@dataclass(frozen=True, slots=True)
class Evidence:
    """One cited knowledge result exposed to later agents and APIs."""

    id: str
    title: str
    source: str
    snippet: str
    score: float
    url: str
    article_id: str


@runtime_checkable
class RetrievalCache(Protocol):
    """Minimal async cache contract implemented by redis-py and fakeredis."""

    async def get(self, name: str) -> str | bytes | None: ...

    async def set(self, name: str, value: str, *, ex: int) -> Any: ...


@runtime_checkable
class EvidenceReranker(Protocol):
    """Optional model-backed ordering hook; it cannot create new evidence."""

    async def rerank(self, query: str, evidence: Sequence[Evidence]) -> Sequence[str]: ...


def _tokens(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.casefold())


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    *,
    k: int = RRF_K,
) -> dict[str, float]:
    """Fuse ranked identifier lists without requiring comparable source scores."""

    if k <= 0:
        raise ValueError("RRF k must be positive")
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, document_id in enumerate(ranking, start=1):
            if document_id in seen:
                continue
            seen.add(document_id)
            scores[document_id] = scores.get(document_id, 0.0) + 1.0 / (k + rank)
    return scores


def heuristic_rerank(
    documents: Mapping[str, VectorDocument],
    scores: Mapping[str, float],
    *,
    query: str,
    category: str | None = None,
) -> list[tuple[str, float]]:
    """Boost category matches and query overlap with an article title."""

    query_tokens = set(_tokens(query))
    reranked: list[tuple[str, float]] = []
    for document_id, base_score in scores.items():
        document = documents.get(document_id)
        if document is None:
            continue
        title = str(document.metadata.get("title", ""))
        title_overlap = (
            len(query_tokens.intersection(_tokens(title))) / len(query_tokens)
            if query_tokens
            else 0.0
        )
        category_match = category is not None and document.metadata.get("category") == category
        score = base_score + (0.02 if category_match else 0.0) + (0.01 * title_overlap)
        reranked.append((document_id, score))
    reranked.sort(key=lambda item: (-item[1], item[0]))
    return reranked


def retrieval_cache_key(
    query: str,
    *,
    mode: RetrievalMode,
    category: str | None,
    top_k: int,
) -> str:
    """Build the stable cache key documented by the memory contract."""

    normalized_query = " ".join(query.casefold().split())
    return f"rag:{mode.value}:{category or 'all'}:{top_k}:{normalized_query}"


class HybridRetriever:
    """Combine semantic and keyword rankings while returning portable citations."""

    def __init__(
        self,
        documents: Sequence[VectorDocument],
        *,
        embeddings: EmbeddingService,
        vector_store: VectorStoreService,
        cache: RetrievalCache | None = None,
        reranker: EvidenceReranker | None = None,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> None:
        if candidate_limit <= 0:
            raise ValueError("candidate limit must be positive")
        if embeddings.dimensions != vector_store.dimensions:
            raise ValueError("embedding and vector-store dimensions must match")
        if any(len(document.vector) != embeddings.dimensions for document in documents):
            raise ValueError("every document vector must match the embedding dimensions")

        self._documents = {document.id: document for document in documents}
        if len(self._documents) != len(documents):
            raise ValueError("vector document ids must be unique")
        self._ordered_documents = tuple(documents)
        self._embeddings = embeddings
        self._vector_store = vector_store
        self._cache = cache
        self._reranker = reranker
        self._candidate_limit = candidate_limit
        corpus = [_tokens(document.content) for document in self._ordered_documents]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    @staticmethod
    def _matches_filters(
        document: VectorDocument,
        filters: Mapping[str, MetadataScalar],
    ) -> bool:
        for name, expected in filters.items():
            actual = document.metadata.get(name)
            if isinstance(actual, list):
                if expected not in actual:
                    return False
            elif actual != expected:
                return False
        return True

    def _keyword_ranking(
        self,
        query: str,
        filters: Mapping[str, MetadataScalar],
        limit: int,
    ) -> list[str]:
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(_tokens(query))
        ranked = [
            (document.id, float(score))
            for document, score in zip(self._ordered_documents, scores, strict=True)
            if self._matches_filters(document, filters)
        ]
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return [document_id for document_id, _ in ranked[:limit]]

    async def _semantic_ranking(
        self,
        query: str,
        filters: Mapping[str, MetadataScalar],
        limit: int,
    ) -> list[str]:
        vector = await self._embeddings.embed_query(query)
        results = await self._vector_store.search(vector, limit=limit, filters=filters)
        return [result.id for result in results]

    @staticmethod
    def _required_metadata(document: VectorDocument, name: str) -> str:
        value = document.metadata.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"vector document {document.id!r} is missing metadata {name!r}")
        return value.strip()

    def _evidence(self, document_id: str, score: float) -> Evidence:
        document = self._documents[document_id]
        article_id = self._required_metadata(document, "article_slug")
        title = self._required_metadata(document, "title")
        source = self._required_metadata(document, "source")
        snippet = " ".join(document.content.split())
        if len(snippet) > 400:
            snippet = f"{snippet[:397].rstrip()}..."
        return Evidence(
            id=document.id,
            title=title,
            source=source,
            snippet=snippet,
            score=score,
            url=f"/knowledge/{article_id}",
            article_id=article_id,
        )

    async def _cached(self, key: str) -> list[Evidence] | None:
        if self._cache is None:
            return None
        value = await self._cache.get(key)
        if value is None:
            return None
        try:
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            payload = json.loads(value)
            if not isinstance(payload, list):
                return None
            return [Evidence(**item) for item in payload if isinstance(item, dict)]
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValueError):
            return None

    async def _store_cache(self, key: str, evidence: Sequence[Evidence]) -> None:
        if self._cache is None:
            return
        await self._cache.set(
            key,
            json.dumps([asdict(item) for item in evidence], separators=(",", ":")),
            ex=RETRIEVAL_CACHE_TTL_SECONDS,
        )

    async def retrieve(
        self,
        query: str,
        *,
        mode: RetrievalMode | str = RetrievalMode.HYBRID,
        category: str | None = None,
        top_k: int = 5,
        filters: Mapping[str, MetadataScalar] | None = None,
    ) -> list[Evidence]:
        """Retrieve cited evidence in semantic, keyword, or fused hybrid mode."""

        if not query.strip():
            raise ValueError("retrieval query must not be blank")
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        try:
            active_mode = RetrievalMode(mode)
        except ValueError as error:
            raise ValueError(f"unsupported retrieval mode: {mode}") from error

        active_filters = dict(filters or {})
        cacheable = not active_filters
        cache_key = retrieval_cache_key(
            query,
            mode=active_mode,
            category=category,
            top_k=top_k,
        )
        if cacheable and (cached := await self._cached(cache_key)) is not None:
            return cached

        candidate_limit = max(self._candidate_limit, top_k * 4)
        rankings: list[list[str]] = []
        if active_mode in {RetrievalMode.HYBRID, RetrievalMode.SEMANTIC}:
            rankings.append(
                await self._semantic_ranking(query, active_filters, candidate_limit)
            )
        if active_mode in {RetrievalMode.HYBRID, RetrievalMode.KEYWORD}:
            rankings.append(self._keyword_ranking(query, active_filters, candidate_limit))

        fused = reciprocal_rank_fusion(rankings)
        reranked = heuristic_rerank(
            self._documents,
            fused,
            query=query,
            category=category,
        )
        candidates = [self._evidence(document_id, score) for document_id, score in reranked]

        if self._reranker is not None and candidates:
            requested_order = await self._reranker.rerank(query, candidates)
            by_id = {item.id: item for item in candidates}
            ordered: list[Evidence] = []
            seen_ids: set[str] = set()
            for document_id in requested_order:
                if document_id in by_id and document_id not in seen_ids:
                    ordered.append(by_id[document_id])
                    seen_ids.add(document_id)
            ordered.extend(item for item in candidates if item.id not in seen_ids)
            candidates = ordered

        evidence: list[Evidence] = []
        seen_articles: set[str] = set()
        for item in candidates:
            if item.article_id in seen_articles:
                continue
            seen_articles.add(item.article_id)
            evidence.append(item)
            if len(evidence) == top_k:
                break

        if cacheable:
            await self._store_cache(cache_key, evidence)
        return evidence
