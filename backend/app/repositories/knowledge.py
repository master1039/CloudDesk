"""Support-knowledge and service-incident persistence."""

from __future__ import annotations

from collections.abc import Sequence

from app.models import Incident, SupportArticle
from app.schemas.common import IncidentStatus, Severity, TicketCategory
from sqlalchemy import select

from .base import BaseRepository


class SupportArticleRepository(BaseRepository[SupportArticle]):
    model = SupportArticle

    async def get_by_slug(self, slug: str) -> SupportArticle | None:
        return await self.session.scalar(select(SupportArticle).where(SupportArticle.slug == slug))

    async def list_published(
        self, *, category: TicketCategory | None = None
    ) -> Sequence[SupportArticle]:
        statement = select(SupportArticle).where(SupportArticle.is_published.is_(True))
        if category is not None:
            statement = statement.where(SupportArticle.category == category)
        statement = statement.order_by(SupportArticle.title, SupportArticle.id)
        return (await self.session.scalars(statement)).all()


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
