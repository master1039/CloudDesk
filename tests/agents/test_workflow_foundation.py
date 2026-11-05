"""P9-1 tests for strict workflow schemas and the offline structured LLM boundary (F14)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.core.config import get_settings
from app.core.llm import (
    FakeLLM,
    LLMConfigurationError,
    StructuredOutputError,
    call_structured,
    get_llm,
)
from app.schemas.common import Severity, TicketCategory
from app.schemas.workflow import (
    Classification,
    Diagnosis,
    EscalationDecision,
    ResolutionPlan,
    SeverityAssessment,
    TicketRunSummary,
)
from pydantic import ValidationError


def test_workflow_schemas_are_strict_and_enforce_domain_bounds() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Classification(
            category="billing",
            summary="Billing question",
            confidence=0.9,
            hidden_reasoning="must never be accepted",
        )
    with pytest.raises(ValidationError):
        SeverityAssessment(severity="urgent", reason="Invalid enum", confidence=2)
    with pytest.raises(ValidationError, match="team"):
        EscalationDecision(
            escalation_required=True,
            team=None,
            reason="Policy escalation",
            confidence=1,
        )


async def test_f14_fake_llm_classifies_offline_with_zero_cost_and_usage() -> None:
    result = await call_structured(
        Classification,
        "Customer requests a refund for an unauthorized charge.",
        llm=FakeLLM(),
    )

    assert result.output.category is TicketCategory.BILLING
    assert "refund" in result.output.summary.casefold()
    assert result.provider == "fake"
    assert result.model == "fake"
    assert result.estimated_cost == Decimal(0)
    assert result.usage.prompt_tokens > 0
    assert result.usage.completion_tokens > 0
    assert result.usage.total_tokens == (
        result.usage.prompt_tokens + result.usage.completion_tokens
    )
    assert result.attempts == 1


@pytest.mark.parametrize(
    ("schema", "expected_type"),
    [
        (SeverityAssessment, SeverityAssessment),
        (Diagnosis, Diagnosis),
        (ResolutionPlan, ResolutionPlan),
        (EscalationDecision, EscalationDecision),
        (TicketRunSummary, TicketRunSummary),
    ],
)
async def test_fake_provider_has_valid_defaults_for_every_model_generated_contract(
    schema: type,
    expected_type: type,
) -> None:
    result = await call_structured(schema, "Dark mode feature request", llm=FakeLLM())

    assert isinstance(result.output, expected_type)
    assert result.estimated_cost == Decimal(0)
    if isinstance(result.output, SeverityAssessment):
        assert result.output.severity is Severity.LOW
    if isinstance(result.output, ResolutionPlan):
        assert result.output.actions == []


async def test_call_structured_retries_invalid_output_and_accumulates_usage() -> None:
    llm = FakeLLM(
        scripted_responses={
            "Classification": [
                {"category": "not-a-category", "summary": "invalid", "confidence": 1},
                {"category": "billing", "summary": "Valid result", "confidence": 0.9},
            ]
        }
    )

    result = await call_structured(Classification, "Billing issue", llm=llm)

    assert result.output.category is TicketCategory.BILLING
    assert result.attempts == 2
    assert result.usage.prompt_tokens >= 4
    assert result.estimated_cost == Decimal(0)


async def test_structured_failure_is_generic_and_does_not_echo_prompt_data() -> None:
    secret = "password=correct-horse-battery-staple"
    llm = FakeLLM(
        scripted_responses={
            "Classification": [
                {"invalid": secret},
                {"still_invalid": secret},
            ]
        }
    )

    with pytest.raises(StructuredOutputError) as captured:
        await call_structured(Classification, secret, llm=llm)

    assert secret not in str(captured.value)


def test_get_llm_selects_fake_without_api_key_and_fails_closed_for_other_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_llm.cache_clear()
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert isinstance(get_llm(), FakeLLM)

    get_llm.cache_clear()
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(LLMConfigurationError, match="LLM_API_KEY"):
        get_llm()

    get_llm.cache_clear()
    get_settings.cache_clear()
