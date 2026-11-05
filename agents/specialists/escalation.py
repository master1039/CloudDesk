"""Policy-first escalation assessment and registry-enforced routing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any

from app.core.llm import StructuredLLM, call_structured
from app.schemas.common import Severity, TicketCategory
from app.schemas.workflow import EscalationDecision, TokenUsage
from app.tools import ToolRegistry, ToolResult

from agents.prompts import ESCALATION_PROMPT, wrap_untrusted
from agents.rules import policy_escalation

LOW_CONFIDENCE_THRESHOLD = 0.6


@dataclass(frozen=True, slots=True)
class EscalationAgentResult:
    """Final policy-safe decision with trace-ready model metadata."""

    output: EscalationDecision
    tool_calls: tuple[ToolResult, ...]
    usage: TokenUsage
    duration_ms: int
    llm_duration_ms: int
    estimated_cost: Decimal
    provider: str
    model: str
    attempts: int
    rule_applied: bool


def _prompt(
    subject: str,
    body: str,
    severity: Severity,
    diagnosis_confidence: float,
    category: TicketCategory | None,
    plan_name: str | None,
    attributes: Mapping[str, Any],
) -> str:
    trusted_context = {
        "category": category.value if category is not None else None,
        "diagnosis_confidence": diagnosis_confidence,
        "plan_name": plan_name,
        "severity": severity.value,
    }
    return "\n".join(
        (
            f"Trusted workflow context: {json.dumps(trusted_context, sort_keys=True)}",
            wrap_untrusted(subject, source="ticket_subject"),
            wrap_untrusted(body, source="ticket_body"),
            wrap_untrusted(
                json.dumps(dict(attributes), default=str, sort_keys=True),
                source="ticket_attributes",
            ),
        )
    )


def _policy_decision(
    *,
    team: str,
    reason: str,
    priority: Severity,
    policy_rules: tuple[str, ...],
) -> EscalationDecision:
    return EscalationDecision(
        escalation_required=True,
        team=team,
        reason=reason,
        policy_rules=list(policy_rules),
        priority=priority,
        confidence=1.0,
    )


def _model_decision(
    decision: EscalationDecision,
    *,
    severity: Severity,
    diagnosis_confidence: float,
) -> EscalationDecision:
    if not decision.escalation_required:
        return decision.model_copy(update={"team": None, "policy_rules": []})

    high_impact_uncertainty = (
        severity in {Severity.HIGH, Severity.CRITICAL}
        and diagnosis_confidence < LOW_CONFIDENCE_THRESHOLD
    )
    if high_impact_uncertainty:
        return decision.model_copy(update={"policy_rules": []})
    return decision.model_copy(
        update={
            "escalation_required": False,
            "team": None,
            "reason": (
                "Model escalation was not accepted because the case is not both high-impact "
                "and diagnostically uncertain."
            ),
            "policy_rules": [],
        }
    )


class EscalationAgent:
    """Apply mandatory policy, constrain grey-area judgment, and route safely (F10/N4)."""

    def __init__(
        self,
        registry: ToolRegistry,
        llm: StructuredLLM | None = None,
    ) -> None:
        self._registry = registry
        self._llm = llm

    async def assess_risk(
        self,
        subject: str,
        body: str,
        severity: Severity | str,
        diagnosis_confidence: float,
        *,
        category: TicketCategory | str | None = None,
        plan_name: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> EscalationAgentResult:
        """Return a structured escalation decision whose policy cases cannot be overridden."""

        normalized_subject = " ".join(subject.split())
        normalized_body = " ".join(body.split())
        if not normalized_subject or not normalized_body:
            raise ValueError("ticket subject and body must not be blank")
        if not 0 <= diagnosis_confidence <= 1:
            raise ValueError("diagnosis confidence must be between zero and one")
        active_severity = severity if isinstance(severity, Severity) else Severity(severity)
        active_category = (
            category
            if category is None or isinstance(category, TicketCategory)
            else TicketCategory(category)
        )
        safe_attributes = attributes or {}
        text = f"{normalized_subject} {normalized_body}"

        started = perf_counter()
        call = await call_structured(
            EscalationDecision,
            _prompt(
                normalized_subject,
                normalized_body,
                active_severity,
                diagnosis_confidence,
                active_category,
                plan_name,
                safe_attributes,
            ),
            system_prompt=ESCALATION_PROMPT,
            llm=self._llm,
        )
        policy = policy_escalation(
            text,
            plan_name,
            category=active_category,
            attributes=safe_attributes,
        )
        if policy.escalation_required:
            if policy.team is None or policy.reason is None or policy.priority is None:
                raise AssertionError("required policy escalation must be complete")
            output = _policy_decision(
                team=policy.team,
                reason=policy.reason,
                priority=policy.priority,
                policy_rules=policy.policy_rules,
            )
        else:
            output = _model_decision(
                call.output,
                severity=active_severity,
                diagnosis_confidence=diagnosis_confidence,
            )
        return EscalationAgentResult(
            output=output,
            tool_calls=(),
            usage=call.usage,
            duration_ms=max(0, round((perf_counter() - started) * 1_000)),
            llm_duration_ms=call.duration_ms,
            estimated_cost=call.estimated_cost,
            provider=call.provider,
            model=call.model,
            attempts=call.attempts,
            rule_applied=policy.escalation_required,
        )

    async def run(
        self,
        subject: str,
        body: str,
        severity: Severity | str,
        diagnosis_confidence: float,
        **context: Any,
    ) -> EscalationAgentResult:
        """Compatibility alias for the specialist's assessment entry point."""

        return await self.assess_risk(
            subject,
            body,
            severity,
            diagnosis_confidence,
            **context,
        )

    async def escalate(
        self,
        ticket_id: str,
        decision: EscalationDecision,
        *,
        workflow_id: str | None = None,
    ) -> ToolResult:
        """Execute a required escalation only through the shared tool registry."""

        normalized_ticket_id = ticket_id.strip()
        if not normalized_ticket_id:
            raise ValueError("ticket id must not be blank")
        if not decision.escalation_required or decision.team is None:
            raise ValueError("an escalation-required decision with a team is required")
        arguments: dict[str, Any] = {
            "ticket_id": normalized_ticket_id,
            "team": decision.team,
            "reason": decision.reason[:2_000],
            "policy_rules": decision.policy_rules,
            "priority": decision.priority.value,
        }
        if workflow_id is not None:
            normalized_workflow_id = workflow_id.strip()
            if not normalized_workflow_id:
                raise ValueError("workflow id must not be blank")
            arguments["workflow_id"] = normalized_workflow_id
        return await self._registry.execute("create_escalation", arguments)
