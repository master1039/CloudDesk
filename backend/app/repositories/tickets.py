"""Ticket and conversation persistence."""

from __future__ import annotations

from collections.abc import Sequence

from app.models import Customer, Ticket, TicketMessage, WorkflowRun
from app.schemas.common import Channel, Severity, TicketCategory, TicketStatus
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from .base import BaseRepository


class TicketRepository(BaseRepository[Ticket]):
    model = Ticket

    @staticmethod
    def _apply_filters(
        statement: Select,
        *,
        customer_id: str | None,
        status: TicketStatus | None,
        category: TicketCategory | None,
        severity: Severity | None,
        channel: Channel | None,
        search: str | None,
    ) -> Select:
        if customer_id is not None:
            statement = statement.where(Ticket.customer_id == customer_id)
        if status is not None:
            statement = statement.where(Ticket.status == status)
        if category is not None:
            statement = statement.where(Ticket.category == category)
        if severity is not None:
            statement = statement.where(Ticket.severity == severity)
        if channel is not None:
            statement = statement.where(Ticket.channel == channel)
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    Ticket.display_id.ilike(pattern),
                    Ticket.subject.ilike(pattern),
                    Customer.name.ilike(pattern),
                )
            )
        return statement

    async def get_by_display_id(self, display_id: str) -> Ticket | None:
        return await self.session.scalar(select(Ticket).where(Ticket.display_id == display_id))

    async def get_with_context(self, ticket_id: str) -> Ticket | None:
        """Load a ticket and the customer context required by F4."""

        statement = (
            select(Ticket)
            .where(Ticket.id == ticket_id)
            .options(
                selectinload(Ticket.messages),
                selectinload(Ticket.workspace),
                selectinload(Ticket.product),
                selectinload(Ticket.customer).selectinload(Customer.subscription),
                selectinload(Ticket.customer).selectinload(Customer.workspaces),
                selectinload(Ticket.customer).selectinload(Customer.memory_notes),
                selectinload(Ticket.workflow_runs).selectinload(WorkflowRun.approvals),
                selectinload(Ticket.escalations),
            )
        )
        return await self.session.scalar(statement)

    async def list_filtered(
        self,
        *,
        customer_id: str | None = None,
        status: TicketStatus | None = None,
        category: TicketCategory | None = None,
        severity: Severity | None = None,
        channel: Channel | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Ticket]:
        statement = self._apply_filters(
            select(Ticket).join(Ticket.customer).options(selectinload(Ticket.customer)),
            customer_id=customer_id,
            status=status,
            category=category,
            severity=severity,
            channel=channel,
            search=search,
        )
        statement = statement.order_by(Ticket.created_at.desc(), Ticket.id.desc())
        statement = self._page(statement, offset=offset, limit=limit)
        return (await self.session.scalars(statement)).all()

    async def count_filtered(
        self,
        *,
        customer_id: str | None = None,
        status: TicketStatus | None = None,
        category: TicketCategory | None = None,
        severity: Severity | None = None,
        channel: Channel | None = None,
        search: str | None = None,
    ) -> int:
        statement = self._apply_filters(
            select(func.count(Ticket.id)).select_from(Ticket).join(Ticket.customer),
            customer_id=customer_id,
            status=status,
            category=category,
            severity=severity,
            channel=channel,
            search=search,
        )
        return int((await self.session.scalar(statement)) or 0)

    async def next_display_number(self) -> int:
        """Return the next demo-friendly ``CD-NNNN`` number in the current transaction."""

        display_ids = await self.session.scalars(
            select(Ticket.display_id).where(Ticket.display_id.like("CD-%"))
        )
        numbers = [
            int(value.removeprefix("CD-"))
            for value in display_ids
            if value.removeprefix("CD-").isdigit()
        ]
        return max(numbers, default=999) + 1

    async def list_previous_resolved(
        self, customer_id: str, *, exclude_ticket_id: str | None = None, limit: int = 10
    ) -> Sequence[Ticket]:
        statement = select(Ticket).where(
            Ticket.customer_id == customer_id,
            Ticket.status.in_((TicketStatus.RESOLVED, TicketStatus.CLOSED)),
        )
        if exclude_ticket_id is not None:
            statement = statement.where(Ticket.id != exclude_ticket_id)
        statement = statement.order_by(Ticket.updated_at.desc(), Ticket.id.desc())
        statement = self._page(statement, offset=0, limit=limit)
        return (await self.session.scalars(statement)).all()

    async def add_message(self, message: TicketMessage) -> TicketMessage:
        self.session.add(message)
        await self.session.flush()
        return message


class TicketMessageRepository(BaseRepository[TicketMessage]):
    model = TicketMessage

    async def list_for_ticket(self, ticket_id: str) -> Sequence[TicketMessage]:
        statement = (
            select(TicketMessage)
            .where(TicketMessage.ticket_id == ticket_id)
            .order_by(TicketMessage.created_at, TicketMessage.id)
        )
        return (await self.session.scalars(statement)).all()
