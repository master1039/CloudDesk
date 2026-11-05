"""P9-8 contract tests for the initial offline evaluation dataset."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.schemas.common import Severity, TicketCategory

from agents.rules import policy_escalation

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = PROJECT_ROOT / "datasets" / "eval_cases.json"
KNOWLEDGE_DIR = PROJECT_ROOT / "sample_data" / "knowledge_base"
CASE_ID_PATTERN = re.compile(r"^eval-\d{3}$")
REQUIRED_FIELDS = {
    "id",
    "subject",
    "body",
    "plan_name",
    "attributes",
    "expected_category",
    "expected_severity",
    "expected_article_ids",
    "expected_grounding_terms",
    "expected_escalation",
    "expected_team",
    "expected_policy_rules",
}


def _cases() -> list[dict[str, Any]]:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    return payload


def test_eval_dataset_is_bounded_unique_and_covers_every_ticket_category() -> None:
    cases = _cases()
    ids = [case["id"] for case in cases]

    assert 10 <= len(cases) <= 100
    assert len(ids) == len(set(ids))
    assert all(CASE_ID_PATTERN.fullmatch(case_id) for case_id in ids)
    assert {TicketCategory(case["expected_category"]) for case in cases} == set(TicketCategory)


def test_every_eval_case_has_a_valid_strict_contract() -> None:
    for case in _cases():
        assert set(case) == REQUIRED_FIELDS
        assert case["subject"].strip()
        assert case["body"].strip()
        assert case["plan_name"] in {"free", "pro", "business", "enterprise"}
        assert isinstance(case["attributes"], dict)
        TicketCategory(case["expected_category"])
        Severity(case["expected_severity"])
        assert case["expected_article_ids"]
        assert len(case["expected_article_ids"]) == len(set(case["expected_article_ids"]))
        assert case["expected_grounding_terms"]
        assert all(term.strip() for term in case["expected_grounding_terms"])
        assert isinstance(case["expected_escalation"], bool)
        assert isinstance(case["expected_policy_rules"], list)
        if case["expected_escalation"]:
            assert isinstance(case["expected_team"], str)
            assert case["expected_team"].strip()
            assert case["expected_policy_rules"]
        else:
            assert case["expected_team"] is None
            assert case["expected_policy_rules"] == []


def test_eval_retrieval_and_grounding_expectations_reference_checked_in_knowledge() -> None:
    article_text = {
        path.stem: path.read_text(encoding="utf-8").casefold()
        for path in KNOWLEDGE_DIR.glob("*.md")
    }
    referenced_articles = {
        article_id for case in _cases() for article_id in case["expected_article_ids"]
    }

    assert referenced_articles == set(article_text)

    for case in _cases():
        for article_id in case["expected_article_ids"]:
            assert article_id in article_text, f"{case['id']} references unknown article {article_id}"
        combined = "\n".join(article_text[item] for item in case["expected_article_ids"])
        for term in case["expected_grounding_terms"]:
            assert term.casefold() in combined, f"{case['id']} has unsupported term {term!r}"


def test_f10_eval_policy_expectations_match_the_deterministic_rule_table() -> None:
    for case in _cases():
        decision = policy_escalation(
            f"{case['subject']} {case['body']}",
            case["plan_name"],
            category=case["expected_category"],
            attributes=case["attributes"],
        )

        assert decision.escalation_required is case["expected_escalation"], case["id"]
        assert decision.team == case["expected_team"], case["id"]
        assert list(decision.policy_rules) == case["expected_policy_rules"], case["id"]
