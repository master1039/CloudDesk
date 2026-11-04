"""Deterministic security checks shared by CloudDesk workflow components."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import ip_address
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class InjectionPattern:
    """One strong prompt-injection signal with an auditable identifier."""

    signal: str
    pattern: str


INJECTION_PATTERNS: tuple[InjectionPattern, ...] = (
    InjectionPattern(
        "instruction_override",
        r"\b(?:ignore|disregard|forget|override|bypass)\b.{0,80}"
        r"\b(?:previous|prior|above|all|system|developer|safety|security)\b.{0,40}"
        r"\b(?:instructions?|rules?|polic(?:y|ies)|prompts?|messages?)\b",
    ),
    InjectionPattern(
        "role_hijack",
        r"\b(?:you are now|pretend to be|switch (?:your )?role|new persona)\b|"
        r"\bact as\b.{0,30}\b(?:system|developer|administrator|admin|root|unrestricted)\b",
    ),
    InjectionPattern(
        "prompt_exfiltration",
        r"\b(?:reveal|show|print|repeat|return|expose|leak)\b.{0,80}"
        r"\b(?:system|developer|hidden|internal)\b.{0,30}"
        r"\b(?:prompt|instructions?|message|rules?)\b",
    ),
    InjectionPattern(
        "bulk_data_exfiltration",
        r"\b(?:export|dump|list|retrieve|send|copy)\b.{0,60}"
        r"\b(?:all|every)\b.{0,40}"
        r"\b(?:customers?|users?|records?|secrets?|credentials?|keys?|data)\b",
    ),
    InjectionPattern(
        "tool_coercion",
        r"\b(?:call|invoke|run|execute)\b.{0,50}"
        r"\b(?:tool|function|command|shell|terminal|sql)\b",
    ),
    InjectionPattern(
        "delimiter_escape",
        r"</?untrusted_content\b|</?(?:system|developer)\b|\[/?INST\]|"
        r"#{2,}\s*(?:system|developer)\b",
    ),
    InjectionPattern(
        "explicit_prompt_injection",
        r"\bprompt[ -]?injection\b|\bjailbreak\b",
    ),
)

_ZERO_WIDTH_CHARACTERS = str.maketrans("", "", "\u200b\u200c\u200d\u2060\ufeff")


def _normalize_untrusted_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH_CHARACTERS)
    return " ".join(normalized.split())


def injection_signals(text: str) -> tuple[str, ...]:
    """Return stable signal names for strong prompt-injection patterns."""

    normalized = _normalize_untrusted_text(text)
    return tuple(
        candidate.signal
        for candidate in INJECTION_PATTERNS
        if re.search(candidate.pattern, normalized, flags=re.IGNORECASE)
    )


def scan_for_injection(text: str) -> bool:
    """Flag suspicious external text before it reaches any model prompt (N4)."""

    return bool(injection_signals(text))


@dataclass(frozen=True, slots=True)
class SecretPattern:
    """One secret class that must not appear in customer-visible output."""

    signal: str
    pattern: str


SECRET_PATTERNS: tuple[SecretPattern, ...] = (
    SecretPattern("openai_api_key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b"),
    SecretPattern("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b"),
    SecretPattern(
        "named_secret",
        r"\b(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|secret|password|passwd)\b"
        r"\s*[:=]\s*(?!\[REDACTED\])[^\s,;]{8,}",
    ),
    SecretPattern("private_key", r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    SecretPattern(
        "jwt",
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
    ),
    SecretPattern("card_number", r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"),
)


class OutputRisk(StrEnum):
    """Risk assigned to a customer-facing output validation result."""

    LOW = "low"
    HIGH = "high"


class OutputViolationCode(StrEnum):
    """Stable, non-sensitive reasons an output cannot be shown."""

    EMPTY_OUTPUT = "empty_output"
    INTERNAL_URL = "internal_url"
    SECRET = "secret"
    OTHER_CUSTOMER_DATA = "other_customer_data"


@dataclass(frozen=True, slots=True)
class OutputViolation:
    """A safe validation finding that never echoes the matched value."""

    code: OutputViolationCode
    message: str


@dataclass(frozen=True, slots=True)
class CustomerOutputValidation:
    """Structured gate checked before any reply is shown to a customer."""

    valid: bool
    risk: OutputRisk
    violations: tuple[OutputViolation, ...]


_URL_PATTERN = re.compile(r"\b(?:https?|ftp|file)://[^\s<>()]+", flags=re.IGNORECASE)
_INTERNAL_HOST_SUFFIXES = (".internal", ".local", ".localhost", ".corp", ".lan")


def _passes_luhn(candidate: str) -> bool:
    digits = [int(character) for character in candidate if character.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    total = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        value = digit
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def secret_signals(text: str) -> tuple[str, ...]:
    """Return secret classes without returning the sensitive values themselves."""

    signals: list[str] = []
    for candidate in SECRET_PATTERNS:
        matches = re.finditer(candidate.pattern, text, flags=re.IGNORECASE)
        if candidate.signal == "card_number":
            detected = any(_passes_luhn(match.group(0)) for match in matches)
        else:
            detected = next(matches, None) is not None
        if detected:
            signals.append(candidate.signal)

    for raw_url in _URL_PATTERN.findall(text):
        try:
            parsed = urlsplit(raw_url.rstrip(".,;:!?\"'"))
        except ValueError:
            continue
        if parsed.username or parsed.password:
            signals.append("url_credentials")
            break
    return tuple(signals)


def _is_internal_url(raw_url: str) -> bool:
    try:
        parsed = urlsplit(raw_url.rstrip(".,;:!?\"'"))
        hostname = (parsed.hostname or "").casefold()
    except ValueError:
        return True
    if parsed.scheme.casefold() == "file" or not hostname:
        return True
    if hostname == "localhost" or hostname.endswith(_INTERNAL_HOST_SUFFIXES):
        return True
    try:
        address = ip_address(hostname)
    except ValueError:
        return "." not in hostname
    return address.is_private or address.is_loopback or address.is_link_local


def _contains_identifier(text: str, identifier: str) -> bool:
    escaped = re.escape(identifier.casefold())
    return re.search(rf"(?<!\w){escaped}(?!\w)", text.casefold()) is not None


def _has_other_customer_data(
    text: str,
    current_customer_identifiers: Iterable[str],
    other_customer_identifiers: Iterable[str],
) -> bool:
    current = {
        identifier.strip().casefold()
        for identifier in current_customer_identifiers
        if len(identifier.strip()) >= 4
    }
    other = {
        identifier.strip()
        for identifier in other_customer_identifiers
        if len(identifier.strip()) >= 4 and identifier.strip().casefold() not in current
    }
    return any(_contains_identifier(text, identifier) for identifier in other)


def validate_customer_output(
    text: str,
    *,
    current_customer_identifiers: Iterable[str] = (),
    other_customer_identifiers: Iterable[str] = (),
) -> CustomerOutputValidation:
    """Validate customer-visible text and assign high risk to every failure (N5)."""

    violations: list[OutputViolation] = []
    if not text.strip():
        violations.append(
            OutputViolation(OutputViolationCode.EMPTY_OUTPUT, "Customer output must not be empty.")
        )
    if any(_is_internal_url(url) for url in _URL_PATTERN.findall(text)):
        violations.append(
            OutputViolation(
                OutputViolationCode.INTERNAL_URL,
                "Customer output contains an internal or local URL.",
            )
        )
    if secret_signals(text):
        violations.append(
            OutputViolation(
                OutputViolationCode.SECRET,
                "Customer output contains secret-like material.",
            )
        )
    if _has_other_customer_data(
        text,
        current_customer_identifiers,
        other_customer_identifiers,
    ):
        violations.append(
            OutputViolation(
                OutputViolationCode.OTHER_CUSTOMER_DATA,
                "Customer output contains an identifier belonging to another customer.",
            )
        )

    findings = tuple(violations)
    return CustomerOutputValidation(
        valid=not findings,
        risk=OutputRisk.HIGH if findings else OutputRisk.LOW,
        violations=findings,
    )
