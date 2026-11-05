"""P9-7 offline tests for policy-first escalation assessment and routing (F10/N4/F14)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from app.core.llm import FakeLLM
from app.schemas.common import Severity, TicketCategory
from app.schemas.workflow import EscalationDecision
from app.tools import ToolRegistry
from langchain_core.tools import tool

from agents.specialists import EscalationAgent


def _registry(calls: list[dict[str, Any]] | None = None) -> ToolRegistry:
    @tool("create_escalation")
    async def create_escalation(
        ticket_id: str,
        team: str,
        reason: str,
        policy_rules: list[str],
        priority: str,
        workflow_id: str | None = None,
    ) -> Mapping[str, Any]:
        """Record a deterministic offline escalation."""

        arguments = {
            "ticket_id": ticket_id,
            "team": team,
            "reason": reason,
            "policy_rules": policy_rules,
            "priority": priority,
            "workflow_id": workflow_id,
        }
        if calls is not None:
            calls.append(arguments)
        return {**arguments, "created": True}

    return ToolRegistry([create_escalation])


async def test_f10_policy_case_overrides_conflicting_model_route() -> None:
    llm = FakeLLM(
        scripted_responses={
            "EscalationDecision": [
                {
                    "escalation_required": True,
                    "team": "Customer Success",
                    "reason": "Model selected a non-policy destination.",
                    "policy_rules": ["invented_rule"],
                    "priority": "low",
                    "confidence": 0.99,
                }
            ]
        }
    )

    result = await EscalationAgent(_registry(), llm).assess_risk(
        "Suspicious logins, possible breach",
        "Successful logins came from countries where we have no staff.",
        Severity.HIGH,
        0.9,
        category=TicketCategory.SECURITY,
        attributes={"possible_breach": True},
    )

    assert result.output.escalation_required is True
    assert result.output.team == "Security Response"
    assert result.output.priority is Severity.CRITICAL
    assert result.output.policy_rules == ["security_incident"]
    assert result.output.confidence == 1
    assert result.rule_applied is True
    assert result.tool_calls == ()
    assert result.usage.total_tokens > 0
    assert result.estimated_cost == 0


async def test_model_escalation_is_rejected_without_high_impact_uncertainty() -> None:
    llm = FakeLLM(
        scripted_responses={
            "EscalationDecision": [
                {
                    "escalation_required": True,
                    "team": "Product Support",
                    "reason": "The model recommends specialist review.",
                    "policy_rules": ["model_invented"],
                    "priority": "medium",
                    "confidence": 0.8,
                }
            ]
        }
    )

    result = await EscalationAgent(_registry(), llm).run(
        "Dark mode request",
        "Please add a dark theme.",
        Severity.LOW,
        0.9,
        category=TicketCategory.FEATURE_REQUEST,
    )

    assert result.output.escalation_required is False
    assert result.output.team is None
    assert result.output.policy_rules == []
    assert result.rule_applied is False


async def test_grey_area_model_escalation_requires_high_severity_and_low_diagnosis_confidence() -> None:
    llm = FakeLLM(
        scripted_responses={
            "EscalationDecision": [
                {
                    "escalation_required": True,
                    "team": "Platform Support",
                    "reason": "High-impact symptoms remain diagnostically uncertain.",
                    "policy_rules": ["not_a_real_policy"],
                    "priority": "high",
                    "confidence": 0.7,
                }
            ]
        }
    )

    result = await EscalationAgent(_registry(), llm).assess_risk(
        "Intermittent workspace failure",
        "Several core operations fail intermittently without a known cause.",
        Severity.HIGH,
        0.4,
        category=TicketCategory.OTHER,
    )

    assert result.output.escalation_required is True
    assert result.output.team == "Platform Support"
    assert result.output.policy_rules == []
    assert result.rule_applied is False


async def test_escalation_tool_runs_only_through_registry() -> None:
    calls: list[dict[str, Any]] = []
    agent = EscalationAgent(_registry(calls), FakeLLM())
    decision = EscalationDecision(
        escalation_required=True,
        team="Storage Reliability",
        reason="Potential data loss requires specialist recovery.",
        policy_rules=["data_loss"],
        priority=Severity.CRITICAL,
        confidence=1,
    )

    result = await agent.escalate("CD-1006", decision, workflow_id="workflow-6")

    assert result.ok is True
    assert result.name == "create_escalation"
    assert result.approval_required is False
    assert calls == [
        {
            "ticket_id": "CD-1006",
            "team": "Storage Reliability",
            "reason": "Potential data loss requires specialist recovery.",
            "policy_rules": ["data_loss"],
            "priority": "critical",
            "workflow_id": "workflow-6",
        }
    ]


async def test_escalation_tool_rejects_a_non_escalation_decision() -> None:
    decision = EscalationDecision(
        escalation_required=False,
        team=None,
        reason="No escalation is required.",
        priority=Severity.LOW,
        confidence=0.9,
    )

    with pytest.raises(ValueError, match="escalation-required"):
        await EscalationAgent(_registry(), FakeLLM()).escalate("CD-1010", decision)
