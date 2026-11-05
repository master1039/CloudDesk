"""Customer-context specialist built only from policy-enforced reads and safe memory recall."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Protocol

from app.schemas.workflow import (
    CustomerContext,
    CustomerProfile,
    MemoryNoteContext,
    PreviousCase,
    SubscriptionContext,
    TokenUsage,
    WorkspaceContext,
)
from app.tools import ToolRegistry, ToolResult

from memory.long_term import LongTermMemoryNote


class CustomerAgentError(RuntimeError):
    """Raised when bounded customer context cannot be assembled safely."""


class CustomerNotFoundError(CustomerAgentError):
    """Raised when the requested customer does not exist."""


class CustomerMemoryReader(Protocol):
    """Small memory-facade contract required by the customer specialist."""

    async def recall_customer(
        self,
        customer_id: str,
        *,
        limit: int = 10,
    ) -> Sequence[LongTermMemoryNote]: ...


@dataclass(frozen=True, slots=True)
class CustomerAgentResult:
    """Deterministic context plus tool-call metadata for future workflow tracing."""

    output: CustomerContext
    tool_calls: tuple[ToolResult, ...]
    usage: TokenUsage
    duration_ms: int
    estimated_cost: Decimal = Decimal(0)


def _require_success(result: ToolResult) -> dict:
    if not result.ok or not isinstance(result.output, dict):
        code = result.error_code.value if result.error_code is not None else "invalid_output"
        raise CustomerAgentError(f"customer context tool {result.name} failed: {code}")
    return result.output


def _customer_profile(payload: dict, customer_id: str) -> CustomerProfile:
    if payload.get("found") is False:
        raise CustomerNotFoundError("customer was not found")
    if payload.get("id") != customer_id:
        raise CustomerAgentError("customer tool returned mismatched ownership")
    return CustomerProfile(
        id=payload["id"],
        name=payload["name"],
        email=payload["email"],
        company=payload.get("company"),
    )


def _workspace(payload: dict) -> WorkspaceContext | None:
    workspace = payload.get("workspace")
    return WorkspaceContext.model_validate(workspace) if workspace is not None else None


def _subscription(payload: dict, customer_id: str) -> SubscriptionContext | None:
    if payload.get("found") is False:
        return None
    if payload.get("customer_id") != customer_id:
        raise CustomerAgentError("subscription tool returned mismatched ownership")
    return SubscriptionContext(
        plan=payload["plan"],
        status=payload["status"],
        seats=payload["seats"],
    )


def _history(payload: dict, customer_id: str) -> list[PreviousCase]:
    if payload.get("customer_id") != customer_id:
        raise CustomerAgentError("ticket-history tool returned mismatched ownership")
    items = payload.get("items")
    if not isinstance(items, list):
        raise CustomerAgentError("ticket-history tool returned invalid items")
    return [
        PreviousCase(
            ticket_id=item["id"],
            display_id=item["display_id"],
            subject=item["subject"],
            category=item.get("category"),
            severity=item.get("severity"),
            summary=item.get("summary"),
        )
        for item in items
    ]


def _memory_notes(
    notes: Sequence[LongTermMemoryNote],
    customer_id: str,
) -> list[MemoryNoteContext]:
    if any(note.customer_id != customer_id for note in notes):
        raise CustomerAgentError("memory recall returned mismatched ownership")
    return [
        MemoryNoteContext(memory_type=note.memory_type.value, content=note.content)
        for note in notes
    ]


class CustomerAgent:
    """Load F4 customer context without model judgement or direct persistence access."""

    def __init__(self, registry: ToolRegistry, memory: CustomerMemoryReader) -> None:
        self._registry = registry
        self._memory = memory

    async def run(
        self,
        customer_id: str,
        *,
        current_ticket_id: str | None = None,
    ) -> CustomerAgentResult:
        """Load identity, subscription, workspace, history, and safe durable notes (F4)."""

        normalized_customer_id = customer_id.strip()
        if not normalized_customer_id:
            raise ValueError("customer_id must not be blank")
        if current_ticket_id is not None and not current_ticket_id.strip():
            raise ValueError("current_ticket_id must not be blank")

        started = perf_counter()
        history_args: dict[str, object] = {
            "customer_id": normalized_customer_id,
            "limit": 10,
        }
        if current_ticket_id is not None:
            history_args["exclude_ticket_id"] = current_ticket_id.strip()

        customer_call, subscription_call, history_call, notes = await asyncio.gather(
            self._registry.execute(
                "get_customer",
                {"customer_id": normalized_customer_id},
            ),
            self._registry.execute(
                "get_subscription",
                {"customer_id": normalized_customer_id},
            ),
            self._registry.execute("get_ticket_history", history_args),
            self._memory.recall_customer(normalized_customer_id, limit=10),
        )
        tool_calls = customer_call, subscription_call, history_call
        customer_payload = _require_success(customer_call)
        subscription_payload = _require_success(subscription_call)
        history_payload = _require_success(history_call)
        context = CustomerContext(
            customer=_customer_profile(customer_payload, normalized_customer_id),
            subscription=_subscription(subscription_payload, normalized_customer_id),
            workspace=_workspace(customer_payload),
            previous_tickets=_history(history_payload, normalized_customer_id),
            memory_notes=_memory_notes(notes, normalized_customer_id),
        )
        return CustomerAgentResult(
            output=context,
            tool_calls=tool_calls,
            usage=TokenUsage(),
            duration_ms=max(0, round((perf_counter() - started) * 1_000)),
        )
