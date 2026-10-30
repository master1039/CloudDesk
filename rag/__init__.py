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

__all__ = [
    "CHUNK_OVERLAP_CHARS",
    "MAX_CHUNK_CHARS",
    "KnowledgeArticle",
    "KnowledgeArticleError",
    "KnowledgeChunk",
    "chunk_article",
    "chunk_articles",
    "load_article_file",
    "load_article_files",
]

