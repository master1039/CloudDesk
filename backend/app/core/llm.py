"""Structured LLM boundary with a deterministic, fully offline fake provider."""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from time import perf_counter
from typing import Any, Literal, Protocol

from app.core.config import Settings, get_settings
from app.schemas.common import Severity, TicketCategory
from app.schemas.workflow import TokenUsage
from pydantic import BaseModel, ValidationError

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


class LLMConfigurationError(RuntimeError):
    """Raised when the selected model provider cannot be created safely."""


class LLMProviderError(RuntimeError):
    """Retryable provider failure with no prompt or secret details."""


class StructuredOutputError(RuntimeError):
    """Raised after structured generation cannot produce a valid schema."""


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    payload: object
    usage: TokenUsage
    estimated_cost: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class StructuredCallResult[OutputT: BaseModel]:
    output: OutputT
    usage: TokenUsage
    duration_ms: int
    estimated_cost: Decimal
    provider: str
    model: str
    attempts: int


class StructuredLLM(Protocol):
    provider: str
    model: str

    async def ainvoke_structured[SchemaT: BaseModel](
        self,
        schema: type[SchemaT],
        messages: Sequence[LLMMessage],
    ) -> ProviderResponse: ...


def _word_count(value: str) -> int:
    return len(_TOKEN_PATTERN.findall(value))


def _request_text(messages: Sequence[LLMMessage]) -> str:
    return "\n".join(message.content for message in messages if message.role == "user")


def _category(text: str) -> TicketCategory:
    normalized = text.casefold()
    rules = (
        (TicketCategory.SECURITY, ("breach", "suspicious login", "compromised", "security")),
        (TicketCategory.BILLING, ("refund", "charge", "invoice", "billing", "payment")),
        (TicketCategory.API_FAILURE, ("api", "429", "rate limit", "webhook")),
        (TicketCategory.STORAGE_QUOTA, ("quota", "storage", "upload")),
        (TicketCategory.WORKSPACE_PERMISSIONS, ("permission", "share folder", "access denied")),
        (TicketCategory.INTEGRATION, ("slack", "integration", "oauth")),
        (TicketCategory.FEATURE_REQUEST, ("feature request", "dark mode", "would like")),
        (TicketCategory.ACCOUNT, ("delete account", "delete workspace", "gdpr")),
        (TicketCategory.LOGIN_ISSUE, ("login", "sign in", "mfa", "sso", "locked out")),
    )
    return next(
        (category for category, terms in rules if any(term in normalized for term in terms)),
        TicketCategory.OTHER,
    )


def _severity(text: str) -> Severity:
    normalized = text.casefold()
    if any(term in normalized for term in ("breach", "data loss", "files disappeared")):
        return Severity.CRITICAL
    if any(term in normalized for term in ("unauthorized", "outage", "delete", "security")):
        return Severity.HIGH
    if any(term in normalized for term in ("feature request", "dark mode", "nice to have")):
        return Severity.LOW
    return Severity.MEDIUM


def _summary(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return "Support request requires review."
    return normalized[:497].rstrip() + ("..." if len(normalized) > 497 else "")


def _default_payload(schema: type[BaseModel], text: str) -> dict[str, Any]:
    name = schema.__name__
    if name == "Classification":
        return {"category": _category(text), "summary": _summary(text), "confidence": 0.95}
    if name == "SeverityAssessment":
        severity = _severity(text)
        return {
            "severity": severity,
            "reason": f"Offline heuristic selected {severity.value} severity.",
            "confidence": 0.9,
        }
    if name == "Diagnosis":
        return {
            "probable_causes": ["Configuration or account state requires verification."],
            "steps": [
                "1. Verify the current account and workspace configuration.",
                "2. Compare the observed behavior with the cited support guidance.",
                "3. Retry the affected operation and record the result.",
            ],
            "confidence": 0.75,
            "service_status": None,
        }
    if name == "ResolutionPlan":
        return {
            "summary": "Investigate the verified cause and apply the documented safe resolution.",
            "customer_reply": "We investigated the issue and prepared the documented next steps.",
            "internal_notes": "Offline fake response; actions must be planned deterministically.",
            "actions": [],
        }
    if name == "EscalationDecision":
        return {
            "escalation_required": False,
            "team": None,
            "reason": "No deterministic escalation signal was supplied to the fake model.",
            "policy_rules": [],
            "priority": Severity.MEDIUM,
            "confidence": 0.8,
        }
    if name == "TicketRunSummary":
        return {
            "summary": "The support workflow completed its offline analysis.",
            "outcome": "A safe proposed resolution is available for review.",
            "customer_follow_up": None,
        }
    raise LLMProviderError(f"fake provider has no response configured for schema {name}")


class FakeLLM:
    """Deterministic structured provider that never performs network I/O."""

    provider = "fake"

    def __init__(
        self,
        model: str = "fake",
        *,
        scripted_responses: Mapping[str, Sequence[object]] | None = None,
    ) -> None:
        self.model = model
        self._scripted = {
            name: deque(responses) for name, responses in (scripted_responses or {}).items()
        }

    async def ainvoke_structured[SchemaT: BaseModel](
        self,
        schema: type[SchemaT],
        messages: Sequence[LLMMessage],
    ) -> ProviderResponse:
        text = _request_text(messages)
        scripted = self._scripted.get(schema.__name__)
        if scripted:
            payload = scripted.popleft()
            if isinstance(payload, Exception):
                raise payload
        else:
            payload = _default_payload(schema, text)
        serialized = json.dumps(payload, default=str, sort_keys=True)
        return ProviderResponse(
            payload=payload,
            usage=TokenUsage(
                prompt_tokens=sum(_word_count(message.content) for message in messages),
                completion_tokens=_word_count(serialized),
            ),
            estimated_cost=Decimal(0),
        )


def _messages(prompt: str, system_prompt: str | None) -> tuple[LLMMessage, ...]:
    if not prompt.strip():
        raise ValueError("LLM prompt must not be blank")
    messages: list[LLMMessage] = []
    if system_prompt is not None:
        if not system_prompt.strip():
            raise ValueError("LLM system prompt must not be blank")
        messages.append(LLMMessage("system", system_prompt))
    messages.append(LLMMessage("user", prompt))
    return tuple(messages)


def _merge_usage(current: TokenUsage, addition: TokenUsage) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=current.prompt_tokens + addition.prompt_tokens,
        completion_tokens=current.completion_tokens + addition.completion_tokens,
    )


async def call_structured[SchemaT: BaseModel](
    schema: type[SchemaT],
    prompt: str,
    *,
    system_prompt: str | None = None,
    llm: StructuredLLM | None = None,
    max_attempts: int = 2,
) -> StructuredCallResult[SchemaT]:
    """Call a provider, validate its output, and return usage/cost metadata without raw text parsing."""

    if not isinstance(schema, type) or not issubclass(schema, BaseModel):
        raise TypeError("schema must be a Pydantic BaseModel type")
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    active_llm = llm or get_llm()
    messages = _messages(prompt, system_prompt)
    usage = TokenUsage()
    cost = Decimal(0)
    started = perf_counter()
    for attempt in range(1, max_attempts + 1):
        try:
            response = await active_llm.ainvoke_structured(schema, messages)
            usage = _merge_usage(usage, response.usage)
            cost += response.estimated_cost
            output = schema.model_validate(response.payload)
        except (LLMProviderError, ValidationError) as error:
            if attempt == max_attempts:
                raise StructuredOutputError(
                    f"structured generation failed after {max_attempts} attempts"
                ) from error
            continue
        return StructuredCallResult(
            output=output,
            usage=usage,
            duration_ms=max(0, round((perf_counter() - started) * 1_000)),
            estimated_cost=cost,
            provider=active_llm.provider,
            model=active_llm.model,
            attempts=attempt,
        )
    raise AssertionError("structured call attempt loop exited unexpectedly")


@lru_cache(maxsize=1)
def get_llm() -> StructuredLLM:
    """Return the configured process-wide provider; fake mode requires no API key."""

    settings: Settings = get_settings()
    provider = settings.llm_provider.strip().casefold()
    if provider == "fake":
        return FakeLLM(settings.llm_model)
    if settings.llm_api_key is None:
        raise LLMConfigurationError(f"LLM_API_KEY is required for provider {provider}")
    raise LLMConfigurationError(f"LLM provider {provider} is not available in this build")
