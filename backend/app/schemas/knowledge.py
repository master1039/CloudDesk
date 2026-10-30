"""Transport schemas for knowledge browsing, retrieval, and reindexing (F5)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.common import TicketCategory
from app.schemas.tickets import PaginatedResponse
from pydantic import BaseModel, ConfigDict, Field

RetrievalModeValue = Literal["hybrid", "semantic", "keyword"]


class KnowledgeArticleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    title: str
    category: TicketCategory
    tags: list[str]
    summary: str
    updated_at: datetime


class KnowledgeArticleResponse(KnowledgeArticleSummary):
    body: str


class KnowledgeListParams(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: TicketCategory | None = None
    search: str | None = Field(default=None, min_length=1, max_length=200)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=2_000)
    category: TicketCategory | None = None
    mode: RetrievalModeValue = "hybrid"
    top_k: int = Field(default=5, ge=1, le=20)


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    source: str
    snippet: str
    score: float
    url: str
    article_id: str


class KnowledgeSearchResponse(BaseModel):
    items: list[EvidenceResponse]


class ReindexRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    embedding_provider: str | None = Field(default=None, min_length=1, max_length=100)
    embedding_model: str | None = Field(default=None, min_length=1, max_length=200)


class ReindexJob(BaseModel):
    id: str
    status: Literal["completed"]
    collection: str
    article_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    indexed_count: int = Field(ge=0)
    created_at: datetime


KnowledgeListResponse = PaginatedResponse[KnowledgeArticleSummary]
