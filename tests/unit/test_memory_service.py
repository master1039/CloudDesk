"""P8-3 tests for customer recall and bounded resolution recording (F4/F11/N7)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from app.core.database import Base, build_engine, build_session_factory, create_tables
from app.models import Customer, CustomerMemory, Ticket, WorkflowRun
from app.schemas.common import Channel, MemoryType, WorkflowStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from memory.memory_service import MemoryService, recall_customer, record_resolution


@pytest.fixture
async def service_database() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_tables(engine)
    factory = build_session_factory(engine)
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def _seed_run(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[str, str, str]:
    async with factory.begin() as session:
        customer = Customer(name="Memory Customer", email="memory@example.test")
        ticket = Ticket(
            display_id="CD-MEMORY-SERVICE",
            customer=customer,
            subject="Cannot access workspace",
            body="This raw ticket body must never become a memory note.",
            channel=Channel.WEB,
        )
        workflow = WorkflowRun(
            ticket=ticket,
            thread_id="memory-service-thread",
            status=WorkflowStatus.COMPLETED,
        )
        session.add_all((customer, ticket, workflow))
        await session.flush()
        return customer.id, ticket.id, workflow.id


async def test_f11_record_resolution_writes_three_bounded_scrubbed_note_groups(
    service_database: async_sessionmaker[AsyncSession],
) -> None:
    customer_id, ticket_id, workflow_id = await _seed_run(service_database)

    async with service_database.begin() as session:
        result = await MemoryService(session).record_resolution(
            customer_id,
            source_ticket_id=ticket_id,
            source_workflow_id=workflow_id,
            past_issue="Workspace access failed after an SSO change.",
            troubleshooting_steps=[
                "Verified the SSO configuration.",
                "Refreshed identity-provider metadata.",
                "Retried the login flow.",
                "This fourth step must not be stored.",
            ],
            resolution_note="Access restored; password=correct-horse-battery-staple",
        )

        assert [note.memory_type for note in result.notes] == [
            MemoryType.PAST_ISSUE,
            MemoryType.TROUBLESHOOTING,
            MemoryType.NOTE,
        ]
        assert result.troubleshooting.content == (
            "1. Verified the SSO configuration.\n"
            "2. Refreshed identity-provider metadata.\n"
            "3. Retried the login flow."
        )
        assert "fourth" not in result.troubleshooting.content.casefold()
        assert result.resolution.content == "Access restored; password=[REDACTED]"
        assert all(note.source_ticket_id == ticket_id for note in result.notes)
        assert all(note.source_workflow_id == workflow_id for note in result.notes)


async def test_repeated_resolution_recording_is_idempotent(
    service_database: async_sessionmaker[AsyncSession],
) -> None:
    customer_id, ticket_id, workflow_id = await _seed_run(service_database)
    values = {
        "source_ticket_id": ticket_id,
        "source_workflow_id": workflow_id,
        "past_issue": "An earlier workspace login failed.",
        "troubleshooting_steps": ["Checked SSO.", "Refreshed metadata."],
        "resolution_note": "Workspace access was restored.",
    }

    async with service_database.begin() as session:
        service = MemoryService(session)
        first = await service.record_resolution(customer_id, **values)
        second = await service.record_resolution(customer_id, **values)

        assert [note.id for note in second.notes] == [note.id for note in first.notes]
        assert await session.scalar(select(func.count()).select_from(CustomerMemory)) == 3


async def test_f4_recall_customer_returns_at_most_ten_safe_newest_notes(
    service_database: async_sessionmaker[AsyncSession],
) -> None:
    customer_id, ticket_id, workflow_id = await _seed_run(service_database)

    async with service_database.begin() as session:
        service = MemoryService(session)
        for index in range(4):
            await service.record_resolution(
                customer_id,
                source_ticket_id=ticket_id,
                source_workflow_id=workflow_id,
                past_issue=f"Past issue {index:02d}",
                troubleshooting_steps=[f"Troubleshooting {index:02d}"],
                resolution_note=f"Resolution {index:02d}",
            )

        notes = await recall_customer(session, customer_id)

        assert len(notes) == 10
        assert [note.content for note in notes[:2]] == [
            "Resolution 03",
            "1. Troubleshooting 03",
        ]
        assert all(not hasattr(note, "fingerprint") for note in notes)
        assert all(not hasattr(note, "attributes") for note in notes)


async def test_record_resolution_rolls_back_all_new_notes_when_one_input_is_invalid(
    service_database: async_sessionmaker[AsyncSession],
) -> None:
    customer_id, ticket_id, workflow_id = await _seed_run(service_database)

    async with service_database.begin() as session:
        with pytest.raises(ValueError, match="must not be blank"):
            await record_resolution(
                session,
                customer_id,
                source_ticket_id=ticket_id,
                source_workflow_id=workflow_id,
                past_issue="Valid past issue",
                troubleshooting_steps=["Valid troubleshooting step"],
                resolution_note="   ",
            )

        assert await session.scalar(select(func.count()).select_from(CustomerMemory)) == 0


@pytest.mark.parametrize("steps", [[], ["", "  "], "not-a-sequence-of-steps"])
async def test_record_resolution_requires_structured_non_blank_troubleshooting_steps(
    service_database: async_sessionmaker[AsyncSession],
    steps: list[str] | str,
) -> None:
    customer_id, ticket_id, workflow_id = await _seed_run(service_database)

    async with service_database.begin() as session:
        with pytest.raises((TypeError, ValueError), match="troubleshooting"):
            await MemoryService(session).record_resolution(
                customer_id,
                source_ticket_id=ticket_id,
                source_workflow_id=workflow_id,
                past_issue="Valid past issue",
                troubleshooting_steps=steps,
                resolution_note="Valid resolution",
            )

        assert await session.scalar(select(func.count()).select_from(CustomerMemory)) == 0
