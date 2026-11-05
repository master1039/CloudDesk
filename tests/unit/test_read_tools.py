"""P6-2 offline tests for bounded read-only support capabilities (F4/F5)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from app.core.config import Settings
from app.core.database import build_engine, build_session_factory, create_tables
from app.repositories import CustomerRepository, TicketRepository
from app.services.knowledge_service import KnowledgeRuntime
from app.services.seed_service import bootstrap_demo_data
from app.tools import (
    ServiceStatusProvider,
    ToolErrorCode,
    ToolRegistry,
    create_read_tool_registry,
)
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"


class StubStatusProvider:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    async def check_service_status(self, service: str | None = None) -> Mapping[str, Any]:
        self.calls.append(service)
        return {"service": service or "all", "status": "maintenance", "incidents": []}


@pytest.fixture
async def read_tool_context(
    tmp_path: Path,
) -> AsyncIterator[
    tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
        Settings,
    ]
]:
    engine = build_engine(f"sqlite+aiosqlite:///{(tmp_path / 'read-tools.db').as_posix()}")
    await create_tables(engine)
    session_factory = build_session_factory(engine)
    async with session_factory.begin() as session:
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
        session_factory=session_factory,
        settings=settings,
        cache=cache,
        knowledge_runtime=runtime,
    )
    try:
        yield registry, session_factory, runtime, cache, settings
    finally:
        await runtime.close()
        await cache.aclose()
        await engine.dispose()


async def _customer_id(
    session_factory: async_sessionmaker[AsyncSession],
    external_ref: str = "cust-acme",
) -> str:
    async with session_factory() as session:
        customer = await CustomerRepository(session).get_by_external_ref(external_ref)
    assert customer is not None
    return customer.id


async def test_registry_contains_exactly_the_five_read_only_policy_tools(
    read_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
        Settings,
    ],
) -> None:
    registry, _, _, _, _ = read_tool_context

    assert set(registry.tools) == {
        "get_customer",
        "get_subscription",
        "get_ticket_history",
        "search_docs",
        "check_service_status",
    }
    assert all(not registry.policy.requires_approval(name) for name in registry.tools)
    assert all(not registry.policy.writes(name) for name in registry.tools)


async def test_get_customer_returns_bounded_context_without_internal_attributes(
    read_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
        Settings,
    ],
) -> None:
    registry, session_factory, _, _, _ = read_tool_context
    customer_id = await _customer_id(session_factory)

    result = await registry.execute("get_customer", {"customer_id": customer_id})

    assert result.ok is True
    assert result.output["name"] == "Asha Rao"
    assert result.output["company"] == "Acme Analytics"
    assert result.output["workspace"]["slug"] == "acme-hq"
    assert result.output["workspace"]["storage_used_bytes"] == 480_000_000_000
    assert result.output["workspace"]["storage_limit_bytes"] == 1_000_000_000_000
    assert "attributes" not in result.output
    assert "phone" not in result.output
    assert "tickets" not in result.output


async def test_get_subscription_returns_safe_billing_projection(
    read_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
        Settings,
    ],
) -> None:
    registry, session_factory, _, _, _ = read_tool_context
    customer_id = await _customer_id(session_factory)

    result = await registry.execute("get_subscription", {"customer_id": customer_id})

    assert result.ok is True
    assert result.output["plan"] == "enterprise"
    assert result.output["status"] == "active"
    assert result.output["seats"] == 120
    assert isinstance(result.output["amount"], str)
    assert "attributes" not in result.output


async def test_get_ticket_history_is_bounded_and_never_returns_ticket_bodies(
    read_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
        Settings,
    ],
) -> None:
    registry, session_factory, _, _, _ = read_tool_context
    customer_id = await _customer_id(session_factory)
    async with session_factory() as session:
        current_ticket = await TicketRepository(session).get_by_display_id("CD-1012")
    assert current_ticket is not None

    result = await registry.execute(
        "get_ticket_history",
        {
            "customer_id": customer_id,
            "exclude_ticket_id": current_ticket.id,
            "limit": 2,
        },
    )

    assert result.ok is True
    assert len(result.output["items"]) == 2
    assert {item["display_id"] for item in result.output["items"]} <= {
        "CD-1001",
        "CD-1007",
    }
    assert all(item["id"] != current_ticket.id for item in result.output["items"])
    assert all("body" not in item and "messages" not in item for item in result.output["items"])


async def test_search_docs_returns_deduplicated_structured_citations(
    read_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
        Settings,
    ],
) -> None:
    registry, _, _, _, _ = read_tool_context

    result = await registry.execute(
        "search_docs",
        {
            "query": "HTTP 429 Retry-After exponential backoff",
            "category": "api_failure",
            "mode": "hybrid",
            "top_k": 3,
        },
    )

    assert result.ok is True
    items = result.output["items"]
    assert items[0]["article_id"] == "api-rate-limits"
    assert items[0]["source"].startswith("kb://api-rate-limits#")
    assert items[0]["url"] == "/knowledge/api-rate-limits"
    assert len({item["article_id"] for item in items}) == len(items)


async def test_repository_service_status_reports_degraded_and_operational_services(
    read_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
        Settings,
    ],
) -> None:
    registry, _, _, _, _ = read_tool_context

    degraded = await registry.execute("check_service_status", {"service": "sso"})
    operational = await registry.execute("check_service_status", {"service": "billing"})

    assert degraded.ok is True
    assert degraded.output["status"] == "degraded"
    assert degraded.output["incidents"][0]["severity"] == "high"
    assert "sso" in degraded.output["incidents"][0]["affected_services"]
    assert operational.output == {
        "service": "billing",
        "status": "operational",
        "incidents": [],
    }


async def test_missing_customer_and_subscription_are_safe_not_found_results(
    read_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
        Settings,
    ],
) -> None:
    registry, _, _, _, _ = read_tool_context
    missing_id = "00000000-0000-0000-0000-000000000000"

    customer = await registry.execute("get_customer", {"customer_id": missing_id})
    subscription = await registry.execute("get_subscription", {"customer_id": missing_id})

    assert customer.ok is subscription.ok is True
    assert customer.output == {"found": False, "customer_id": missing_id}
    assert subscription.output == {"found": False, "customer_id": missing_id}


async def test_tool_input_bounds_fail_as_structured_registry_results(
    read_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
        Settings,
    ],
) -> None:
    registry, session_factory, _, _, _ = read_tool_context
    customer_id = await _customer_id(session_factory)

    result = await registry.execute(
        "get_ticket_history",
        {"customer_id": customer_id, "limit": 11},
    )

    assert result.ok is False
    assert result.error_code is ToolErrorCode.EXECUTION_ERROR
    assert result.error == "ValidationError: Tool execution failed"


async def test_service_status_provider_is_dependency_injected_for_p6_4(
    read_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        KnowledgeRuntime,
        FakeRedis,
        Settings,
    ],
) -> None:
    _, session_factory, runtime, cache, settings = read_tool_context
    provider = StubStatusProvider()
    assert isinstance(provider, ServiceStatusProvider)
    registry = create_read_tool_registry(
        session_factory=session_factory,
        settings=settings,
        cache=cache,
        knowledge_runtime=runtime,
        status_provider=provider,
    )

    result = await registry.execute("check_service_status", {"service": "files"})

    assert result.ok is True
    assert result.output["status"] == "maintenance"
    assert provider.calls == ["files"]
