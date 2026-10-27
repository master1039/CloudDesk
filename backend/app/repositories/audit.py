"""Append and inspect audit records."""

from __future__ import annotations

from collections.abc import Sequence

from app.models import AuditLog
from sqlalchemy import select

from .base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def list_for_request(self, request_id: str) -> Sequence[AuditLog]:
        statement = (
            select(AuditLog)
            .where(AuditLog.request_id == request_id)
            .order_by(AuditLog.created_at, AuditLog.id)
        )
        return (await self.session.scalars(statement)).all()

    async def list_for_actor(
        self, actor_id: str, *, offset: int = 0, limit: int = 100
    ) -> Sequence[AuditLog]:
        statement = (
            select(AuditLog)
            .where(AuditLog.actor_id == actor_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        )
        statement = self._page(statement, offset=offset, limit=limit)
        return (await self.session.scalars(statement)).all()
