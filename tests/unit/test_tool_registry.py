"""P6-1 policy and registry tests for the F9 approval boundary."""

from __future__ import annotations

import asyncio

import pytest
from app.core.config import Settings
from app.tools import ToolErrorCode, ToolPolicy, ToolRegistry
from langchain_core.tools import tool


@pytest.mark.parametrize(
    "name",
    [
        "get_customer",
        "get_subscription",
        "get_ticket_history",
        "search_docs",
        "check_service_status",
        "update_ticket",
        "create_escalation",
    ],
)
def test_f9_safe_and_read_only_tools_do_not_require_approval(name: str) -> None:
    assert ToolPolicy().requires_approval(name) is False


@pytest.mark.parametrize("name", ["reset_demo_setting", "create_refund_request"])
def test_f9_consequential_tools_require_approval(name: str) -> None:
    policy = ToolPolicy()

    assert policy.requires_approval(name) is True
    assert policy.writes(name) is True


def test_unknown_tools_receive_the_conservative_policy() -> None:
    policy = ToolPolicy()
    rule = policy.rule_for("model_invented_tool")

    assert rule.known is False
    assert rule.writes is True
    assert rule.requires_approval is True


async def test_safe_tool_executes_without_approval_and_returns_a_structured_result() -> None:
    @tool("search_docs")
    async def search_docs(query: str) -> dict[str, str]:
        """Search support documentation."""

        return {"query": query, "article": "mfa-recovery"}

    registry = ToolRegistry([search_docs])

    result = await registry.execute("search_docs", {"query": "MFA lockout"})

    assert result.ok is True
    assert result.output == {"query": "MFA lockout", "article": "mfa-recovery"}
    assert result.error is None
    assert result.error_code is None
    assert result.approval_required is False
    assert result.duration_ms >= 0


async def test_update_ticket_is_the_only_routine_write_that_runs_without_approval() -> None:
    calls: list[str] = []

    @tool("update_ticket")
    async def update_ticket(status: str) -> dict[str, str]:
        """Update routine support ticket fields."""

        calls.append(status)
        return {"status": status}

    registry = ToolRegistry([update_ticket])

    result = await registry.execute("update_ticket", {"status": "in_progress"})

    assert result.ok is True
    assert calls == ["in_progress"]


async def test_refund_is_blocked_before_execution_without_recorded_approval() -> None:
    calls = 0

    @tool("create_refund_request")
    async def create_refund_request(amount: float) -> dict[str, float]:
        """Create a demo refund request."""

        nonlocal calls
        calls += 1
        return {"amount": amount}

    registry = ToolRegistry([create_refund_request])

    blocked = await registry.execute("create_refund_request", {"amount": 25.0})
    executed = await registry.execute(
        "create_refund_request",
        {"amount": 25.0},
        approved=True,
    )

    assert blocked.ok is False
    assert blocked.error_code is ToolErrorCode.APPROVAL_REQUIRED
    assert blocked.approval_required is True
    assert calls == 1
    assert executed.ok is True
    assert executed.output == {"amount": 25.0}
    assert executed.approval_required is True


async def test_registered_unclassified_extension_still_requires_approval() -> None:
    calls = 0

    @tool("future_capability")
    async def future_capability() -> str:
        """Represent a future capability without a policy classification."""

        nonlocal calls
        calls += 1
        return "executed"

    registry = ToolRegistry([future_capability])

    blocked = await registry.execute("future_capability")
    approved = await registry.execute("future_capability", approved=True)

    assert blocked.error_code is ToolErrorCode.APPROVAL_REQUIRED
    assert approved.ok is True
    assert calls == 1


async def test_unregistered_tool_never_executes_even_when_approved() -> None:
    registry = ToolRegistry()

    result = await registry.execute("invented_delete_everything", approved=True)

    assert result.ok is False
    assert result.error_code is ToolErrorCode.UNKNOWN_TOOL
    assert result.approval_required is True


async def test_tool_exception_becomes_failed_result_and_never_escapes() -> None:
    @tool("check_service_status")
    async def check_service_status() -> str:
        """Check a service and simulate an adapter failure."""

        raise RuntimeError("demo adapter unavailable")

    registry = ToolRegistry([check_service_status])

    result = await registry.execute("check_service_status")

    assert result.ok is False
    assert result.error_code is ToolErrorCode.EXECUTION_ERROR
    assert result.error == "RuntimeError: Tool execution failed"
    assert "demo adapter unavailable" not in result.error


async def test_timeout_uses_tool_timeout_seconds_and_cancels_the_call() -> None:
    cancelled = asyncio.Event()

    @tool("search_docs")
    async def search_docs(query: str) -> str:
        """Simulate a slow documentation search."""

        try:
            await asyncio.sleep(1)
        finally:
            cancelled.set()
        return query

    registry = ToolRegistry(
        [search_docs],
        settings=Settings(tool_timeout_seconds=0.01),
    )

    result = await registry.execute("search_docs", {"query": "slow"})

    assert result.ok is False
    assert result.error_code is ToolErrorCode.TIMEOUT
    assert "0.01-second timeout" in (result.error or "")
    assert cancelled.is_set()


def test_registry_rejects_sync_tools_and_duplicate_names() -> None:
    @tool("search_docs")
    def sync_search(query: str) -> str:
        """A sync tool is forbidden by the CloudDesk tool contract."""

        return query

    with pytest.raises(TypeError, match="must be asynchronous"):
        ToolRegistry([sync_search])

    @tool("search_docs")
    async def async_search(query: str) -> str:
        """An async search tool used for duplicate registration validation."""

        return query

    registry = ToolRegistry([async_search])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(async_search)


def test_registry_exposes_a_read_only_tool_mapping() -> None:
    @tool("search_docs")
    async def search_docs(query: str) -> str:
        """Search support documentation."""

        return query

    registry = ToolRegistry([search_docs])

    with pytest.raises(TypeError):
        registry.tools["replacement"] = search_docs  # type: ignore[index]
