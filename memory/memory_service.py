"""Workflow-facing recall and resolution-recording orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from .long_term import MAX_RECALLED_NOTES, LongTermMemory, LongTermMemoryNote

MAX_TROUBLESHOOTING_STEPS = 3


@dataclass(frozen=True, slots=True)
class ResolutionMemoryRecord:
    """The three durable note groups produced after one resolution run."""

    past_issue: LongTermMemoryNote
    troubleshooting: LongTermMemoryNote
    resolution: LongTermMemoryNote

    @property
    def notes(self) -> tuple[LongTermMemoryNote, ...]:
        return self.past_issue, self.troubleshooting, self.resolution


def _first_steps(steps: Sequence[str]) -> tuple[str, ...]:
    if isinstance(steps, (str, bytes)):
        raise TypeError("troubleshooting_steps must be a sequence of step strings")
    if any(not isinstance(step, str) for step in steps):
        raise TypeError("troubleshooting_steps must be a sequence of step strings")
    normalized = tuple(step.strip() for step in steps if step.strip())
    if not normalized:
        raise ValueError("at least one troubleshooting step is required")
    return normalized[:MAX_TROUBLESHOOTING_STEPS]


def _numbered_steps(steps: Sequence[str]) -> str:
    return "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))


class MemoryService:
    """Compose durable memory operations for future workflow nodes (F4/F11/N7)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._long_term = LongTermMemory(session)

    async def recall_customer(
        self,
        customer_id: str,
        *,
        limit: int = MAX_RECALLED_NOTES,
    ) -> Sequence[LongTermMemoryNote]:
        """Return up to ten newest safe notes for the customer-context node."""

        return await self._long_term.recall(customer_id, limit=limit)

    async def record_resolution(
        self,
        customer_id: str,
        *,
        source_ticket_id: str,
        source_workflow_id: str,
        past_issue: str,
        troubleshooting_steps: Sequence[str],
        resolution_note: str,
    ) -> ResolutionMemoryRecord:
        """Atomically record the bounded durable memory produced by one workflow run."""

        troubleshooting = _numbered_steps(_first_steps(troubleshooting_steps))
        source = {
            "source_ticket_id": source_ticket_id,
            "source_workflow_id": source_workflow_id,
        }
        async with self._session.begin_nested():
            past_issue_note = await self._long_term.store(
                customer_id,
                "past_issue",
                past_issue,
                **source,
            )
            troubleshooting_note = await self._long_term.store(
                customer_id,
                "troubleshooting",
                troubleshooting,
                **source,
            )
            resolution = await self._long_term.store(
                customer_id,
                "note",
                resolution_note,
                **source,
            )
        return ResolutionMemoryRecord(
            past_issue=past_issue_note,
            troubleshooting=troubleshooting_note,
            resolution=resolution,
        )


async def recall_customer(
    session: AsyncSession,
    customer_id: str,
    *,
    limit: int = MAX_RECALLED_NOTES,
) -> Sequence[LongTermMemoryNote]:
    """Functional entry point used by the future ``customer_context`` node."""

    return await MemoryService(session).recall_customer(customer_id, limit=limit)


async def record_resolution(
    session: AsyncSession,
    customer_id: str,
    *,
    source_ticket_id: str,
    source_workflow_id: str,
    past_issue: str,
    troubleshooting_steps: Sequence[str],
    resolution_note: str,
) -> ResolutionMemoryRecord:
    """Functional entry point used by the future ``memory_update`` node."""

    return await MemoryService(session).record_resolution(
        customer_id,
        source_ticket_id=source_ticket_id,
        source_workflow_id=source_workflow_id,
        past_issue=past_issue,
        troubleshooting_steps=troubleshooting_steps,
        resolution_note=resolution_note,
    )
