"""Support-knowledge and service-incident persistence."""

from __future__ import annotations

from collections.abc import Sequence

from app.models import Incident, SupportArticle
from app.schemas.common import IncidentStatus, Severity, TicketCategory
from sqlalchemy import func, or_, select

from .base import BaseRepository


class SupportArticleRepository(BaseRepository[SupportArticle]):
    model = SupportArticle

    async def get_by_slug(self, slug: str) -> SupportArticle | None:
        return await self.session.scalar(select(SupportArticle).where(SupportArticle.slug == slug))

    async def get_published(self, article_id: str) -> SupportArticle | None:
        statement = select(SupportArticle).where(
            SupportArticle.is_published.is_(True),
            or_(SupportArticle.id == article_id, SupportArticle.slug == article_id),
        )
        return await self.session.scalar(statement)

    async def list_published(
        self,
        *,
        category: TicketCategory | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[SupportArticle]:
        statement = select(SupportArticle).where(SupportArticle.is_published.is_(True))
        if category is not None:
            statement = statement.where(SupportArticle.category == category)
        if search is not None:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    SupportArticle.title.ilike(pattern),
                    SupportArticle.summary.ilike(pattern),
                    SupportArticle.body.ilike(pattern),
                )
            )
        statement = statement.order_by(SupportArticle.title, SupportArticle.id)
        statement = self._page(statement, offset=offset, limit=limit)
        return (await self.session.scalars(statement)).all()

    async def count_published(
        self,
        *,
        category: TicketCategory | None = None,
        search: str | None = None,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(SupportArticle)
            .where(SupportArticle.is_published.is_(True))
        )
        if category is not None:
            statement = statement.where(SupportArticle.category == category)
        if search is not None:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    SupportArticle.title.ilike(pattern),
                    SupportArticle.summary.ilike(pattern),
                    SupportArticle.body.ilike(pattern),
                )
            )
        return int((await self.session.scalar(statement)) or 0)


class IncidentRepository(BaseRepository[Incident]):
    model = Incident

    async def list_active(
        self,
        *,
        product_id: str | None = None,
        severity: Severity | None = None,
    ) -> Sequence[Incident]:
        statement = select(Incident).where(Incident.status != IncidentStatus.RESOLVED)
        if product_id is not None:
            statement = statement.where(Incident.product_id == product_id)
        if severity is not None:
            statement = statement.where(Incident.severity == severity)
        statement = statement.order_by(Incident.started_at.desc(), Incident.id.desc())
        return (await self.session.scalars(statement)).all()
