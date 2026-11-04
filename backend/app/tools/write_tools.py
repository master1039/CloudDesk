"""Policy-enforced write capabilities used by CloudDesk support workflows."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.models import Escalation, Ticket
from app.repositories import EscalationRepository, TicketRepository
from app.schemas.common import EscalationStatus, Severity, TicketCategory, TicketStatus
from langchain_core.tools import BaseTool, tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from integrations.protocols import BillingProvider, JsonScalar, WorkspaceAdminProvider

from .policy import ToolPolicy
from .registry import ToolRegistry

type SessionFactory = async_sessionmaker[AsyncSession]
type PolicyRule = Annotated[str, Field(min_length=1, max_length=120)]


class WriteToolDependencyError(RuntimeError):
    """Raised only after approval when a P6-4 provider is not configured."""


async def _find_ticket(repository: TicketRepository, ticket_ref: str) -> Ticket | None:
    ticket = await repository.get(ticket_ref)
    if ticket is not None:
        return ticket
    return await repository.get_by_display_id(ticket_ref)


def _ticket_result(ticket: Ticket) -> dict[str, Any]:
    return {
        "id": ticket.id,
        "display_id": ticket.display_id,
        "status": ticket.status.value,
        "category": ticket.category.value if ticket.category else None,
        "severity": ticket.severity.value if ticket.severity else None,
        "summary": ticket.summary,
    }


def _escalation_result(escalation: Escalation, *, created: bool) -> dict[str, Any]:
    return {
        "id": escalation.id,
        "ticket_id": escalation.ticket_id,
        "workflow_id": escalation.workflow_id,
        "team": escalation.team,
        "reason": escalation.reason,
        "policy_rules": list(escalation.policy_rules),
        "priority": escalation.priority.value,
        "status": escalation.status.value,
        "created": created,
    }


def create_write_tools(
    *,
    session_factory: SessionFactory | None = None,
    workspace_admin: WorkspaceAdminProvider | None = None,
    billing: BillingProvider | None = None,
) -> tuple[BaseTool, ...]:
    """Create database writes and approval-gated provider adapters."""

    active_factory = session_factory if session_factory is not None else get_session_factory()

    @tool("update_ticket")
    async def update_ticket(
        ticket_id: Annotated[str, Field(min_length=1, max_length=36)],
        status: TicketStatus | None = None,
        category: TicketCategory | None = None,
        severity: Severity | None = None,
        summary: Annotated[str | None, Field(min_length=1, max_length=500)] = None,
    ) -> dict[str, Any]:
        """Update only routine classification, status, severity, or summary ticket fields."""

        if all(value is None for value in (status, category, severity, summary)):
            raise ValueError("at least one ticket field must be supplied")
        normalized_summary = summary.strip() if summary is not None else None
        if summary is not None and not normalized_summary:
            raise ValueError("summary must not be blank")

        async with active_factory.begin() as session:
            ticket = await _find_ticket(TicketRepository(session), ticket_id)
            if ticket is None:
                raise LookupError("ticket not found")

            if status is not None:
                now = datetime.now(UTC)
                ticket.status = status
                if status == TicketStatus.RESOLVED:
                    ticket.resolved_at = now
                    ticket.closed_at = None
                elif status == TicketStatus.CLOSED:
                    ticket.resolved_at = ticket.resolved_at or now
                    ticket.closed_at = now
                else:
                    ticket.resolved_at = None
                    ticket.closed_at = None
            if category is not None:
                ticket.category = category
            if severity is not None:
                ticket.severity = severity
            if summary is not None:
                ticket.summary = normalized_summary
            await session.flush()
            return _ticket_result(ticket)

    @tool("reset_demo_setting")
    async def reset_demo_setting(
        workspace_id: Annotated[str, Field(min_length=1, max_length=36)],
        setting: Annotated[str, Field(min_length=1, max_length=120)],
        value: JsonScalar,
    ) -> dict[str, Any]:
        """Reset one demo workspace setting after a recorded human approval."""

        if workspace_admin is None:
            raise WriteToolDependencyError("workspace admin provider is not configured")
        normalized_setting = setting.strip()
        if not normalized_setting:
            raise ValueError("setting must not be blank")
        return dict(
            await workspace_admin.reset_demo_setting(
                workspace_id=workspace_id,
                setting=normalized_setting,
                value=value,
            )
        )

    @tool("create_refund_request")
    async def create_refund_request(
        ticket_id: Annotated[str, Field(min_length=1, max_length=36)],
        customer_id: Annotated[str, Field(min_length=1, max_length=36)],
        amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)],
        currency: Annotated[str, Field(min_length=3, max_length=3)],
        reason: Annotated[str, Field(min_length=1, max_length=500)],
        idempotency_key: Annotated[str, Field(min_length=1, max_length=120)],
    ) -> dict[str, Any]:
        """Create an idempotent refund request after a recorded human approval."""

        if billing is None:
            raise WriteToolDependencyError("billing provider is not configured")
        normalized_reason = reason.strip()
        normalized_key = idempotency_key.strip()
        if not normalized_reason or not normalized_key:
            raise ValueError("reason and idempotency key must not be blank")
        return dict(
            await billing.create_refund_request(
                ticket_id=ticket_id,
                customer_id=customer_id,
                amount=amount,
                currency=currency.upper(),
                reason=normalized_reason,
                idempotency_key=normalized_key,
            )
        )

    @tool("create_escalation")
    async def create_escalation(
        ticket_id: Annotated[str, Field(min_length=1, max_length=36)],
        team: Annotated[str, Field(min_length=1, max_length=120)],
        reason: Annotated[str, Field(min_length=1, max_length=2000)],
        policy_rules: Annotated[list[PolicyRule] | None, Field(max_length=20)] = None,
        priority: Severity = Severity.MEDIUM,
        workflow_id: Annotated[str | None, Field(min_length=1, max_length=36)] = None,
    ) -> dict[str, Any]:
        """Create the safe escalation fallback, reusing an identical open escalation."""

        normalized_team = team.strip()
        normalized_reason = reason.strip()
        if not normalized_team or not normalized_reason:
            raise ValueError("team and reason must not be blank")
        normalized_rules = list(dict.fromkeys(rule.strip() for rule in policy_rules or []))
        if any(not rule for rule in normalized_rules):
            raise ValueError("policy rules must not be blank")

        async with active_factory.begin() as session:
            tickets = TicketRepository(session)
            ticket = await _find_ticket(tickets, ticket_id)
            if ticket is None:
                raise LookupError("ticket not found")

            escalations = EscalationRepository(session)
            for existing in await escalations.list_open_for_ticket(ticket.id):
                if (
                    existing.team == normalized_team
                    and existing.reason == normalized_reason
                    and existing.workflow_id == workflow_id
                    and list(existing.policy_rules) == normalized_rules
                    and existing.priority == priority
                ):
                    ticket.status = TicketStatus.ESCALATED
                    return _escalation_result(existing, created=False)

            escalation = await escalations.create(
                ticket_id=ticket.id,
                workflow_id=workflow_id,
                team=normalized_team,
                reason=normalized_reason,
                policy_rules=normalized_rules,
                priority=priority,
                status=EscalationStatus.OPEN,
            )
            ticket.status = TicketStatus.ESCALATED
            await session.flush()
            return _escalation_result(escalation, created=True)

    return update_ticket, reset_demo_setting, create_refund_request, create_escalation


def create_write_tool_registry(
    *,
    session_factory: SessionFactory | None = None,
    workspace_admin: WorkspaceAdminProvider | None = None,
    billing: BillingProvider | None = None,
    settings: Settings | None = None,
    policy: ToolPolicy | None = None,
) -> ToolRegistry:
    """Build the P6-3 registry; callers invoke writes only through ``execute``."""

    active_settings = settings if settings is not None else get_settings()
    tools = create_write_tools(
        session_factory=session_factory,
        workspace_admin=workspace_admin,
        billing=billing,
    )
    return ToolRegistry(tools, policy=policy, settings=active_settings)
