"""Support supervisor for ticket classification, severity, and run summaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core.guardrails import injection_signals
from app.core.llm import StructuredCallResult, StructuredLLM, call_structured
from app.schemas.common import TicketCategory
from app.schemas.workflow import (
    Classification,
    SeverityAssessment,
    TicketRunSummary,
    TokenUsage,
    WorkflowSchema,
)

from agents.prompts import (
    SUPERVISOR_CLASSIFICATION_PROMPT,
    SUPERVISOR_SEVERITY_PROMPT,
    SUPERVISOR_SUMMARY_PROMPT,
    wrap_untrusted,
)
from agents.rules import rule_category, rule_severity


@dataclass(frozen=True, slots=True)
class SupervisorResult[OutputT: WorkflowSchema]:
    """Validated specialist value with safe tracing and deterministic-rule metadata."""

    output: OutputT
    usage: TokenUsage
    duration_ms: int
    estimated_cost: Decimal
    provider: str
    model: str
    attempts: int
    injection_signals: tuple[str, ...] = ()
    policy_rules: tuple[str, ...] = ()
    rule_applied: bool = False


def _result[OutputT: WorkflowSchema](
    call: StructuredCallResult[OutputT],
    *,
    output: OutputT | None = None,
    signals: tuple[str, ...] = (),
    policy_rules: tuple[str, ...] = (),
    rule_applied: bool = False,
) -> SupervisorResult[OutputT]:
    return SupervisorResult(
        output=output or call.output,
        usage=call.usage,
        duration_ms=call.duration_ms,
        estimated_cost=call.estimated_cost,
        provider=call.provider,
        model=call.model,
        attempts=call.attempts,
        injection_signals=signals,
        policy_rules=policy_rules,
        rule_applied=rule_applied,
    )


def _ticket_text(subject: str, body: str) -> str:
    normalized_subject = " ".join(subject.split())
    normalized_body = " ".join(body.split())
    if not normalized_subject:
        raise ValueError("ticket subject must not be blank")
    if not normalized_body:
        raise ValueError("ticket body must not be blank")
    return f"{normalized_subject}\n{normalized_body}"


def _wrapped_ticket(subject: str, body: str) -> str:
    return "\n".join(
        (
            wrap_untrusted(subject, source="ticket_subject"),
            wrap_untrusted(body, source="ticket_body"),
        )
    )


class SupervisorAgent:
    """Perform the supervisor's model-assisted work behind deterministic safety rules."""

    def __init__(self, llm: StructuredLLM | None = None) -> None:
        self._llm = llm

    async def understand(
        self,
        subject: str,
        body: str,
        *,
        plan_name: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> SupervisorResult[Classification]:
        """Classify an untrusted ticket and apply narrow deterministic category overrides (F2/N4)."""

        text = _ticket_text(subject, body)
        signals = injection_signals(text)
        call = await call_structured(
            Classification,
            _wrapped_ticket(subject, body),
            system_prompt=SUPERVISOR_CLASSIFICATION_PROMPT,
            llm=self._llm,
        )
        decision = rule_category(
            call.output.category,
            text,
            plan_name=plan_name,
            attributes=attributes,
            injection_detected=bool(signals),
        )
        classification = call.output.model_copy(update={"category": decision.category})
        return _result(
            call,
            output=classification,
            signals=signals,
            policy_rules=decision.policy_rules,
            rule_applied=decision.overridden,
        )

    async def understand_ticket(
        self,
        subject: str,
        body: str,
        **context: Any,
    ) -> SupervisorResult[Classification]:
        """Node-name alias for `understand`."""

        return await self.understand(subject, body, **context)

    async def assess_severity(
        self,
        subject: str,
        body: str,
        classification: Classification | TicketCategory | str,
        *,
        plan_name: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> SupervisorResult[SeverityAssessment]:
        """Assess impact, then let deterministic policy raise but never lower severity (F3/N4)."""

        text = _ticket_text(subject, body)
        signals = injection_signals(text)
        category = (
            classification.category if isinstance(classification, Classification) else classification
        )
        category_value = (
            category if isinstance(category, TicketCategory) else TicketCategory(category)
        )
        call = await call_structured(
            SeverityAssessment,
            f"{_wrapped_ticket(subject, body)}\nClassified category: {category_value.value}",
            system_prompt=SUPERVISOR_SEVERITY_PROMPT,
            llm=self._llm,
        )
        decision = rule_severity(
            call.output.severity,
            text,
            plan_name=plan_name,
            category=category_value,
            attributes=attributes,
        )
        assessment = call.output
        if decision.raised:
            reason = f"{assessment.reason} {decision.reason}"[:1_000]
            assessment = assessment.model_copy(
                update={"severity": decision.severity, "reason": reason}
            )
        return _result(
            call,
            output=assessment,
            signals=signals,
            policy_rules=decision.policy_rules,
            rule_applied=decision.raised,
        )

    async def summarize(
        self,
        ticket_summary: str,
        outcome: str,
        *,
        customer_follow_up: str | None = None,
    ) -> SupervisorResult[TicketRunSummary]:
        """Create the structured internal summary used by the future ticket-summary node (F11)."""

        if not ticket_summary.strip() or not outcome.strip():
            raise ValueError("ticket summary and outcome must not be blank")
        parts = [
            wrap_untrusted(ticket_summary, source="ticket_context"),
            wrap_untrusted(outcome, source="workflow_outcome"),
        ]
        if customer_follow_up is not None:
            parts.append(wrap_untrusted(customer_follow_up, source="customer_follow_up"))
        call = await call_structured(
            TicketRunSummary,
            "\n".join(parts),
            system_prompt=SUPERVISOR_SUMMARY_PROMPT,
            llm=self._llm,
        )
        return _result(call)

    async def ticket_summary(
        self,
        ticket_summary: str,
        outcome: str,
        *,
        customer_follow_up: str | None = None,
    ) -> SupervisorResult[TicketRunSummary]:
        """Node-name alias for `summarize`."""

        return await self.summarize(
            ticket_summary,
            outcome,
            customer_follow_up=customer_follow_up,
        )
