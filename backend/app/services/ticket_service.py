"""Ticket use cases and transport projection for the support API."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from app.models import ApprovalRequest, Escalation, Ticket, WorkflowRun
from app.repositories import CustomerRepository, TicketRepository, WorkspaceRepository
from app.schemas.tickets import (
    ApprovalReference,
    CreateTicketRequest,
    CustomerContextLinks,
    EscalationReference,
    TicketDetail,
    TicketListParams,
    TicketListResponse,
    TicketMessageResponse,
    TicketSummary,
    WorkflowReference,
)
from sqlalchemy.ext.asyncio import AsyncSession


class TicketNotFoundError(LookupError):
    """Raised when an internal ticket UUID does not exist."""


class CustomerNotFoundError(LookupError):
    """Raised when ticket creation references an unknown customer."""


def _newest[T](values: Iterable[T]) -> T | None:
    return max(values, key=lambda item: (item.created_at, item.id), default=None)  # type: ignore[attr-defined]


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite-naive and PostgreSQL-aware timestamps to UTC transport values."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _ticket_summary(ticket: Ticket) -> TicketSummary:
    return TicketSummary(
        id=ticket.id,
        display_id=ticket.display_id,
        subject=ticket.subject,
        customer_id=ticket.customer_id,
        customer_name=ticket.customer.name,
        channel=ticket.channel,
        status=ticket.status,
        category=ticket.category,
        severity=ticket.severity,
        summary=ticket.summary,
        created_at=_as_utc(ticket.created_at),
        updated_at=_as_utc(ticket.updated_at),
    )


def _workflow_reference(workflow: WorkflowRun | None, ticket_id: str) -> WorkflowReference | None:
    if workflow is None:
        return None
    return WorkflowReference(
        id=workflow.id,
        status=workflow.status,
        url=f"/api/v1/tickets/{ticket_id}/workflow",
    )


def _approval_reference(approval: ApprovalRequest | None) -> ApprovalReference | None:
    if approval is None:
        return None
    return ApprovalReference(
        id=approval.id,
        status=approval.status,
        url=f"/api/v1/approvals/{approval.id}",
    )


def _escalation_reference(escalation: Escalation | None) -> EscalationReference | None:
    if escalation is None:
        return None
    return EscalationReference(
        id=escalation.id,
        status=escalation.status,
        team=escalation.team,
        url=f"/api/v1/escalations/{escalation.id}",
    )


def _ticket_detail(ticket: Ticket) -> TicketDetail:
    workflow = _newest(ticket.workflow_runs)
    approvals = [approval for run in ticket.workflow_runs for approval in run.approvals]
    workspace_id = ticket.workspace_id
    return TicketDetail(
        **_ticket_summary(ticket).model_dump(),
        body=ticket.body,
        messages=[
            TicketMessageResponse(
                id=message.id,
                ticket_id=message.ticket_id,
                direction=message.direction,
                author=message.author_name,
                body=message.body,
                created_at=_as_utc(message.created_at),
            )
            for message in ticket.messages
        ],
        workflow=_workflow_reference(workflow, ticket.id),
        approval=_approval_reference(_newest(approvals)),
        escalation=_escalation_reference(_newest(ticket.escalations)),
        customer_context_links=CustomerContextLinks(
            customer=f"/api/v1/customers/{ticket.customer_id}",
            subscription=(
                f"/api/v1/customers/{ticket.customer_id}#subscription"
                if ticket.customer.subscription is not None
                else None
            ),
            workspace=(
                f"/api/v1/customers/{ticket.customer_id}#workspace" if workspace_id else None
            ),
            previous_tickets=f"/api/v1/tickets?customer_id={ticket.customer_id}",
        ),
    )


class TicketService:
    """Coordinate ticket repositories while retaining transaction ownership."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tickets = TicketRepository(session)
        self.customers = CustomerRepository(session)
        self.workspaces = WorkspaceRepository(session)

    async def list_tickets(self, params: TicketListParams) -> TicketListResponse:
        filters = params.model_dump(exclude={"limit", "offset"})
        tickets = await self.tickets.list_filtered(
            **filters,
            limit=params.limit,
            offset=params.offset,
        )
        total = await self.tickets.count_filtered(**filters)
        return TicketListResponse(
            items=[_ticket_summary(ticket) for ticket in tickets],
            total=total,
            limit=params.limit,
            offset=params.offset,
        )

    async def get_ticket(self, ticket_id: str) -> TicketDetail:
        ticket = await self.tickets.get_with_context(ticket_id)
        if ticket is None:
            raise TicketNotFoundError(ticket_id)
        return _ticket_detail(ticket)

    async def create_ticket(self, request: CreateTicketRequest) -> TicketDetail:
        customer = await self.customers.get(request.customer_id)
        if customer is None:
            raise CustomerNotFoundError(request.customer_id)

        workspaces = await self.workspaces.list_for_customer(customer.id)
        display_number = await self.tickets.next_display_number()
        ticket = Ticket(
            display_id=f"CD-{display_number:04d}",
            customer_id=customer.id,
            workspace_id=workspaces[0].id if workspaces else None,
            subject=request.subject,
            body=request.body,
            channel=request.channel,
        )
        try:
            await self.tickets.add(ticket)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        created = await self.tickets.get_with_context(ticket.id)
        if created is None:  # Defensive: a committed row must remain readable.
            raise TicketNotFoundError(ticket.id)
        return _ticket_detail(created)

