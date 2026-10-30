"""Knowledge loading and retrieval components for CloudDesk RAG."""

from .chunking import (
    CHUNK_OVERLAP_CHARS,
    MAX_CHUNK_CHARS,
    KnowledgeArticle,
    KnowledgeArticleError,
    KnowledgeChunk,
    chunk_article,
    chunk_articles,
    load_article_file,
    load_article_files,
)
from .embeddings import (
    EmbeddingConfigurationError,
    EmbeddingService,
    FakeEmbeddings,
    get_embedding_service,
)
from .vector_store import (
    InMemoryVectorStore,
    QdrantVectorStore,
    VectorDocument,
    VectorSearchResult,
    VectorStoreConfigurationError,
    VectorStoreService,
    get_vector_store,
    vector_documents_from_chunks,
)

__all__ = [
    "CHUNK_OVERLAP_CHARS",
    "MAX_CHUNK_CHARS",
    "EmbeddingConfigurationError",
    "EmbeddingService",
    "FakeEmbeddings",
    "InMemoryVectorStore",
    "KnowledgeArticle",
    "KnowledgeArticleError",
    "KnowledgeChunk",
    "QdrantVectorStore",
    "VectorDocument",
    "VectorSearchResult",
    "VectorStoreConfigurationError",
    "VectorStoreService",
    "chunk_article",
    "chunk_articles",
    "get_embedding_service",
    "get_vector_store",
    "load_article_file",
    "load_article_files",
    "vector_documents_from_chunks",
]

