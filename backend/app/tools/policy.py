"""Deterministic approval policy for every CloudDesk support tool (F9)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class ToolRule:
    """Static safety classification for one tool capability."""

    writes: bool
    requires_approval: bool
    reason: str
    known: bool = True


DEFAULT_TOOL_RULES: Mapping[str, ToolRule] = MappingProxyType(
    {
        "get_customer": ToolRule(False, False, "Read-only customer lookup"),
        "get_subscription": ToolRule(False, False, "Read-only subscription lookup"),
        "get_ticket_history": ToolRule(False, False, "Read-only ticket-history lookup"),
        "search_docs": ToolRule(False, False, "Read-only knowledge search"),
        "check_service_status": ToolRule(False, False, "Read-only service-status lookup"),
        "update_ticket": ToolRule(True, False, "Routine support ticket update"),
        "reset_demo_setting": ToolRule(True, True, "Workspace setting changes need approval"),
        "create_refund_request": ToolRule(True, True, "Money movement needs approval"),
        "create_escalation": ToolRule(True, False, "Escalation is the safe fallback path"),
    }
)

UNKNOWN_TOOL_RULE = ToolRule(
    writes=True,
    requires_approval=True,
    reason="Unclassified tools require explicit approval",
    known=False,
)


class ToolPolicy:
    """Resolve tool safety without consulting an LLM or executing the tool."""

    def __init__(self, rules: Mapping[str, ToolRule] | None = None) -> None:
        self._rules = MappingProxyType(dict(rules or DEFAULT_TOOL_RULES))

    @property
    def rules(self) -> Mapping[str, ToolRule]:
        return self._rules

    def rule_for(self, name: str) -> ToolRule:
        """Return a conservative default for every unclassified name."""

        return self._rules.get(name, UNKNOWN_TOOL_RULE)

    def is_known(self, name: str) -> bool:
        return self.rule_for(name).known

    def requires_approval(self, name: str) -> bool:
        return self.rule_for(name).requires_approval

    def writes(self, name: str) -> bool:
        return self.rule_for(name).writes
