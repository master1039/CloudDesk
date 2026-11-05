"""P9-3 offline tests for deterministic, customer-isolated context assembly (F4/F14)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from app.core.config import Settings
from app.core.database import build_engine, build_session_factory, create_tables
from app.repositories import CustomerRepository, TicketRepository
from app.services.knowledge_service import KnowledgeRuntime
from app.services.seed_service import bootstrap_demo_data
from app.tools import ToolRegistry, create_read_tool_registry
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.specialists import CustomerAgent, CustomerAgentError, CustomerNotFoundError
from memory.long_term import LongTermMemoryNote
from memory.memory_service import MemoryService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"


@pytest.fixture
async def customer_agent_context(
    tmp_path: Path,
) -> AsyncIterator[
    tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
    ]
]:
    engine = build_engine(f"sqlite+aiosqlite:///{(tmp_path / 'customer-agent.db').as_posix()}")
    await create_tables(engine)
    factory = build_session_factory(engine)
    async with factory.begin() as session:
        await bootstrap_demo_data(session, SAMPLE_DATA_DIR)
    runtime = KnowledgeRuntime()
    cache = FakeRedis(decode_responses=True)
    settings = Settings(
        sample_data_dir=SAMPLE_DATA_DIR,
        vector_store="memory",
        embedding_provider="fake",
        embedding_dimensions=384,
    )
    registry = create_read_tool_registry(
        session_factory=factory,
        settings=settings,
        cache=cache,
        knowledge_runtime=runtime,
    )
    try:
        yield registry, factory, runtime, cache
    finally:
        await runtime.close()
        await cache.aclose()
        await engine.dispose()


async def _ids(
    factory: async_sessionmaker[AsyncSession],
    customer_ref: str,
    ticket_display_id: str,
) -> tuple[str, str]:
    async with factory() as session:
        customer = await CustomerRepository(session).get_by_external_ref(customer_ref)
        ticket = await TicketRepository(session).get_by_display_id(ticket_display_id)
    assert customer is not None
    assert ticket is not None
    return customer.id, ticket.id


async def test_f4_customer_agent_loads_complete_safe_context_without_an_llm(
    customer_agent_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
    ],
) -> None:
    registry, factory, _, _ = customer_agent_context
    customer_id, ticket_id = await _ids(factory, "cust-acme", "CD-1001")

    async with factory() as session:
        result = await CustomerAgent(registry, MemoryService(session)).run(
            customer_id,
            current_ticket_id=ticket_id,
        )

    assert result.output.customer.name == "Asha Rao"
    assert result.output.customer.company == "Acme Analytics"
    assert result.output.subscription is not None
    assert result.output.subscription.plan.value == "enterprise"
    assert result.output.workspace is not None
    assert result.output.workspace.slug == "acme-hq"
    assert result.output.workspace.storage_used_bytes == 480_000_000_000
    assert result.output.workspace.storage_limit_bytes == 1_000_000_000_000
    assert all(case.ticket_id != ticket_id for case in result.output.previous_tickets)
    assert result.output.memory_notes[0].content.startswith("A prior SSO failure")
    assert [call.name for call in result.tool_calls] == [
        "get_customer",
        "get_subscription",
        "get_ticket_history",
    ]
    assert all(call.ok for call in result.tool_calls)
    assert result.usage.total_tokens == 0
    assert result.estimated_cost == 0


async def test_customer_agent_does_not_mix_another_customers_context(
    customer_agent_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
    ],
) -> None:
    registry, factory, _, _ = customer_agent_context
    acme_id, acme_ticket_id = await _ids(factory, "cust-acme", "CD-1001")
    _, orbit_ticket_id = await _ids(factory, "cust-orbit", "CD-1002")

    async with factory() as session:
        acme = await CustomerAgent(registry, MemoryService(session)).run(
            acme_id,
            current_ticket_id=acme_ticket_id,
        )

    assert acme.output.customer.id == acme_id
    assert acme.output.subscription is not None
    assert all(note.content.find("quota") == -1 for note in acme.output.memory_notes)
    assert all(case.ticket_id != orbit_ticket_id for case in acme.output.previous_tickets)


async def test_customer_agent_fails_closed_on_cross_customer_memory() -> None:
    class WrongCustomerMemory:
        def __init__(self, note: LongTermMemoryNote) -> None:
            self.note = note

        async def recall_customer(
            self,
            customer_id: str,
            *,
            limit: int = 10,
        ) -> Sequence[LongTermMemoryNote]:
            return (replace(self.note, customer_id="another-customer"),)

    class StubRegistry:
        async def execute(self, name: str, args: dict) -> object:
            from app.tools import ToolResult

            customer_id = args["customer_id"]
            outputs = {
                "get_customer": {
                    "found": True,
                    "id": customer_id,
                    "name": "Customer",
                    "email": "customer@example.test",
                    "company": None,
                    "workspace": None,
                },
                "get_subscription": {"found": False, "customer_id": customer_id},
                "get_ticket_history": {"customer_id": customer_id, "items": []},
            }
            return ToolResult(name=name, ok=True, output=outputs[name])

    from datetime import UTC, datetime

    from app.schemas.common import MemoryType

    note = LongTermMemoryNote(
        id="note-1",
        customer_id="customer-1",
        memory_type=MemoryType.NOTE,
        content="Safe note",
        source_ticket_id=None,
        source_workflow_id=None,
        created_at=datetime.now(UTC),
    )
    with pytest.raises(CustomerAgentError, match="mismatched ownership"):
        await CustomerAgent(StubRegistry(), WrongCustomerMemory(note)).run("customer-1")  # type: ignore[arg-type]


async def test_customer_agent_returns_safe_not_found_error(
    customer_agent_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
    ],
) -> None:
    registry, factory, _, _ = customer_agent_context
    async with factory() as session:
        with pytest.raises(CustomerNotFoundError, match="not found"):
            await CustomerAgent(registry, MemoryService(session)).run(
                "00000000-0000-0000-0000-000000000000"
            )
