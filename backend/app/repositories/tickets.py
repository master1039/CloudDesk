"""Ticket and conversation persistence."""

from __future__ import annotations

from collections.abc import Sequence

from app.models import Customer, Ticket, TicketMessage
from app.schemas.common import Severity, TicketCategory, TicketStatus
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .base import BaseRepository


class TicketRepository(BaseRepository[Ticket]):
    model = Ticket

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
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Ticket]:
        statement = select(Ticket)
        if customer_id is not None:
            statement = statement.where(Ticket.customer_id == customer_id)
        if status is not None:
            statement = statement.where(Ticket.status == status)
        if category is not None:
            statement = statement.where(Ticket.category == category)
        if severity is not None:
            statement = statement.where(Ticket.severity == severity)
        statement = statement.order_by(Ticket.created_at.desc(), Ticket.id.desc())
        statement = self._page(statement, offset=offset, limit=limit)
        return (await self.session.scalars(statement)).all()

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
