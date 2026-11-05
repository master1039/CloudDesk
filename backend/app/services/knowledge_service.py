"""Knowledge browsing plus the process-scoped offline retrieval runtime."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.redis import RedisClient, get_redis_client
from app.models import SupportArticle
from app.repositories import SupportArticleRepository
from app.schemas.knowledge import (
    EvidenceResponse,
    KnowledgeArticleResponse,
    KnowledgeArticleSummary,
    KnowledgeListParams,
    KnowledgeListResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    ReindexJob,
    ReindexRequest,
)
from app.services.ticket_service import as_utc
from sqlalchemy.ext.asyncio import AsyncSession

from rag.ingest import KnowledgeIndex, ingest_from_settings
from rag.vector_store import close_vector_store


class KnowledgeArticleNotFoundError(LookupError):
    """Raised when a published knowledge article cannot be found."""


def _article_summary(article: SupportArticle) -> KnowledgeArticleSummary:
    return KnowledgeArticleSummary(
        id=article.id,
        slug=article.slug,
        title=article.title,
        category=article.category,
        tags=list(article.tags),
        summary=article.summary,
        updated_at=as_utc(article.updated_at),
    )


class KnowledgeRuntime:
    """Own the active vector index and swap it atomically after successful reindexing."""

    def __init__(self) -> None:
        self._index: KnowledgeIndex | None = None
        self._lock = asyncio.Lock()

    @property
    def index(self) -> KnowledgeIndex | None:
        return self._index

    async def ensure_index(
        self,
        settings: Settings,
        cache: RedisClient,
    ) -> KnowledgeIndex:
        if self._index is not None:
            return self._index
        async with self._lock:
            if self._index is None:
                self._index = await ingest_from_settings(settings, cache=cache)
            return self._index

    async def reindex(
        self,
        settings: Settings,
        cache: RedisClient,
    ) -> KnowledgeIndex:
        async with self._lock:
            replacement = await ingest_from_settings(settings, recreate=True, cache=cache)
            previous = self._index
            self._index = replacement
            async for key in cache.scan_iter(match="rag:*"):
                await cache.delete(key)
            if previous is not None:
                await close_vector_store(previous.vector_store)
            return replacement

    async def close(self) -> None:
        async with self._lock:
            if self._index is not None:
                await close_vector_store(self._index.vector_store)
                self._index = None


_knowledge_runtime = KnowledgeRuntime()


def get_knowledge_runtime() -> KnowledgeRuntime:
    return _knowledge_runtime


async def close_knowledge_runtime() -> None:
    await _knowledge_runtime.close()


class KnowledgeService:
    """Coordinate SQL article reads and infrastructure-neutral RAG operations."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        runtime: KnowledgeRuntime | None = None,
        settings: Settings | None = None,
        cache: RedisClient | None = None,
    ) -> None:
        self.articles = SupportArticleRepository(session)
        self.runtime = runtime or get_knowledge_runtime()
        self.settings = settings or get_settings()
        self.cache = cache or get_redis_client()

    async def list_articles(self, params: KnowledgeListParams) -> KnowledgeListResponse:
        filters = params.model_dump(exclude={"limit", "offset"})
        articles = await self.articles.list_published(
            **filters,
            limit=params.limit,
            offset=params.offset,
        )
        total = await self.articles.count_published(**filters)
        return KnowledgeListResponse(
            items=[_article_summary(article) for article in articles],
            total=total,
            limit=params.limit,
            offset=params.offset,
        )

    async def get_article(self, article_id: str) -> KnowledgeArticleResponse:
        article = await self.articles.get_published(article_id)
        if article is None:
            raise KnowledgeArticleNotFoundError(article_id)
        return KnowledgeArticleResponse(
            **_article_summary(article).model_dump(),
            body=article.body,
        )

    async def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
        index = await self.runtime.ensure_index(self.settings, self.cache)
        evidence = await index.retriever.retrieve(
            request.query,
            mode=request.mode,
            category=request.category.value if request.category else None,
            top_k=request.top_k,
        )
        return KnowledgeSearchResponse(
            items=[EvidenceResponse.model_validate(item) for item in evidence]
        )

    async def reindex(self, request: ReindexRequest) -> ReindexJob:
        overrides = {
            name: value for name, value in request.model_dump().items() if value is not None
        }
        settings = self.settings.model_copy(update=overrides)
        index = await self.runtime.reindex(settings, self.cache)
        report = index.report
        return ReindexJob(
            id=str(uuid4()),
            status="completed",
            collection=report.collection,
            article_count=report.article_count,
            chunk_count=report.chunk_count,
            indexed_count=report.indexed_count,
            created_at=datetime.now(UTC),
        )
