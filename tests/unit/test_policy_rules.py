"""P7-1 tests for deterministic escalation and raise-only severity policy (F3/F10)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from app.schemas.common import Severity

from agents.rules import (
    ESCALATION_RULES,
    matching_escalation_rules,
    policy_escalation,
    rule_severity,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"


def _load_json(name: str) -> list[dict[str, Any]]:
    return json.loads((SAMPLE_DATA_DIR / name).read_text(encoding="utf-8"))


def _demo_cases() -> dict[str, tuple[dict[str, Any], str]]:
    tickets = _load_json("tickets.json")
    subscriptions = {
        item["customer_ref"]: item["plan"] for item in _load_json("subscriptions.json")
    }
    return {
        ticket["display_id"]: (ticket, subscriptions[ticket["customer_ref"]]) for ticket in tickets
    }


@pytest.mark.parametrize(
    ("ticket_id", "rule_id", "team", "priority"),
    [
        ("CD-1001", "enterprise_outage", "Identity Operations", Severity.HIGH),
        ("CD-1005", "security_incident", "Security Response", Severity.CRITICAL),
        ("CD-1006", "data_loss", "Storage Reliability", Severity.CRITICAL),
        ("CD-1009", "account_deletion", "Privacy Operations", Severity.HIGH),
        ("CD-1011", "payment_dispute", "Billing Risk", Severity.HIGH),
    ],
)
def test_f10_demo_policy_cases_escalate_without_a_model(
    ticket_id: str,
    rule_id: str,
    team: str,
    priority: Severity,
) -> None:
    ticket, plan = _demo_cases()[ticket_id]
    text = f"{ticket['subject']} {ticket['body']}"

    decision = policy_escalation(
        text,
        plan,
        category=ticket["category"],
        attributes=ticket.get("attributes"),
    )

    assert decision.escalation_required is True
    assert decision.team == team
    assert decision.priority == priority
    assert decision.policy_rules[0] == rule_id


def test_all_required_policy_cases_have_named_routes() -> None:
    examples = {
        "security_incident": ("We suspect a security incident and breach", "business"),
        "data_loss": ("Several files disappeared from the folder", "business"),
        "account_deletion": ("Please permanently erase all our data", "business"),
        "payment_dispute": ("We formally dispute this charge", "pro"),
        "legal_request": ("We received a regulatory authority request", "business"),
        "enterprise_outage": ("Our entire team cannot sign in", "enterprise"),
    }

    assert {rule.rule_id for rule in ESCALATION_RULES} == set(examples)
    for rule_id, (text, plan) in examples.items():
        matches = matching_escalation_rules(text, plan)
        match = next(rule for rule in matches if rule.rule_id == rule_id)
        assert match.team.strip()
        assert match.reason.strip()


def test_enterprise_outage_requires_both_scope_and_enterprise_plan() -> None:
    assert matching_escalation_rules("Our entire team cannot sign in", "pro") == ()
    matches = matching_escalation_rules("Our entire team cannot sign in", "enterprise")
    assert [rule.rule_id for rule in matches] == ["enterprise_outage"]


def test_refund_request_is_not_misclassified_as_a_payment_dispute() -> None:
    ticket, plan = _demo_cases()["CD-1002"]
    decision = policy_escalation(
        f"{ticket['subject']} {ticket['body']}",
        plan,
        category=ticket["category"],
        attributes=ticket.get("attributes"),
    )
    assert decision.escalation_required is False


@pytest.mark.parametrize("model_severity", list(Severity))
def test_f3_rules_never_lower_model_severity(model_severity: Severity) -> None:
    decision = rule_severity(
        model_severity,
        "Potential security breach",
        category="security",
    )
    assert decision.severity in {model_severity, Severity.CRITICAL}
    assert [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL].index(
        decision.severity
    ) >= [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL].index(model_severity)


def test_f3_security_and_data_loss_raise_severity_to_critical() -> None:
    security = rule_severity(Severity.LOW, "Suspicious logins suggest a breach")
    data_loss = rule_severity(Severity.MEDIUM, "Files disappeared from the folder")

    assert security.severity == Severity.CRITICAL
    assert security.raised is True
    assert data_loss.severity == Severity.CRITICAL
    assert data_loss.raised is True


def test_f3_cd_1010_feature_request_stays_low() -> None:
    ticket, plan = _demo_cases()["CD-1010"]
    decision = rule_severity(
        Severity.LOW,
        f"{ticket['subject']} {ticket['body']}",
        plan_name=plan,
        category=ticket["category"],
        attributes=ticket.get("attributes"),
    )

    assert decision.severity == Severity.LOW
    assert decision.raised is False
    assert decision.policy_rules == ()


def test_multiple_matches_use_precedence_for_team_and_maximum_for_severity() -> None:
    decision = policy_escalation(
        "A security breach also caused data loss",
        "enterprise",
        attributes={"legal_request": True},
    )
    severity = rule_severity(
        Severity.LOW,
        "A security breach also caused data loss",
        plan_name="enterprise",
        attributes={"legal_request": True},
    )

    assert decision.team == "Security Response"
    assert decision.policy_rules == ("security_incident", "data_loss", "legal_request")
    assert severity.severity == Severity.CRITICAL
