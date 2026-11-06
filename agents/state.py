"""Typed LangGraph support state and non-mutating reducer functions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Annotated, Any, Literal, TypedDict

from app.core.guardrails import CustomerOutputValidation
from app.schemas.common import Channel
from app.schemas.workflow import (
    Classification,
    CustomerContext,
    Diagnosis,
    EscalationDecision,
    Evidence,
    PreviousCase,
    ResolutionPlan,
    SeverityAssessment,
    TicketRunSummary,
    TokenUsage,
)


class WorkflowError(TypedDict):
    """Scrubbed workflow failure safe to persist and expose to an operator."""

    node: str
    code: str
    message: str
    retryable: bool


def append_items[ItemT](
    current: Sequence[ItemT] | None,
    addition: Sequence[ItemT] | None,
) -> list[ItemT]:
    """Return a new list containing both reducer contributions in order."""

    return [*(current or ()), *(addition or ())]


def merge_usage(
    current: TokenUsage | Mapping[str, Any] | None,
    addition: TokenUsage | Mapping[str, Any] | None,
) -> TokenUsage:
    """Add prompt and completion counts without mutating either input."""

    left = current if isinstance(current, TokenUsage) else TokenUsage.model_validate(current or {})
    right = addition if isinstance(addition, TokenUsage) else TokenUsage.model_validate(addition or {})
    return TokenUsage(
        prompt_tokens=left.prompt_tokens + right.prompt_tokens,
        completion_tokens=left.completion_tokens + right.completion_tokens,
    )


def merge_cost(
    current: Decimal | str | float | None,
    addition: Decimal | str | float | None,
) -> Decimal:
    """Add model cost values with decimal precision for workflow aggregation."""

    return Decimal(str(current or 0)) + Decimal(str(addition or 0))


class SupportState(TypedDict, total=False):
    """Shared partial state passed between bounded CloudDesk workflow nodes."""

    workflow_id: str
    thread_id: str
    ticket_id: str
    customer_id: str
    subject: str
    body: str
    channel: Channel
    plan_name: str | None
    attributes: dict[str, Any]

    classification: Classification
    severity_assessment: SeverityAssessment
    customer_context: CustomerContext
    evidence: list[Evidence]
    previous_cases: list[PreviousCase]
    diagnosis: Diagnosis
    resolution_plan: ResolutionPlan
    output_validation: CustomerOutputValidation
    risk: Literal["low", "high"]
    escalation: EscalationDecision
    approval: dict[str, Any]
    action_results: list[dict[str, Any]]
    ticket_summary: TicketRunSummary

    injection_signals: tuple[str, ...]
    policy_rules: tuple[str, ...]
    current_node: str
    completed_nodes: Annotated[list[str], append_items]
    errors: Annotated[list[WorkflowError], append_items]
    token_usage: Annotated[TokenUsage, merge_usage]
    estimated_cost: Annotated[Decimal, merge_cost]
