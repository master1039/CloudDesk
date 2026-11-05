"""P8-2 tests for scrubbed and de-duplicated durable customer memory (F4/F11/N7)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from app.core.database import Base, build_engine, build_session_factory, create_tables
from app.models import Customer, CustomerMemory, Ticket, WorkflowRun
from app.schemas.common import Channel, MemoryType, WorkflowStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from memory.long_term import MAX_RECALLED_NOTES, LongTermMemory


@pytest.fixture
async def memory_database() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_tables(engine)
    factory = build_session_factory(engine)
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def _seed_sources(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[str, str, str, str, str]:
    async with factory.begin() as session:
        first = Customer(name="First Customer", email="first@example.test")
        second = Customer(name="Second Customer", email="second@example.test")
        first_ticket = Ticket(
            display_id="CD-MEM-1",
            customer=first,
            subject="First issue",
            body="Customer-controlled body",
            channel=Channel.WEB,
        )
        second_ticket = Ticket(
            display_id="CD-MEM-2",
            customer=second,
            subject="Second issue",
            body="Other customer body",
            channel=Channel.WEB,
        )
        workflow = WorkflowRun(
            ticket=first_ticket,
            thread_id="memory-thread",
            status=WorkflowStatus.COMPLETED,
        )
        session.add_all((first, second, first_ticket, second_ticket, workflow))
        await session.flush()
        return first.id, second.id, first_ticket.id, second_ticket.id, workflow.id


async def test_n7_store_scrubs_secrets_and_keeps_only_safe_projection(
    memory_database: async_sessionmaker[AsyncSession],
) -> None:
    customer_id, _, ticket_id, _, workflow_id = await _seed_sources(memory_database)

    async with memory_database.begin() as session:
        note = await LongTermMemory(session).store(
            customer_id,
            MemoryType.PAST_ISSUE,
            "Resolved billing issue; password=correct-horse-battery-staple",
            source_ticket_id=ticket_id,
            source_workflow_id=workflow_id,
        )
        stored = await session.get(CustomerMemory, note.id)

        assert stored is not None
        assert note.content == "Resolved billing issue; password=[REDACTED]"
        assert stored.content == note.content
        assert stored.fingerprint not in note.content
        assert stored.attributes == {}
        assert not hasattr(note, "fingerprint")
        assert not hasattr(note, "attributes")


async def test_exact_duplicates_are_skipped_but_types_and_customers_remain_isolated(
    memory_database: async_sessionmaker[AsyncSession],
) -> None:
    first_id, second_id, *_ = await _seed_sources(memory_database)

    async with memory_database.begin() as session:
        memory = LongTermMemory(session)
        first = await memory.store(first_id, "note", "Prefers email")
        duplicate = await memory.store(first_id, "note", "Prefers email")
        other_type = await memory.store(first_id, "preference", "Prefers email")
        other_customer = await memory.store(second_id, "note", "Prefers email")

        assert duplicate.id == first.id
        assert len({first.id, other_type.id, other_customer.id}) == 3
        count = await session.scalar(select(func.count()).select_from(CustomerMemory))
        assert count == 3


async def test_recall_returns_at_most_ten_newest_notes_and_filters_by_type(
    memory_database: async_sessionmaker[AsyncSession],
) -> None:
    customer_id, *_ = await _seed_sources(memory_database)

    async with memory_database.begin() as session:
        memory = LongTermMemory(session)
        for index in range(12):
            memory_type = MemoryType.PREFERENCE if index % 2 == 0 else MemoryType.NOTE
            await memory.store(customer_id, memory_type, f"Memory {index:02d}")

        newest = await memory.recall(customer_id)
        preferences = await memory.recall(customer_id, memory_type="preference", limit=3)

        assert len(newest) == MAX_RECALLED_NOTES
        assert [note.content for note in newest[:2]] == ["Memory 11", "Memory 10"]
        assert len(preferences) == 3
        assert all(note.memory_type is MemoryType.PREFERENCE for note in preferences)


async def test_cross_customer_sources_and_mismatched_workflow_are_rejected(
    memory_database: async_sessionmaker[AsyncSession],
) -> None:
    first_id, second_id, first_ticket_id, second_ticket_id, workflow_id = await _seed_sources(
        memory_database
    )

    async with memory_database.begin() as session:
        memory = LongTermMemory(session)
        with pytest.raises(ValueError, match="source ticket"):
            await memory.store(first_id, "note", "unsafe link", source_ticket_id=second_ticket_id)
        with pytest.raises(ValueError, match="source workflow"):
            await memory.store(second_id, "note", "unsafe link", source_workflow_id=workflow_id)
        with pytest.raises(ValueError, match="source workflow"):
            await memory.store(
                second_id,
                "note",
                "unsafe link",
                source_ticket_id=second_ticket_id,
                source_workflow_id=workflow_id,
            )

        assert first_ticket_id != second_ticket_id
        assert await session.scalar(select(func.count()).select_from(CustomerMemory)) == 0


async def test_raw_source_ticket_body_is_rejected(
    memory_database: async_sessionmaker[AsyncSession],
) -> None:
    customer_id, _, ticket_id, _, _ = await _seed_sources(memory_database)

    async with memory_database.begin() as session:
        memory = LongTermMemory(session)
        with pytest.raises(ValueError, match="raw ticket bodies"):
            await memory.store(
                customer_id,
                "past_issue",
                "Customer-controlled body",
                source_ticket_id=ticket_id,
            )

        assert await session.scalar(select(func.count()).select_from(CustomerMemory)) == 0


async def test_invalid_content_type_customer_and_recall_bounds_fail_before_persistence(
    memory_database: async_sessionmaker[AsyncSession],
) -> None:
    customer_id, *_ = await _seed_sources(memory_database)

    async with memory_database.begin() as session:
        memory = LongTermMemory(session)
        with pytest.raises(ValueError, match="must not be blank"):
            await memory.store(customer_id, "note", "   ")
        with pytest.raises(ValueError, match="unsupported memory type"):
            await memory.store(customer_id, "unsupported", "value")
        with pytest.raises(ValueError, match="customer does not exist"):
            await memory.store("00000000-0000-0000-0000-000000000000", "note", "value")
        with pytest.raises(ValueError, match="limit"):
            await memory.recall(customer_id, limit=11)

        assert await session.scalar(select(func.count()).select_from(CustomerMemory)) == 0
