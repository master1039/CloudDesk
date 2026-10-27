"""Shared SQLAlchemy metadata and asynchronous session lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from app.core.config import get_settings
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all CloudDesk ORM entities."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def build_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Build an async engine without opening a database connection."""

    return create_async_engine(database_url, echo=echo, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build sessions that retain loaded values after transaction commits."""

    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Return the process-wide engine configured from application settings."""

    return build_engine(get_settings().database_url)


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide asynchronous session factory."""

    return build_session_factory(get_engine())


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped session; callers own commit and rollback."""

    async with get_session_factory()() as session:
        yield session


async def create_tables(engine: AsyncEngine | None = None) -> None:
    """Create registered ORM tables for the offline SQLite demo."""

    import app.models  # noqa: F401 -- registers entities on Base.metadata

    target = engine or get_engine()
    async with target.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def dispose_database() -> None:
    """Dispose the cached engine and reset database factories."""

    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
