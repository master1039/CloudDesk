"""P7-3 tests for the customer-visible output gate (N5)."""

from __future__ import annotations

import pytest
from app.core.guardrails import (
    OutputRisk,
    OutputViolationCode,
    secret_signals,
    validate_customer_output,
)


def _codes(text: str, **context: list[str]) -> tuple[OutputViolationCode, ...]:
    result = validate_customer_output(text, **context)
    return tuple(violation.code for violation in result.violations)


def test_n5_safe_grounded_customer_reply_is_allowed_at_low_risk() -> None:
    result = validate_customer_output(
        "We found an SSO configuration issue. Please refresh your metadata using "
        "https://help.clouddesk.example/knowledge/sso-troubleshooting.",
        current_customer_identifiers=["Asha Rao", "asha@acme.example", "Acme Analytics"],
        other_customer_identifiers=["Mateo Silva", "mateo@northstar.example"],
    )

    assert result.valid is True
    assert result.risk == OutputRisk.LOW
    assert result.violations == ()


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/admin",
        "http://backend:8000/internal",
        "https://10.20.30.40/debug",
        "https://192.168.1.5/logs",
        "https://service.internal/runbook",
        "file:///etc/clouddesk/config",
    ],
)
def test_n5_internal_and_local_urls_are_blocked_with_high_risk(url: str) -> None:
    result = validate_customer_output(f"Open {url} for more information.")

    assert result.valid is False
    assert result.risk == OutputRisk.HIGH
    assert _codes(f"Open {url} for more information.") == (OutputViolationCode.INTERNAL_URL,)


@pytest.mark.parametrize(
    ("secret", "signal"),
    [
        ("sk-proj-abcdefghijklmnopqrstuvwxyz", "openai_api_key"),
        ("AKIAIOSFODNN7EXAMPLE", "aws_access_key"),
        ("password=correct-horse-battery-staple", "named_secret"),
        ("-----BEGIN PRIVATE KEY-----", "private_key"),
        (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123456",
            "jwt",
        ),
        ("4111 1111 1111 1111", "card_number"),
        ("https://agent:supersecret@support.example/private", "url_credentials"),
    ],
)
def test_n5_secret_classes_are_blocked_without_echoing_values(secret: str, signal: str) -> None:
    result = validate_customer_output(f"Diagnostic value: {secret}")

    assert signal in secret_signals(secret)
    assert result.valid is False
    assert result.risk == OutputRisk.HIGH
    assert tuple(item.code for item in result.violations) == (OutputViolationCode.SECRET,)
    assert all(secret not in item.message for item in result.violations)


def test_n5_other_customer_data_is_blocked_but_current_customer_data_is_allowed() -> None:
    context = {
        "current_customer_identifiers": [
            "cust-acme",
            "Asha Rao",
            "asha@acme.example",
            "Acme Analytics",
        ],
        "other_customer_identifiers": [
            "cust-northstar",
            "Mateo Silva",
            "mateo@northstar.example",
            "Northstar Labs",
        ],
    }

    current = validate_customer_output("Hello Asha Rao at asha@acme.example.", **context)
    leaked = validate_customer_output(
        "We found a related record for mateo@northstar.example.", **context
    )

    assert current.valid is True
    assert leaked.valid is False
    assert leaked.risk == OutputRisk.HIGH
    assert tuple(item.code for item in leaked.violations) == (
        OutputViolationCode.OTHER_CUSTOMER_DATA,
    )
    assert all("mateo" not in item.message.casefold() for item in leaked.violations)


def test_overlapping_current_identifier_is_not_treated_as_other_customer_data() -> None:
    result = validate_customer_output(
        "Your workspace is Acme HQ.",
        current_customer_identifiers=["Acme HQ"],
        other_customer_identifiers=["Acme HQ"],
    )
    assert result.valid is True


def test_multiple_violations_are_deduplicated_and_remain_high_risk() -> None:
    result = validate_customer_output(
        "Visit http://backend:8000 and http://redis:6379. "
        "Use password=correct-horse-battery-staple and contact other@example.test.",
        other_customer_identifiers=["other@example.test"],
    )

    assert result.valid is False
    assert result.risk == "high"
    assert tuple(item.code for item in result.violations) == (
        OutputViolationCode.INTERNAL_URL,
        OutputViolationCode.SECRET,
        OutputViolationCode.OTHER_CUSTOMER_DATA,
    )


def test_empty_customer_output_is_invalid_and_high_risk() -> None:
    result = validate_customer_output("   ")
    assert result.valid is False
    assert result.risk == OutputRisk.HIGH
    assert tuple(item.code for item in result.violations) == (OutputViolationCode.EMPTY_OUTPUT,)


@pytest.mark.parametrize(
    "text",
    [
        "Your invoice number is 202611040001.",
        "Your card ending in 1111 was not charged.",
        "The password reset link is https://help.clouddesk.example/reset.",
        "The API key can be rotated from the account settings page.",
        "The documentation is at https://docs.clouddesk.example/api.",
    ],
)
def test_benign_support_content_does_not_trigger_secret_or_url_checks(text: str) -> None:
    result = validate_customer_output(text)
    assert result.valid is True
