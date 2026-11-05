"""Build the CloudDesk knowledge index and expose the ``make ingest`` entrypoint."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.config import Settings, get_settings

from .chunking import KnowledgeArticle, KnowledgeChunk, chunk_articles, load_article_files
from .embeddings import EmbeddingService, get_embedding_service
from .retriever import EvidenceReranker, HybridRetriever, RetrievalCache
from .vector_store import (
    VectorDocument,
    VectorStoreService,
    close_vector_store,
    get_vector_store,
    recreate_vector_store,
    vector_documents_from_chunks,
)


@dataclass(frozen=True, slots=True)
class IngestReport:
    """Counts and configuration reported by CLI and reindex operations."""

    article_count: int
    chunk_count: int
    indexed_count: int
    collection: str
    embedding_provider: str
    embedding_model: str


@dataclass(frozen=True, slots=True)
class KnowledgeIndex:
    """One complete in-process view of indexed knowledge and retrieval services."""

    articles: tuple[KnowledgeArticle, ...]
    chunks: tuple[KnowledgeChunk, ...]
    documents: tuple[VectorDocument, ...]
    vector_store: VectorStoreService
    retriever: HybridRetriever
    report: IngestReport


async def build_knowledge_index(
    article_directory: str | Path,
    *,
    settings: Settings,
    embeddings: EmbeddingService,
    vector_store: VectorStoreService,
    cache: RetrievalCache | None = None,
    reranker: EvidenceReranker | None = None,
) -> KnowledgeIndex:
    """Load, chunk, embed, index, and wire retrieval for one article directory."""

    articles = load_article_files(article_directory)
    chunks = chunk_articles(articles)
    documents = await vector_documents_from_chunks(chunks, embeddings)
    await vector_store.add_documents(documents)
    indexed_count = await vector_store.count()
    report = IngestReport(
        article_count=len(articles),
        chunk_count=len(chunks),
        indexed_count=indexed_count,
        collection=settings.qdrant_collection,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
    )
    return KnowledgeIndex(
        articles=tuple(articles),
        chunks=tuple(chunks),
        documents=tuple(documents),
        vector_store=vector_store,
        retriever=HybridRetriever(
            documents,
            embeddings=embeddings,
            vector_store=vector_store,
            cache=cache,
            reranker=reranker,
        ),
        report=report,
    )


async def ingest_from_settings(
    settings: Settings | None = None,
    *,
    recreate: bool = False,
    cache: RetrievalCache | None = None,
    reranker: EvidenceReranker | None = None,
) -> KnowledgeIndex:
    """Create a configured index; reindex callers receive a newly recreated store."""

    active_settings = settings or get_settings()
    embeddings = get_embedding_service(active_settings)
    vector_store = (
        await recreate_vector_store(active_settings)
        if recreate
        else get_vector_store(active_settings)
    )
    try:
        return await build_knowledge_index(
            active_settings.sample_data_dir / "knowledge_base",
            settings=active_settings,
            embeddings=embeddings,
            vector_store=vector_store,
            cache=cache,
            reranker=reranker,
        )
    except BaseException:
        await close_vector_store(vector_store)
        raise


async def _run_cli() -> None:
    index = await ingest_from_settings(recreate=True)
    try:
        print(json.dumps(asdict(index.report), sort_keys=True))
    finally:
        await close_vector_store(index.vector_store)


def main() -> None:
    """Run knowledge ingestion and print machine-readable article/chunk counts."""

    asyncio.run(_run_cli())


if __name__ == "__main__":
    main()
