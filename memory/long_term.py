"""Scrubbed, de-duplicated long-term customer memory backed by SQL."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from app.core.guardrails import scrub
from app.models import CustomerMemory
from app.repositories import (
    CustomerMemoryRepository,
    CustomerRepository,
    TicketRepository,
    WorkflowRunRepository,
)
from app.schemas.common import MemoryType
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

MAX_RECALLED_NOTES = 10


@dataclass(frozen=True, slots=True)
class LongTermMemoryNote:
    """Safe memory projection that deliberately omits fingerprints and attributes."""

    id: str
    customer_id: str
    memory_type: MemoryType
    content: str
    source_ticket_id: str | None
    source_workflow_id: str | None
    created_at: datetime

    @classmethod
    def from_entity(cls, entity: CustomerMemory) -> LongTermMemoryNote:
        return cls(
            id=entity.id,
            customer_id=entity.customer_id,
            memory_type=entity.memory_type,
            content=entity.content,
            source_ticket_id=entity.source_ticket_id,
            source_workflow_id=entity.source_workflow_id,
            created_at=entity.created_at,
        )


def _memory_type(value: MemoryType | str) -> MemoryType:
    try:
        return MemoryType(value)
    except ValueError as error:
        raise ValueError(f"unsupported memory type: {value}") from error


def _safe_content(content: str) -> str:
    normalized = scrub(content).strip()
    if not normalized:
        raise ValueError("memory content must not be blank")
    return normalized


def _fingerprint(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


class LongTermMemory:
    """The only application write boundary for durable ``customer_memory`` notes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._customers = CustomerRepository(session)
        self._memory = CustomerMemoryRepository(session)
        self._tickets = TicketRepository(session)
        self._workflows = WorkflowRunRepository(session)
        self._last_created_at: datetime | None = None

    def _next_created_at(self) -> datetime:
        now = datetime.now(UTC)
        if self._last_created_at is not None and now <= self._last_created_at:
            now = self._last_created_at + timedelta(microseconds=1)
        self._last_created_at = now
        return now

    async def _validate_ownership(
        self,
        customer_id: str,
        *,
        content: str,
        source_ticket_id: str | None,
        source_workflow_id: str | None,
    ) -> None:
        if await self._customers.get(customer_id) is None:
            raise ValueError("customer does not exist")

        ticket = None
        if source_ticket_id is not None:
            ticket = await self._tickets.get(source_ticket_id)
            if ticket is None or ticket.customer_id != customer_id:
                raise ValueError("source ticket does not belong to customer")
            if content == scrub(ticket.body).strip():
                raise ValueError("raw ticket bodies cannot be stored in customer memory")

        if source_workflow_id is None:
            return
        workflow = await self._workflows.get(source_workflow_id)
        if workflow is None:
            raise ValueError("source workflow does not belong to customer")
        workflow_ticket = ticket or await self._tickets.get(workflow.ticket_id)
        if workflow_ticket is None or workflow_ticket.customer_id != customer_id:
            raise ValueError("source workflow does not belong to customer")
        if content == scrub(workflow_ticket.body).strip():
            raise ValueError("raw ticket bodies cannot be stored in customer memory")
        if source_ticket_id is not None and workflow.ticket_id != source_ticket_id:
            raise ValueError("source workflow does not belong to source ticket")

    async def store(
        self,
        customer_id: str,
        memory_type: MemoryType | str,
        content: str,
        *,
        source_ticket_id: str | None = None,
        source_workflow_id: str | None = None,
    ) -> LongTermMemoryNote:
        """Scrub and store one note, returning the existing note for an exact duplicate."""

        active_type = _memory_type(memory_type)
        safe_content = _safe_content(content)
        fingerprint = _fingerprint(safe_content)
        await self._validate_ownership(
            customer_id,
            content=safe_content,
            source_ticket_id=source_ticket_id,
            source_workflow_id=source_workflow_id,
        )

        existing = await self._memory.get_by_fingerprint(
            customer_id,
            active_type,
            fingerprint,
        )
        if existing is not None:
            return LongTermMemoryNote.from_entity(existing)

        try:
            async with self._session.begin_nested():
                created_at = self._next_created_at()
                entity = await self._memory.create(
                    customer_id=customer_id,
                    memory_type=active_type,
                    content=safe_content,
                    fingerprint=fingerprint,
                    source_ticket_id=source_ticket_id,
                    source_workflow_id=source_workflow_id,
                    attributes={},
                    created_at=created_at,
                    updated_at=created_at,
                )
        except IntegrityError:
            existing = await self._memory.get_by_fingerprint(
                customer_id,
                active_type,
                fingerprint,
            )
            if existing is None:
                raise
            entity = existing
        return LongTermMemoryNote.from_entity(entity)

    async def recall(
        self,
        customer_id: str,
        *,
        memory_type: MemoryType | str | None = None,
        limit: int = MAX_RECALLED_NOTES,
    ) -> Sequence[LongTermMemoryNote]:
        """Return at most ten newest notes belonging only to the requested customer."""

        if not 1 <= limit <= MAX_RECALLED_NOTES:
            raise ValueError(f"memory recall limit must be between 1 and {MAX_RECALLED_NOTES}")
        active_type = _memory_type(memory_type) if memory_type is not None else None
        notes = await self._memory.list_for_customer(
            customer_id,
            memory_type=active_type,
            limit=limit,
        )
        return tuple(LongTermMemoryNote.from_entity(note) for note in notes)
