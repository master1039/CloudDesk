"""Grounded resolution planning with deterministic, approval-aware actions."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any

from app.core.guardrails import CustomerOutputValidation, validate_customer_output
from app.core.llm import StructuredLLM, call_structured
from app.schemas.common import TicketCategory
from app.schemas.workflow import (
    CustomerContext,
    Diagnosis,
    Evidence,
    PlannedAction,
    ResolutionPlan,
    TokenUsage,
)
from app.tools import ToolPolicy

from agents.prompts import RESOLUTION_PROMPT, wrap_untrusted

_BLOCKED_REPLY = "A proposed reply could not be generated safely and requires agent review."


@dataclass(frozen=True, slots=True)
class ResolutionAgentResult:
    """Validated plan plus trace-ready model and output-gate metadata."""

    output: ResolutionPlan
    validation: CustomerOutputValidation
    usage: TokenUsage
    duration_ms: int
    llm_duration_ms: int
    estimated_cost: Decimal
    provider: str
    model: str
    attempts: int


def _ground_response(reply: str, evidence: Sequence[Evidence]) -> str:
    """Append stable customer-safe citations for every supplied knowledge article."""

    references: list[str] = []
    seen: set[str] = set()
    for item in evidence:
        if item.article_id in seen or item.url in reply:
            continue
        seen.add(item.article_id)
        references.append(f"- [{item.title}]({item.url})")
    if not references:
        return reply.strip()
    return f"{reply.strip()}\n\nReferences:\n" + "\n".join(references)


def _money(value: Decimal | str | float) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("refund amount must be a valid number") from exc
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise ValueError("refund amount must be positive with at most two decimal places")
    return amount


def _action(
    policy: ToolPolicy,
    tool: str,
    arguments: dict[str, Any],
    reason: str,
) -> PlannedAction:
    rule = policy.rule_for(tool)
    if not rule.known:
        raise ValueError(f"resolution planner cannot use unknown tool: {tool}")
    return PlannedAction(
        tool=tool,
        arguments=arguments,
        requires_approval=rule.requires_approval,
        reason=reason,
    )


def _prompt(
    subject: str,
    body: str,
    category: TicketCategory,
    diagnosis: Diagnosis,
    evidence: Sequence[Evidence],
    customer_context: CustomerContext | None,
) -> str:
    blocks = [
        f"Trusted ticket category: {category.value}",
        wrap_untrusted(subject, source="ticket_subject"),
        wrap_untrusted(body, source="ticket_body"),
        wrap_untrusted(
            json.dumps(diagnosis.model_dump(mode="json"), sort_keys=True),
            source="diagnosis",
        ),
        wrap_untrusted(
            json.dumps([item.model_dump(mode="json") for item in evidence], sort_keys=True),
            source="knowledge_evidence",
        ),
    ]
    if customer_context is not None:
        blocks.append(
            wrap_untrusted(
                json.dumps(customer_context.model_dump(mode="json"), sort_keys=True),
                source="customer_context",
            )
        )
    return "\n".join(blocks)


class ResolutionAgent:
    """Draft and validate a grounded plan while deterministic code owns actions (F8/F9/N5)."""

    def __init__(
        self,
        llm: StructuredLLM | None = None,
        *,
        policy: ToolPolicy | None = None,
    ) -> None:
        self._llm = llm
        self._policy = policy or ToolPolicy()

    def plan_actions(
        self,
        ticket_id: str,
        category: TicketCategory | str,
        summary: str,
        *,
        customer_id: str | None = None,
        refund_amount: Decimal | str | float | None = None,
        currency: str = "USD",
        workspace_id: str | None = None,
        setting_reset: Mapping[str, Any] | None = None,
    ) -> tuple[PlannedAction, ...]:
        """Build the only executable action list from explicit structured inputs."""

        normalized_ticket_id = ticket_id.strip()
        normalized_summary = " ".join(summary.split())
        if not normalized_ticket_id or not normalized_summary:
            raise ValueError("ticket id and resolution summary must not be blank")
        active_category = (
            category if isinstance(category, TicketCategory) else TicketCategory(category)
        )
        actions = [
            _action(
                self._policy,
                "update_ticket",
                {
                    "ticket_id": normalized_ticket_id,
                    "category": active_category.value,
                    "summary": normalized_summary[:500],
                },
                "Record the proposed classification and resolution summary on the ticket.",
            )
        ]

        if refund_amount is not None:
            if active_category is not TicketCategory.BILLING:
                raise ValueError("refund actions are only valid for billing tickets")
            if customer_id is None or not customer_id.strip():
                raise ValueError("customer id is required for a refund request")
            amount = _money(refund_amount)
            normalized_currency = currency.strip().upper()
            if len(normalized_currency) != 3:
                raise ValueError("refund currency must be a three-letter code")
            actions.append(
                _action(
                    self._policy,
                    "create_refund_request",
                    {
                        "ticket_id": normalized_ticket_id,
                        "customer_id": customer_id.strip(),
                        "amount": str(amount),
                        "currency": normalized_currency,
                        "reason": normalized_summary[:500],
                        "idempotency_key": (
                            f"{normalized_ticket_id}:refund:{amount}:{normalized_currency}"
                        ),
                    },
                    "A billing refund was explicitly requested and requires human approval.",
                )
            )

        if setting_reset is not None:
            active_workspace_id = workspace_id or str(setting_reset.get("workspace_id", ""))
            setting = str(setting_reset.get("setting", "")).strip()
            if not active_workspace_id.strip() or not setting or "value" not in setting_reset:
                raise ValueError("setting reset requires workspace_id, setting, and value")
            actions.append(
                _action(
                    self._policy,
                    "reset_demo_setting",
                    {
                        "workspace_id": active_workspace_id.strip(),
                        "setting": setting,
                        "value": setting_reset["value"],
                    },
                    "A workspace setting reset was explicitly requested and requires approval.",
                )
            )
        return tuple(actions)

    async def run(
        self,
        subject: str,
        body: str,
        category: TicketCategory | str,
        diagnosis: Diagnosis,
        *,
        ticket_id: str,
        evidence: Sequence[Evidence] = (),
        customer_context: CustomerContext | None = None,
        customer_id: str | None = None,
        refund_amount: Decimal | str | float | None = None,
        currency: str = "USD",
        workspace_id: str | None = None,
        setting_reset: Mapping[str, Any] | None = None,
        current_customer_identifiers: Sequence[str] = (),
        other_customer_identifiers: Sequence[str] = (),
    ) -> ResolutionAgentResult:
        """Draft, cite, validate, and deterministically replace all model-proposed actions."""

        normalized_subject = " ".join(subject.split())
        normalized_body = " ".join(body.split())
        if not normalized_subject or not normalized_body:
            raise ValueError("ticket subject and body must not be blank")
        active_category = (
            category if isinstance(category, TicketCategory) else TicketCategory(category)
        )

        started = perf_counter()
        call = await call_structured(
            ResolutionPlan,
            _prompt(
                normalized_subject,
                normalized_body,
                active_category,
                diagnosis,
                evidence,
                customer_context,
            ),
            system_prompt=RESOLUTION_PROMPT,
            llm=self._llm,
        )
        grounded_reply = _ground_response(call.output.customer_reply, evidence)
        validation = validate_customer_output(
            grounded_reply,
            current_customer_identifiers=current_customer_identifiers,
            other_customer_identifiers=other_customer_identifiers,
        )
        reply = grounded_reply if validation.valid else _BLOCKED_REPLY
        active_customer_id = customer_id
        active_workspace_id = workspace_id
        if customer_context is not None:
            active_customer_id = active_customer_id or customer_context.customer.id
            if customer_context.workspace is not None:
                active_workspace_id = active_workspace_id or customer_context.workspace.id
        actions = self.plan_actions(
            ticket_id,
            active_category,
            call.output.summary,
            customer_id=active_customer_id,
            refund_amount=refund_amount,
            currency=currency,
            workspace_id=active_workspace_id,
            setting_reset=setting_reset,
        )
        output = call.output.model_copy(update={"customer_reply": reply, "actions": list(actions)})
        return ResolutionAgentResult(
            output=output,
            validation=validation,
            usage=call.usage,
            duration_ms=max(0, round((perf_counter() - started) * 1_000)),
            llm_duration_ms=call.duration_ms,
            estimated_cost=call.estimated_cost,
            provider=call.provider,
            model=call.model,
            attempts=call.attempts,
        )
