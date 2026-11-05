"""Reusable SQLAlchemy repository primitives."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.core.database import Base
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository[ModelT: Base]:
    """CRUD helpers that flush changes but leave transactions to services."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def create(self, **values: Any) -> ModelT:
        return await self.add(self.model(**values))

    async def get(self, entity_id: str) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def list(self, *, offset: int = 0, limit: int = 100) -> Sequence[ModelT]:
        statement = self._page(select(self.model), offset=offset, limit=limit)
        return (await self.session.scalars(statement)).all()

    async def count(self) -> int:
        statement = select(func.count()).select_from(self.model)
        return int((await self.session.scalar(statement)) or 0)

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    @staticmethod
    def _page(statement: Select[Any], *, offset: int, limit: int) -> Select[Any]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        return statement.offset(offset).limit(limit)
