"""P2-4 tests for the offline sample data and demo bootstrap."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.core.database import (
    Base,
    build_engine,
    build_session_factory,
    create_tables,
    dispose_database,
    get_session_factory,
)
from app.main import create_app
from app.models import Customer, CustomerMemory, SupportArticle, Ticket
from app.repositories import CustomerRepository, IncidentRepository, TicketRepository
from app.schemas.common import SubscriptionPlan
from app.services.seed_service import bootstrap_demo_data
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA = PROJECT_ROOT / "sample_data"


@pytest.fixture
async def demo_database() -> AsyncIterator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]]]:
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_tables(engine)
    factory = build_session_factory(engine)
    try:
        yield engine, factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_f1_f4_bootstrap_loads_locked_demo_scenarios_once(
    demo_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, factory = demo_database
    async with factory.begin() as session:
        first = await bootstrap_demo_data(session, SAMPLE_DATA)
    async with factory.begin() as session:
        second = await bootstrap_demo_data(session, SAMPLE_DATA)

    assert first.seeded is True
    assert (first.profiles, first.customers, first.tickets, first.articles) == (3, 8, 13, 15)
    assert second.seeded is False
    assert second == type(second)(False, 3, 8, 13, 15)

    async with factory() as session:
        ticket_repository = TicketRepository(session)
        refund = await ticket_repository.get_by_display_id("CD-1002")
        injection = await ticket_repository.get_by_display_id("CD-1013")
        assert refund is not None
        assert refund.attributes["requested_refund_seats"] == 3
        assert injection is not None
        assert injection.injection_detected is True

        context = await CustomerRepository(session).get_with_context(refund.customer_id)
        assert context is not None
        assert context.subscription is not None
        assert context.subscription.plan is SubscriptionPlan.PRO
        assert [workspace.slug for workspace in context.workspaces] == ["orbit-creative"]

        incidents = await IncidentRepository(session).list_active()
        assert {incident.title for incident in incidents} == {
            "Enterprise SSO authentication degradation",
            "Delayed Slack event delivery",
        }

        assert await session.scalar(select(func.count()).select_from(CustomerMemory)) == 4
        assert await session.scalar(select(func.count()).select_from(SupportArticle)) == 15


async def test_lifespan_creates_parent_directory_and_seeds_demo_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "nested" / "support.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("SAMPLE_DATA_DIR", SAMPLE_DATA.as_posix())
    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    await dispose_database()

    app = create_app()
    async with app.router.lifespan_context(app), get_session_factory()() as session:
        assert await session.scalar(select(func.count()).select_from(Customer)) == 8
        assert await session.scalar(select(func.count()).select_from(Ticket)) == 13

    assert database_path.is_file()


def test_sample_files_cover_the_locked_dataset() -> None:
    tickets = json.loads((SAMPLE_DATA / "tickets.json").read_text(encoding="utf-8"))
    customers = json.loads((SAMPLE_DATA / "customers.json").read_text(encoding="utf-8"))
    articles = sorted((SAMPLE_DATA / "knowledge_base").glob("*.md"))

    assert len(customers) == 8
    assert [ticket["display_id"] for ticket in tickets] == [
        f"CD-{number}" for number in range(1001, 1014)
    ]
    assert len(articles) == 15
    for article in articles:
        text = article.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        for field in ("title:", "category:", "tags:", "summary:"):
            assert field in text


def test_make_seed_and_postgres_seed_file_are_present() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    sql = (PROJECT_ROOT / "database" / "seed.sql").read_text(encoding="utf-8")

    assert "\nseed:\n" in makefile
    assert "$(UV) run python backend/seed.py" in makefile
    assert "CD-1002" in sql
    assert "CD-1013" in sql
    assert "ON CONFLICT DO NOTHING" in sql
