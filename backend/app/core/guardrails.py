"""Deterministic security checks shared by CloudDesk workflow components."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


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
