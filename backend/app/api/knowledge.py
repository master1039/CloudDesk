"""Protected knowledge browsing, search, and administrative reindex routes."""

from __future__ import annotations

from typing import Annotated

from app.core.database import get_session
from app.core.security import require_role
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import Role
from app.schemas.knowledge import (
    KnowledgeArticleResponse,
    KnowledgeListParams,
    KnowledgeListResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    ReindexJob,
    ReindexRequest,
)
from app.services.knowledge_service import KnowledgeArticleNotFoundError, KnowledgeService
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])
ViewerUser = Annotated[AuthenticatedUser, Depends(require_role(Role.VIEWER))]
AdminUser = Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN))]
DatabaseSession = Annotated[AsyncSession, Depends(get_session)]
KnowledgeQuery = Annotated[KnowledgeListParams, Query()]


@router.get("", response_model=KnowledgeListResponse)
async def list_knowledge(
    params: KnowledgeQuery,
    _: ViewerUser,
    session: DatabaseSession,
) -> KnowledgeListResponse:
    """List published knowledge articles with filtering and pagination."""

    return await KnowledgeService(session).list_articles(params)


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    request: KnowledgeSearchRequest,
    _: ViewerUser,
    session: DatabaseSession,
) -> KnowledgeSearchResponse:
    """Return cited semantic, keyword, or hybrid evidence (F5)."""

    return await KnowledgeService(session).search(request)


@router.post(
    "/reindex",
    response_model=ReindexJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_knowledge(
    _: AdminUser,
    session: DatabaseSession,
    request: Annotated[ReindexRequest | None, Body()] = None,
) -> ReindexJob:
    """Recreate and repopulate the configured vector collection as an administrator."""

    try:
        return await KnowledgeService(session).reindex(request or ReindexRequest())
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error


@router.get("/{article_id}", response_model=KnowledgeArticleResponse)
async def get_knowledge_article(
    article_id: str,
    _: ViewerUser,
    session: DatabaseSession,
) -> KnowledgeArticleResponse:
    """Return one published knowledge article by UUID or stable slug."""

    try:
        return await KnowledgeService(session).get_article(article_id)
    except KnowledgeArticleNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge article not found",
        ) from error
