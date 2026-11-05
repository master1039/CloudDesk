"""P9-6 offline tests for grounded, validated, deterministic resolution plans."""

from __future__ import annotations

from app.core.guardrails import OutputRisk, OutputViolationCode
from app.core.llm import FakeLLM
from app.schemas.common import TicketCategory
from app.schemas.workflow import Diagnosis, Evidence

from agents.specialists import ResolutionAgent


def _diagnosis() -> Diagnosis:
    return Diagnosis(
        probable_causes=["The API client exceeded the documented request limit."],
        steps=["1. Honor Retry-After and use bounded exponential backoff."],
        confidence=0.9,
    )


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            id="api-rate-limits#retry:0",
            title="API rate limits",
            source="kb://api-rate-limits#retry",
            snippet="Honor Retry-After and use bounded exponential backoff.",
            score=0.95,
            url="/knowledge/api-rate-limits",
            article_id="api-rate-limits",
        )
    ]


async def test_f8_resolution_is_grounded_validated_and_actions_are_deterministic() -> None:
    llm = FakeLLM(
        scripted_responses={
            "ResolutionPlan": [
                {
                    "summary": "Apply documented API retry handling.",
                    "customer_reply": "Please honor Retry-After before retrying the request.",
                    "internal_notes": "Diagnosis is consistent with rate limiting.",
                    "actions": [
                        {
                            "tool": "delete_customer",
                            "arguments": {"customer_id": "other"},
                            "requires_approval": False,
                            "reason": "Model invented action.",
                        }
                    ],
                }
            ]
        }
    )

    result = await ResolutionAgent(llm).run(
        "API returns 429",
        "Our nightly sync is rate limited.",
        TicketCategory.API_FAILURE,
        _diagnosis(),
        ticket_id="CD-1003",
        evidence=_evidence(),
    )

    assert result.validation.valid is True
    assert result.validation.risk is OutputRisk.LOW
    assert "[API rate limits](/knowledge/api-rate-limits)" in result.output.customer_reply
    assert [action.tool for action in result.output.actions] == ["update_ticket"]
    assert result.output.actions[0].requires_approval is False
    assert result.output.actions[0].arguments["ticket_id"] == "CD-1003"
    assert result.usage.total_tokens > 0
    assert result.estimated_cost == 0
    assert result.provider == "fake"


async def test_f9_refund_and_setting_reset_are_planned_as_approval_gated() -> None:
    agent = ResolutionAgent(FakeLLM())

    actions = agent.plan_actions(
        "CD-1002",
        TicketCategory.BILLING,
        "Request a seat refund and restore the demo setting.",
        customer_id="customer-2",
        refund_amount="29.00",
        setting_reset={
            "workspace_id": "workspace-2",
            "setting": "sharing.external",
            "value": False,
        },
    )

    assert [action.tool for action in actions] == [
        "update_ticket",
        "create_refund_request",
        "reset_demo_setting",
    ]
    assert [action.requires_approval for action in actions] == [False, True, True]
    assert actions[1].arguments["idempotency_key"] == "CD-1002:refund:29.00:USD"


async def test_n5_unsafe_customer_reply_is_blocked_and_reported_without_echoing_secret() -> None:
    llm = FakeLLM(
        scripted_responses={
            "ResolutionPlan": [
                {
                    "summary": "Proposed reply requires review.",
                    "customer_reply": "Use api_key=super-secret-value at http://admin.internal/run",
                    "internal_notes": "Unsafe output test.",
                    "actions": [],
                }
            ]
        }
    )

    result = await ResolutionAgent(llm).run(
        "API access",
        "Help with API access.",
        TicketCategory.API_FAILURE,
        _diagnosis(),
        ticket_id="CD-1013",
    )

    assert result.validation.valid is False
    assert result.validation.risk is OutputRisk.HIGH
    assert {item.code for item in result.validation.violations} == {
        OutputViolationCode.INTERNAL_URL,
        OutputViolationCode.SECRET,
    }
    assert "super-secret-value" not in result.output.customer_reply
    assert result.output.customer_reply.endswith("requires agent review.")


async def test_other_customer_identifier_blocks_reply() -> None:
    llm = FakeLLM(
        scripted_responses={
            "ResolutionPlan": [
                {
                    "summary": "Account review.",
                    "customer_reply": "The affected account is customer-other-99.",
                    "internal_notes": "Identifier validation test.",
                    "actions": [],
                }
            ]
        }
    )

    result = await ResolutionAgent(llm).run(
        "Account review",
        "Please review my account.",
        TicketCategory.ACCOUNT,
        _diagnosis(),
        ticket_id="CD-1014",
        current_customer_identifiers=("customer-current-1",),
        other_customer_identifiers=("customer-other-99",),
    )

    assert result.validation.valid is False
    assert result.validation.violations[0].code is OutputViolationCode.OTHER_CUSTOMER_DATA
    assert "customer-other-99" not in result.output.customer_reply
