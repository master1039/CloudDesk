"""P9-2 tests for the injection-safe support supervisor (F2/F3/F11/N4/F14)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.core.llm import FakeLLM
from app.schemas.common import Severity, TicketCategory
from app.schemas.workflow import Classification

from agents.specialists.supervisor import SupervisorAgent

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _tickets() -> list[dict]:
    return json.loads((PROJECT_ROOT / "sample_data" / "tickets.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("ticket", _tickets(), ids=lambda ticket: ticket["display_id"])
async def test_f2_supervisor_classifies_all_demo_tickets_offline(ticket: dict) -> None:
    result = await SupervisorAgent(FakeLLM()).understand(
        ticket["subject"],
        ticket["body"],
        attributes=ticket.get("attributes"),
    )

    assert result.output.category is TicketCategory(ticket["category"])
    assert "\n" not in result.output.summary
    assert "<untrusted_content" not in result.output.summary
    assert result.provider == "fake"
    assert result.estimated_cost == 0


async def test_n4_supervisor_flags_injection_and_enforces_security_category() -> None:
    ticket = next(ticket for ticket in _tickets() if ticket["display_id"] == "CD-1013")
    llm = FakeLLM(
        scripted_responses={
            "Classification": [
                {"category": "other", "summary": "Suspicious request", "confidence": 0.7}
            ]
        }
    )

    result = await SupervisorAgent(llm).understand(ticket["subject"], ticket["body"])

    assert result.output.category is TicketCategory.SECURITY
    assert "instruction_override" in result.injection_signals
    assert "bulk_data_exfiltration" in result.injection_signals
    assert "prompt_injection" in result.policy_rules
    assert result.rule_applied is True


async def test_f3_policy_raises_security_severity_and_preserves_model_metadata() -> None:
    llm = FakeLLM(
        scripted_responses={
            "SeverityAssessment": [
                {"severity": "low", "reason": "Model saw limited impact.", "confidence": 0.6}
            ]
        }
    )

    result = await SupervisorAgent(llm).assess_severity(
        "Suspicious logins, possible breach",
        "Successful logins came from unknown countries.",
        TicketCategory.SECURITY,
        attributes={"possible_breach": True},
    )

    assert result.output.severity is Severity.CRITICAL
    assert "security_incident" in result.policy_rules
    assert result.rule_applied is True
    assert result.output.confidence == 0.6
    assert result.usage.total_tokens > 0


async def test_f3_rules_never_lower_a_model_severity() -> None:
    llm = FakeLLM(
        scripted_responses={
            "SeverityAssessment": [
                {"severity": "high", "reason": "Model detected broad impact.", "confidence": 0.8}
            ]
        }
    )

    result = await SupervisorAgent(llm).assess_severity(
        "Dark mode request",
        "Please add a dark theme.",
        TicketCategory.FEATURE_REQUEST,
    )

    assert result.output.severity is Severity.HIGH
    assert result.rule_applied is False


async def test_f11_supervisor_returns_structured_ticket_run_summary() -> None:
    result = await SupervisorAgent(FakeLLM()).ticket_summary(
        "Customer could not sign in.",
        "MFA recovery guidance was prepared.",
        customer_follow_up="Confirm that sign-in succeeds.",
    )

    assert result.output.summary
    assert result.output.outcome
    assert result.provider == "fake"
    assert result.estimated_cost == 0


@pytest.mark.parametrize(
    ("subject", "body"),
    [("", "Body"), ("Subject", "   ")],
)
async def test_supervisor_rejects_blank_ticket_fields(subject: str, body: str) -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        await SupervisorAgent(FakeLLM()).understand(subject, body)


async def test_category_policy_overrides_payment_dispute_even_when_model_is_wrong() -> None:
    classification = Classification(category="other", summary="A charge is disputed", confidence=0.8)
    llm = FakeLLM(
        scripted_responses={"Classification": [classification.model_dump(mode="json")]}
    )

    result = await SupervisorAgent(llm).understand(
        "Unauthorized charge",
        "We formally dispute this payment.",
        attributes={"payment_dispute": True},
    )

    assert result.output.category is TicketCategory.BILLING
    assert result.policy_rules == ("payment_dispute",)
    assert result.rule_applied is True
