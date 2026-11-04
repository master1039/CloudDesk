"""P6-3 offline tests for transactional and approval-gated write tools (F9)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from app.core.database import build_engine, build_session_factory, create_tables
from app.repositories import EscalationRepository, TicketRepository
from app.services.seed_service import bootstrap_demo_data
from app.tools import ToolErrorCode, ToolRegistry, create_write_tool_registry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"


class StubWorkspaceAdmin:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def reset_demo_setting(
        self, *, workspace_id: str, setting: str, value: str | float | bool | None
    ) -> Mapping[str, Any]:
        call = {"workspace_id": workspace_id, "setting": setting, "value": value}
        self.calls.append(call)
        return {"updated": True, **call}


class StubBilling:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_refund_request(
        self,
        *,
        ticket_id: str,
        customer_id: str,
        amount: Decimal,
        currency: str,
        reason: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        call = {
            "ticket_id": ticket_id,
            "customer_id": customer_id,
            "amount": amount,
            "currency": currency,
            "reason": reason,
            "idempotency_key": idempotency_key,
        }
        self.calls.append(call)
        return {
            "request_id": "refund-demo-1",
            "status": "requested",
            "amount": format(amount, "f"),
            "currency": currency,
        }


@pytest.fixture
async def write_tool_context(
    tmp_path: Path,
) -> AsyncIterator[
    tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        StubWorkspaceAdmin,
        StubBilling,
    ]
]:
    engine = build_engine(f"sqlite+aiosqlite:///{(tmp_path / 'write-tools.db').as_posix()}")
    await create_tables(engine)
    session_factory = build_session_factory(engine)
    async with session_factory.begin() as session:
        await bootstrap_demo_data(session, SAMPLE_DATA_DIR)

    workspace_admin = StubWorkspaceAdmin()
    billing = StubBilling()
    registry = create_write_tool_registry(
        session_factory=session_factory,
        workspace_admin=workspace_admin,
        billing=billing,
    )
    try:
        yield registry, session_factory, workspace_admin, billing
    finally:
        await engine.dispose()


async def test_update_ticket_persists_only_routine_fields_without_approval(
    write_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        StubWorkspaceAdmin,
        StubBilling,
    ],
) -> None:
    registry, session_factory, _, _ = write_tool_context

    result = await registry.execute(
        "update_ticket",
        {
            "ticket_id": "CD-1010",
            "status": "resolved",
            "category": "feature_request",
            "severity": "low",
            "summary": "Feature request recorded for product review.",
        },
    )

    assert result.ok is True
    assert result.approval_required is False
    assert result.output["status"] == "resolved"
    async with session_factory() as session:
        ticket = await TicketRepository(session).get_by_display_id("CD-1010")
        assert ticket is not None
        assert ticket.subject == "Dark mode request"
        assert ticket.status.value == "resolved"
        assert ticket.severity.value == "low"
        assert ticket.resolved_at is not None


async def test_update_ticket_rejects_empty_and_unknown_ticket_updates(
    write_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        StubWorkspaceAdmin,
        StubBilling,
    ],
) -> None:
    registry, _, _, _ = write_tool_context

    empty = await registry.execute("update_ticket", {"ticket_id": "CD-1010"})
    missing = await registry.execute(
        "update_ticket", {"ticket_id": "CD-9999", "status": "resolved"}
    )

    assert empty.error_code == ToolErrorCode.EXECUTION_ERROR
    assert missing.error_code == ToolErrorCode.EXECUTION_ERROR


async def test_refund_has_no_provider_side_effect_before_approval(
    write_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        StubWorkspaceAdmin,
        StubBilling,
    ],
) -> None:
    registry, _, _, billing = write_tool_context
    args = {
        "ticket_id": "CD-1002",
        "customer_id": "customer-demo",
        "amount": "30.00",
        "currency": "usd",
        "reason": "Unused seats",
        "idempotency_key": "CD-1002-refund-v1",
    }

    blocked = await registry.execute("create_refund_request", args)
    assert billing.calls == []
    approved = await registry.execute("create_refund_request", args, approved=True)

    assert blocked.error_code == ToolErrorCode.APPROVAL_REQUIRED
    assert billing.calls == [
        {
            **args,
            "amount": Decimal("30.00"),
            "currency": "USD",
        }
    ]
    assert approved.ok is True
    assert approved.output == {
        "request_id": "refund-demo-1",
        "status": "requested",
        "amount": "30.00",
        "currency": "USD",
    }


async def test_workspace_setting_has_no_provider_side_effect_before_approval(
    write_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        StubWorkspaceAdmin,
        StubBilling,
    ],
) -> None:
    registry, _, workspace_admin, _ = write_tool_context
    args = {"workspace_id": "workspace-demo", "setting": "file_sharing", "value": True}

    blocked = await registry.execute("reset_demo_setting", args)
    assert workspace_admin.calls == []
    approved = await registry.execute("reset_demo_setting", args, approved=True)

    assert blocked.error_code == ToolErrorCode.APPROVAL_REQUIRED
    assert workspace_admin.calls == [args]
    assert approved.ok is True
    assert approved.output["updated"] is True


async def test_create_escalation_is_safe_transactional_and_idempotent(
    write_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        StubWorkspaceAdmin,
        StubBilling,
    ],
) -> None:
    registry, session_factory, _, _ = write_tool_context
    args = {
        "ticket_id": "CD-1005",
        "team": "Security Response",
        "reason": "Potential security incident",
        "policy_rules": ["security", "security"],
        "priority": "critical",
    }

    created = await registry.execute("create_escalation", args)
    repeated = await registry.execute("create_escalation", args)

    assert created.ok is True
    assert created.output["created"] is True
    assert created.output["policy_rules"] == ["security"]
    assert repeated.ok is True
    assert repeated.output["created"] is False
    assert repeated.output["id"] == created.output["id"]
    async with session_factory() as session:
        ticket = await TicketRepository(session).get_by_display_id("CD-1005")
        assert ticket is not None
        assert ticket.status.value == "escalated"
        open_escalations = await EscalationRepository(session).list_open_for_ticket(ticket.id)
        assert len(open_escalations) == 1


async def test_unconfigured_approval_provider_fails_only_after_gate(
    write_tool_context: tuple[
        ToolRegistry,
        async_sessionmaker[AsyncSession],
        StubWorkspaceAdmin,
        StubBilling,
    ],
) -> None:
    _, session_factory, _, _ = write_tool_context
    registry = create_write_tool_registry(session_factory=session_factory)
    args = {"workspace_id": "workspace-demo", "setting": "file_sharing", "value": True}

    blocked = await registry.execute("reset_demo_setting", args)
    approved = await registry.execute("reset_demo_setting", args, approved=True)

    assert blocked.error_code == ToolErrorCode.APPROVAL_REQUIRED
    assert approved.error_code == ToolErrorCode.EXECUTION_ERROR
    assert "not configured" not in (approved.error or "")
