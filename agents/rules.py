"""Deterministic escalation and raise-only severity policy (F3/F10)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.schemas.common import Severity, TicketCategory


@dataclass(frozen=True, slots=True)
class EscalationRule:
    """One explainable policy case with routing and minimum severity."""

    rule_id: str
    team: str
    reason: str
    minimum_severity: Severity
    patterns: tuple[str, ...]
    categories: tuple[TicketCategory, ...] = ()
    attribute_flags: tuple[str, ...] = ()
    required_plan: str | None = None

    def matches(
        self,
        text: str,
        plan_name: str | None,
        category: TicketCategory | None,
        attributes: Mapping[str, Any],
    ) -> bool:
        """Return a policy match; plan requirements gate all other signals."""

        normalized_plan = plan_name.strip().casefold() if plan_name else None
        if self.required_plan is not None and normalized_plan != self.required_plan:
            return False
        if category in self.categories:
            return True
        if any(attributes.get(flag) is True for flag in self.attribute_flags):
            return True
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in self.patterns)


# Declaration order is routing precedence when a case matches more than one policy.
ESCALATION_RULES: tuple[EscalationRule, ...] = (
    EscalationRule(
        rule_id="security_incident",
        team="Security Response",
        reason="Potential account compromise or security incident requires specialist response.",
        minimum_severity=Severity.CRITICAL,
        patterns=(
            r"\bsecurity incident\b",
            r"\b(possible |suspected )?breach\b",
            r"\bcompromised?\b",
            r"\bsuspicious (?:sign[ -]?ins?|logins?)\b",
            r"\bunauthori[sz]ed (?:access|login|sign[ -]?in)\b",
        ),
        categories=(TicketCategory.SECURITY,),
        attribute_flags=("possible_breach", "security_incident", "account_compromise"),
    ),
    EscalationRule(
        rule_id="data_loss",
        team="Storage Reliability",
        reason="Potential data loss requires preservation and recovery by storage specialists.",
        minimum_severity=Severity.CRITICAL,
        patterns=(
            r"\bdata loss\b",
            r"\bfiles? (?:are |were |have )?(?:missing|disappeared|lost|deleted)\b",
            r"\bfolders? (?:is |are |was |were )?(?:missing|empty|disappeared)\b",
            r"\bmissing (?:files?|folders?|content|data)\b",
        ),
        attribute_flags=("data_loss",),
    ),
    EscalationRule(
        rule_id="account_deletion",
        team="Privacy Operations",
        reason="Irreversible deletion and erasure requests require privacy review.",
        minimum_severity=Severity.HIGH,
        patterns=(
            r"\bdelete (?:my|our|the|this)?\s*(?:account|workspace|customer data)\b",
            r"\b(?:permanently )?erase\b.{0,40}\b(?:data|workspace|account)\b",
            r"\b(?:gdpr|privacy) (?:deletion|erasure|request)\b",
            r"\bright to (?:erasure|be forgotten)\b",
        ),
        attribute_flags=("deletion_request", "gdpr_erasure"),
    ),
    EscalationRule(
        rule_id="payment_dispute",
        team="Billing Risk",
        reason="Disputed or unauthorized charges must follow the billing-risk process.",
        minimum_severity=Severity.HIGH,
        patterns=(
            r"\bpayment dispute\b",
            r"\b(?:formally )?dispute(?:d|s|ing)? (?:a |the |this )?(?:payment|charge|invoice)\b",
            r"\bunauthori[sz]ed charge\b",
            r"\bchargeback\b",
        ),
        attribute_flags=("payment_dispute", "chargeback"),
    ),
    EscalationRule(
        rule_id="legal_request",
        team="Legal and Compliance",
        reason="Explicit legal or regulatory requests require compliance review.",
        minimum_severity=Severity.HIGH,
        patterns=(
            r"\blegal (?:request|action|hold|notice|demand)\b",
            r"\bsubpoena\b",
            r"\blawsuit\b",
            r"\b(?:regulator|regulatory authority|court order|attorney)\b",
        ),
        attribute_flags=("legal_request", "legal_hold", "regulatory_request"),
    ),
    EscalationRule(
        rule_id="enterprise_outage",
        team="Identity Operations",
        reason="An enterprise-wide outage requires coordinated incident response.",
        minimum_severity=Severity.HIGH,
        patterns=(
            r"\benterprise(?:-wide| wide) outage\b",
            r"\b(?:entire|whole) (?:team|company|organi[sz]ation)\b",
            r"\b(?:all|every) (?:users?|employees?|members?)\b.*\b(?:cannot|can't|unable)\b",
            r"\bcompany(?:-wide| wide)\b.*\b(?:outage|down|unavailable)\b",
        ),
        attribute_flags=("enterprise_outage",),
        required_plan="enterprise",
    ),
)

SEVERITY_RANK: Mapping[Severity, int] = MappingProxyType(
    {
        Severity.LOW: 0,
        Severity.MEDIUM: 1,
        Severity.HIGH: 2,
        Severity.CRITICAL: 3,
    }
)


@dataclass(frozen=True, slots=True)
class EscalationPolicyDecision:
    """Deterministic routing result consumed by the future escalation agent."""

    escalation_required: bool
    team: str | None
    reason: str | None
    priority: Severity | None
    policy_rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SeverityDecision:
    """Final severity plus the policy evidence that was applied."""

    severity: Severity
    reason: str
    raised: bool
    policy_rules: tuple[str, ...]


def _category(value: TicketCategory | str | None) -> TicketCategory | None:
    if value is None or isinstance(value, TicketCategory):
        return value
    try:
        return TicketCategory(value.strip().casefold())
    except ValueError:
        return None


def matching_escalation_rules(
    text: str,
    plan_name: str | None = None,
    *,
    category: TicketCategory | str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> tuple[EscalationRule, ...]:
    """Return every mandatory policy match in stable routing-precedence order."""

    normalized_text = " ".join(text.split())
    normalized_category = _category(category)
    safe_attributes = attributes or {}
    return tuple(
        rule
        for rule in ESCALATION_RULES
        if rule.matches(normalized_text, plan_name, normalized_category, safe_attributes)
    )


def policy_escalation(
    text: str,
    plan_name: str | None = None,
    *,
    category: TicketCategory | str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> EscalationPolicyDecision:
    """Resolve policy matches without a model call; the first match owns routing."""

    matches = matching_escalation_rules(
        text,
        plan_name,
        category=category,
        attributes=attributes,
    )
    if not matches:
        return EscalationPolicyDecision(False, None, None, None, ())
    primary = matches[0]
    priority = max(matches, key=lambda rule: SEVERITY_RANK[rule.minimum_severity]).minimum_severity
    return EscalationPolicyDecision(
        escalation_required=True,
        team=primary.team,
        reason=primary.reason,
        priority=priority,
        policy_rules=tuple(rule.rule_id for rule in matches),
    )


def rule_severity(
    model_severity: Severity | str,
    text: str = "",
    *,
    plan_name: str | None = None,
    category: TicketCategory | str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> SeverityDecision:
    """Apply deterministic minimums while never lowering the model severity."""

    current = model_severity if isinstance(model_severity, Severity) else Severity(model_severity)
    matches = matching_escalation_rules(
        text,
        plan_name,
        category=category,
        attributes=attributes,
    )
    policy_rules = tuple(rule.rule_id for rule in matches)
    if not matches:
        return SeverityDecision(
            severity=current,
            reason="Model severity retained; no deterministic policy rule matched.",
            raised=False,
            policy_rules=(),
        )

    minimum = max(matches, key=lambda rule: SEVERITY_RANK[rule.minimum_severity])
    if SEVERITY_RANK[minimum.minimum_severity] > SEVERITY_RANK[current]:
        return SeverityDecision(
            severity=minimum.minimum_severity,
            reason=f"Raised by deterministic policy rule: {minimum.rule_id}.",
            raised=True,
            policy_rules=policy_rules,
        )
    return SeverityDecision(
        severity=current,
        reason="Model severity retained; deterministic rules are not allowed to lower it.",
        raised=False,
        policy_rules=policy_rules,
    )
