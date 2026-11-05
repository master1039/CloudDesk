"""Deterministic policy and agent orchestration for CloudDesk."""

from .prompts import (
    SECURITY_PREAMBLE,
    SUPERVISOR_CLASSIFICATION_PROMPT,
    SUPERVISOR_SEVERITY_PROMPT,
    SUPERVISOR_SUMMARY_PROMPT,
    wrap_untrusted,
)
from .rules import (
    ESCALATION_RULES,
    CategoryDecision,
    EscalationPolicyDecision,
    EscalationRule,
    SeverityDecision,
    matching_escalation_rules,
    policy_escalation,
    rule_category,
    rule_severity,
)

__all__ = [
    "ESCALATION_RULES",
    "SECURITY_PREAMBLE",
    "SUPERVISOR_CLASSIFICATION_PROMPT",
    "SUPERVISOR_SEVERITY_PROMPT",
    "SUPERVISOR_SUMMARY_PROMPT",
    "CategoryDecision",
    "EscalationPolicyDecision",
    "EscalationRule",
    "SeverityDecision",
    "matching_escalation_rules",
    "policy_escalation",
    "rule_category",
    "rule_severity",
    "wrap_untrusted",
]
