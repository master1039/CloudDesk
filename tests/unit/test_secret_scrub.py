"""P7-4 tests for deterministic secret removal before durable memory (N7)."""

from __future__ import annotations

import pytest
from app.core.guardrails import REDACTION_MARKER, scrub, secret_signals


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Key: sk-proj-abcdefghijklmnopqrstuvwxyz", f"Key: {REDACTION_MARKER}"),
        ("AWS AKIAIOSFODNN7EXAMPLE", f"AWS {REDACTION_MARKER}"),
        (
            "password=correct-horse-battery-staple",
            f"password={REDACTION_MARKER}",
        ),
        (
            "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123456",
            f"token {REDACTION_MARKER}",
        ),
        ("Card 4111 1111 1111 1111", f"Card {REDACTION_MARKER}"),
        (
            "Open https://agent:supersecret@support.example/private now.",
            f"Open {REDACTION_MARKER} now.",
        ),
    ],
)
def test_n7_scrub_removes_each_secret_class(raw: str, expected: str) -> None:
    result = scrub(raw)
    assert result == expected
    assert secret_signals(result) == ()


def test_n7_scrub_removes_complete_multiline_private_key_block() -> None:
    private_key = (
        "-----BEGIN PRIVATE KEY-----\n"
        "c3VwZXItc2VjcmV0LWtleS1tYXRlcmlhbA==\n"
        "-----END PRIVATE KEY-----"
    )
    text = f"Do not store this:\n{private_key}\nInvestigation complete."

    result = scrub(text)

    assert result == f"Do not store this:\n{REDACTION_MARKER}\nInvestigation complete."
    assert "PRIVATE KEY" not in result
    assert "c3Vw" not in result


def test_overlapping_named_and_api_key_patterns_produce_one_marker() -> None:
    result = scrub("api_key=sk-proj-abcdefghijklmnopqrstuvwxyz")
    assert result == f"api_key={REDACTION_MARKER}"
    assert result.count(REDACTION_MARKER) == 1


def test_adjacent_and_repeated_secrets_are_removed_in_stable_order() -> None:
    text = (
        "password=correct-horse-battery-staple, "
        "card=4111-1111-1111-1111, "
        "password=another-secret-value"
    )
    result = scrub(text)

    assert result == (
        f"password={REDACTION_MARKER}, card={REDACTION_MARKER}, password={REDACTION_MARKER}"
    )
    assert secret_signals(result) == ()


def test_scrub_is_idempotent() -> None:
    once = scrub("password=correct-horse-battery-staple")
    assert scrub(once) == once


@pytest.mark.parametrize(
    "safe_text",
    [
        "No sensitive values were included.",
        "The password reset was completed successfully.",
        "Rotate the API key from account settings.",
        "Invoice 202611040001 is ready.",
        "Card ending in 1111 was not charged.",
        "Reference 1234 5678 9012 3456 is not a valid card number.",
        f"Already removed: {REDACTION_MARKER}",
    ],
)
def test_scrub_preserves_benign_support_content(safe_text: str) -> None:
    assert scrub(safe_text) == safe_text


def test_scrub_handles_empty_text() -> None:
    assert scrub("") == ""
