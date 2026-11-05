"""Provider-independent vector storage with memory and Qdrant implementations."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import NAMESPACE_URL, uuid5

from app.core.config import Settings, get_settings
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ApiException

from .chunking import KnowledgeChunk
from .embeddings import EmbeddingService

type MetadataScalar = str | int | float | bool
type MetadataValue = MetadataScalar | list[str]
type Metadata = Mapping[str, MetadataValue]


class VectorStoreConfigurationError(ValueError):
    """Raised for an unsupported or incomplete vector-store configuration."""


@dataclass(frozen=True, slots=True)
class VectorDocument:
    """Embedded text and metadata accepted by every vector-store implementation."""

    id: str
    content: str
    vector: tuple[float, ...]
    metadata: Metadata

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("vector document id must not be blank")
        if not self.content.strip():
            raise ValueError("vector document content must not be blank")


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    """Infrastructure-neutral nearest-neighbor result."""

    id: str
    content: str
    metadata: Metadata
    score: float


@runtime_checkable
class VectorStoreService(Protocol):
    """Operations required by ingestion, retrieval, and readiness checks."""

    @property
    def dimensions(self) -> int: ...

    async def add_documents(self, documents: Sequence[VectorDocument]) -> None: ...

    async def search(
        self,
        query_vector: Sequence[float],
        *,
        limit: int = 5,
        filters: Mapping[str, MetadataScalar] | None = None,
    ) -> list[VectorSearchResult]: ...

    async def delete(self, document_ids: Sequence[str]) -> None: ...

    async def count(self) -> int: ...

    async def health(self) -> bool: ...


def _validate_dimensions(vector: Sequence[float], dimensions: int) -> tuple[float, ...]:
    if len(vector) != dimensions:
        raise ValueError(f"expected a {dimensions}-dimensional vector, received {len(vector)}")
    values = tuple(float(value) for value in vector)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("vectors must contain only finite numbers")
    return values


def _matches_filters(metadata: Metadata, filters: Mapping[str, MetadataScalar]) -> bool:
    for name, expected in filters.items():
        actual = metadata.get(name)
        if isinstance(actual, list):
            if expected not in actual:
                return False
        elif actual != expected:
            return False
    return True


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(first * second for first, second in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


class InMemoryVectorStore:
    """Concurrency-safe in-process cosine store used by demo and tests."""

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions <= 0:
            raise ValueError("vector-store dimensions must be positive")
        self._dimensions = dimensions
        self._documents: dict[str, VectorDocument] = {}
        self._lock = asyncio.Lock()

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def add_documents(self, documents: Sequence[VectorDocument]) -> None:
        validated = [
            VectorDocument(
                id=document.id,
                content=document.content,
                vector=_validate_dimensions(document.vector, self.dimensions),
                metadata=dict(document.metadata),
            )
            for document in documents
        ]
        async with self._lock:
            self._documents.update({document.id: document for document in validated})

    async def search(
        self,
        query_vector: Sequence[float],
        *,
        limit: int = 5,
        filters: Mapping[str, MetadataScalar] | None = None,
    ) -> list[VectorSearchResult]:
        if limit <= 0:
            raise ValueError("search limit must be positive")
        query = _validate_dimensions(query_vector, self.dimensions)
        active_filters = filters or {}
        async with self._lock:
            documents = list(self._documents.values())

        results = [
            VectorSearchResult(
                id=document.id,
                content=document.content,
                metadata=dict(document.metadata),
                score=_cosine_similarity(query, document.vector),
            )
            for document in documents
            if _matches_filters(document.metadata, active_filters)
        ]
        results.sort(key=lambda result: (-result.score, result.id))
        return results[:limit]

    async def delete(self, document_ids: Sequence[str]) -> None:
        async with self._lock:
            for document_id in document_ids:
                self._documents.pop(document_id, None)

    async def count(self) -> int:
        async with self._lock:
            return len(self._documents)

    async def health(self) -> bool:
        return True


class QdrantVectorStore:
    """Async Qdrant adapter using cosine distance and portable CloudDesk payloads."""

    def __init__(
        self,
        *,
        dimensions: int,
        collection: str,
        url: str | None = None,
        api_key: str | None = None,
        client: AsyncQdrantClient | None = None,
    ) -> None:
        if dimensions <= 0:
            raise ValueError("vector-store dimensions must be positive")
        if not collection.strip():
            raise VectorStoreConfigurationError("Qdrant collection must not be blank")
        if client is None and not url:
            raise VectorStoreConfigurationError("Qdrant URL is required")
        self._dimensions = dimensions
        self.collection = collection
        self.client = client if client is not None else AsyncQdrantClient(url=url, api_key=api_key)
        self._collection_lock = asyncio.Lock()

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _point_id(self, document_id: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"clouddesk:{self.collection}:{document_id}"))

    async def _collection_exists(self) -> bool:
        return await self.client.collection_exists(self.collection)

    async def _ensure_collection(self) -> None:
        if await self._collection_exists():
            return
        async with self._collection_lock:
            if not await self._collection_exists():
                await self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=self.dimensions,
                        distance=models.Distance.COSINE,
                    ),
                )

    async def add_documents(self, documents: Sequence[VectorDocument]) -> None:
        if not documents:
            return
        await self._ensure_collection()
        points = [
            models.PointStruct(
                id=self._point_id(document.id),
                vector=list(_validate_dimensions(document.vector, self.dimensions)),
                payload={
                    "document_id": document.id,
                    "content": document.content,
                    "metadata": dict(document.metadata),
                },
            )
            for document in documents
        ]
        await self.client.upsert(
            collection_name=self.collection,
            points=points,
            wait=True,
        )

    @staticmethod
    def _filter(filters: Mapping[str, MetadataScalar]) -> models.Filter | None:
        if not filters:
            return None
        return models.Filter(
            must=[
                models.FieldCondition(
                    key=f"metadata.{name}",
                    match=models.MatchValue(value=value),
                )
                for name, value in filters.items()
            ]
        )

    async def search(
        self,
        query_vector: Sequence[float],
        *,
        limit: int = 5,
        filters: Mapping[str, MetadataScalar] | None = None,
    ) -> list[VectorSearchResult]:
        if limit <= 0:
            raise ValueError("search limit must be positive")
        query = _validate_dimensions(query_vector, self.dimensions)
        if not await self._collection_exists():
            return []
        response = await self.client.query_points(
            collection_name=self.collection,
            query=list(query),
            query_filter=self._filter(filters or {}),
            limit=limit,
            with_payload=True,
        )
        results: list[VectorSearchResult] = []
        for point in response.points:
            payload = point.payload or {}
            metadata = payload.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            results.append(
                VectorSearchResult(
                    id=str(payload.get("document_id", point.id)),
                    content=str(payload.get("content", "")),
                    metadata=metadata,
                    score=float(point.score),
                )
            )
        return results

    async def delete(self, document_ids: Sequence[str]) -> None:
        if not document_ids or not await self._collection_exists():
            return
        await self.client.delete(
            collection_name=self.collection,
            points_selector=models.PointIdsList(
                points=[self._point_id(document_id) for document_id in document_ids]
            ),
            wait=True,
        )

    async def count(self) -> int:
        if not await self._collection_exists():
            return 0
        result = await self.client.count(collection_name=self.collection, exact=True)
        return int(result.count)

    async def health(self) -> bool:
        try:
            return await self._collection_exists()
        except ApiException:
            return False


async def vector_documents_from_chunks(
    chunks: Sequence[KnowledgeChunk],
    embeddings: EmbeddingService,
) -> list[VectorDocument]:
    """Embed chunk content and preserve every field needed by later retrieval."""

    vectors = await embeddings.embed_documents([chunk.content for chunk in chunks])
    if len(vectors) != len(chunks):
        raise ValueError("embedding provider returned the wrong number of vectors")
    return [
        VectorDocument(
            id=chunk.id,
            content=chunk.content,
            vector=vector,
            metadata={
                "article_slug": chunk.article_slug,
                "title": chunk.title,
                "category": chunk.category.value,
                "tags": list(chunk.tags),
                "heading": chunk.heading,
                "source": chunk.source,
                "section_index": chunk.section_index,
                "window_index": chunk.window_index,
            },
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]


async def recreate_vector_store(
    settings: Settings | None = None,
    *,
    qdrant_client: AsyncQdrantClient | None = None,
) -> VectorStoreService:
    """Return an empty configured store, deleting the Qdrant collection when present."""

    active_settings = settings or get_settings()
    store = get_vector_store(active_settings, qdrant_client=qdrant_client)
    if isinstance(store, QdrantVectorStore) and await store.client.collection_exists(
        store.collection
    ):
        await store.client.delete_collection(store.collection)
    return store


async def close_vector_store(store: VectorStoreService) -> None:
    """Release provider resources without exposing concrete stores to callers."""

    if isinstance(store, QdrantVectorStore):
        await store.client.close()


def get_vector_store(
    settings: Settings | None = None,
    *,
    qdrant_client: AsyncQdrantClient | None = None,
) -> VectorStoreService:
    """Select a store from settings without exposing infrastructure downstream."""

    active_settings = settings or get_settings()
    provider = active_settings.vector_store.casefold()
    if provider == "memory":
        return InMemoryVectorStore(active_settings.embedding_dimensions)
    if provider == "qdrant":
        api_key = (
            active_settings.qdrant_api_key.get_secret_value()
            if active_settings.qdrant_api_key
            else None
        )
        return QdrantVectorStore(
            dimensions=active_settings.embedding_dimensions,
            collection=active_settings.qdrant_collection,
            url=active_settings.qdrant_url,
            api_key=api_key,
            client=qdrant_client,
        )
    raise VectorStoreConfigurationError(f"Unsupported vector store: {active_settings.vector_store}")
