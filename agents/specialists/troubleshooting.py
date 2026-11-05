"""Troubleshooting specialist with cited prompts and deterministic category playbooks."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from types import MappingProxyType
from typing import Any

from app.core.llm import StructuredLLM, call_structured
from app.schemas.common import TicketCategory
from app.schemas.workflow import Diagnosis, Evidence, TokenUsage
from app.tools import ToolRegistry, ToolResult

from agents.prompts import TROUBLESHOOTING_PROMPT, wrap_untrusted

_NUMBER_PREFIX = re.compile(r"^\s*\d+[.)]\s*")


@dataclass(frozen=True, slots=True)
class TroubleshootingPlaybook:
    """Model-independent diagnostic guidance for one ticket category."""

    service: str
    probable_causes: tuple[str, ...]
    steps: tuple[str, ...]


CATEGORY_PLAYBOOKS: Mapping[TicketCategory, TroubleshootingPlaybook] = MappingProxyType(
    {
        TicketCategory.LOGIN_ISSUE: TroubleshootingPlaybook(
            "sso",
            ("Identity-provider, SSO, session, or MFA state may be blocking authentication.",),
            (
                "Check the current authentication service status.",
                "Verify the user's identity and the applicable SSO or MFA configuration.",
            ),
        ),
        TicketCategory.BILLING: TroubleshootingPlaybook(
            "billing",
            ("Subscription, seat count, invoice, or payment state may not match expectations.",),
            (
                "Compare the active subscription and seat count with the disputed invoice.",
                "Record the exact billing period and line items without initiating a refund.",
            ),
        ),
        TicketCategory.API_FAILURE: TroubleshootingPlaybook(
            "api",
            ("Authentication, rate limiting, request shape, or API availability may be responsible.",),
            (
                "Record the endpoint, status code, response headers, and a redacted request example.",
                "For HTTP 429 responses, honor Retry-After and verify bounded exponential backoff.",
            ),
        ),
        TicketCategory.WORKSPACE_PERMISSIONS: TroubleshootingPlaybook(
            "sharing",
            ("Workspace policy or the caller's effective role may deny the requested operation.",),
            (
                "Compare the effective user role with the workspace sharing policy.",
                "Reproduce the operation with the same resource and intended recipient type.",
            ),
        ),
        TicketCategory.STORAGE_QUOTA: TroubleshootingPlaybook(
            "storage",
            ("Used storage, retained trash, or a delayed quota calculation may block uploads.",),
            (
                "Compare reported usage with the workspace storage limit.",
                "Check retained trash and allow quota recalculation before retrying a small upload.",
            ),
        ),
        TicketCategory.INTEGRATION: TroubleshootingPlaybook(
            "slack",
            ("OAuth authorization, scopes, delivery queues, or provider availability may be degraded.",),
            (
                "Check the integration provider and webhook delivery status.",
                "Verify authorization expiry and required scopes without exposing credentials.",
            ),
        ),
        TicketCategory.FEATURE_REQUEST: TroubleshootingPlaybook(
            "feature",
            ("The requested behavior may be an unsupported capability rather than a defect.",),
            (
                "Confirm the requested outcome and compare it with currently documented behavior.",
                "Capture the use case and impact without promising a delivery date.",
            ),
        ),
        TicketCategory.ACCOUNT: TroubleshootingPlaybook(
            "account",
            ("Account lifecycle, verification, or workspace ownership state may require review.",),
            (
                "Verify the requester and current account or workspace ownership state.",
                "Do not delete, reset, or change the account during diagnosis.",
            ),
        ),
        TicketCategory.SECURITY: TroubleshootingPlaybook(
            "authentication",
            ("The reported behavior may indicate account compromise or a security incident.",),
            (
                "Preserve timestamps and indicators without exposing credentials or private data.",
                "Avoid account changes and route confirmed security indicators to the escalation policy.",
            ),
        ),
        TicketCategory.OTHER: TroubleshootingPlaybook(
            "general",
            ("Configuration, account state, or a service dependency requires verification.",),
            (
                "Capture the exact observed behavior and the smallest reproducible sequence.",
                "Compare the result with current service status and cited support guidance.",
            ),
        ),
    }
)


@dataclass(frozen=True, slots=True)
class TroubleshootingAgentResult:
    """Validated diagnosis with model and tool telemetry for workflow tracing."""

    output: Diagnosis
    tool_calls: tuple[ToolResult, ...]
    usage: TokenUsage
    duration_ms: int
    llm_duration_ms: int
    estimated_cost: Decimal
    provider: str
    model: str
    attempts: int


def _service_status(result: ToolResult, service: str) -> dict[str, Any]:
    if not result.ok or not isinstance(result.output, dict):
        return {"service": service, "status": "unavailable", "incidents": []}
    incidents = result.output.get("incidents")
    if not isinstance(incidents, list):
        incidents = []
    projected_incidents = []
    for incident in incidents:
        if not isinstance(incident, dict):
            continue
        affected_services = incident.get("affected_services", [])
        if not isinstance(affected_services, list):
            affected_services = []
        projected_incidents.append(
            {
                "title": str(incident.get("title", "Service incident")),
                "status": str(incident.get("status", "unknown")),
                "severity": str(incident.get("severity", "unknown")),
                "affected_services": [str(item) for item in affected_services],
            }
        )
    return {
        "service": str(result.output.get("service", service)),
        "status": str(result.output.get("status", "unknown")),
        "incidents": projected_incidents,
    }


def _unique(values: Sequence[str], *, limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            output.append(normalized)
        if len(output) == limit:
            break
    return output


def _numbered_steps(values: Sequence[str]) -> list[str]:
    normalized = _unique([_NUMBER_PREFIX.sub("", value) for value in values], limit=20)
    return [f"{index}. {step}" for index, step in enumerate(normalized, start=1)]


def _prompt(
    subject: str,
    body: str,
    category: TicketCategory,
    evidence: Sequence[Evidence],
    service_status: Mapping[str, Any],
) -> str:
    blocks = [
        f"Trusted ticket category: {category.value}",
        wrap_untrusted(subject, source="ticket_subject"),
        wrap_untrusted(body, source="ticket_body"),
    ]
    if evidence:
        blocks.append(
            wrap_untrusted(
                json.dumps(
                    [item.model_dump(mode="json") for item in evidence],
                    sort_keys=True,
                ),
                source="knowledge_evidence",
            )
        )
    blocks.append(
        wrap_untrusted(
            json.dumps(dict(service_status), sort_keys=True),
            source="service_status",
        )
    )
    return "\n".join(blocks)


def _enrich(
    diagnosis: Diagnosis,
    playbook: TroubleshootingPlaybook,
    service_status: dict[str, Any],
) -> Diagnosis:
    incident_active = bool(service_status["incidents"])
    incident_causes = (
        ("An active service incident may be contributing to the reported behavior.",)
        if incident_active
        else ()
    )
    incident_steps = (
        ("Review the active incident status before changing customer configuration.",)
        if incident_active
        else ()
    )
    return Diagnosis(
        probable_causes=_unique(
            (*incident_causes, *playbook.probable_causes, *diagnosis.probable_causes),
            limit=10,
        ),
        steps=_numbered_steps((*incident_steps, *playbook.steps, *diagnosis.steps)),
        confidence=diagnosis.confidence,
        service_status=service_status,
    )


class TroubleshootingAgent:
    """Create a grounded diagnosis while deterministic playbooks retain control (F7/N4)."""

    def __init__(self, registry: ToolRegistry, llm: StructuredLLM | None = None) -> None:
        self._registry = registry
        self._llm = llm

    async def run(
        self,
        subject: str,
        body: str,
        category: TicketCategory | str,
        *,
        evidence: Sequence[Evidence] = (),
        service: str | None = None,
    ) -> TroubleshootingAgentResult:
        """Check service health, call the structured model, and enrich its diagnosis."""

        normalized_subject = " ".join(subject.split())
        normalized_body = " ".join(body.split())
        if not normalized_subject or not normalized_body:
            raise ValueError("ticket subject and body must not be blank")
        active_category = (
            category if isinstance(category, TicketCategory) else TicketCategory(category)
        )
        playbook = CATEGORY_PLAYBOOKS[active_category]
        active_service = service.strip().casefold() if service is not None else playbook.service
        if not active_service:
            raise ValueError("service must not be blank")

        started = perf_counter()
        status_call = await self._registry.execute(
            "check_service_status",
            {"service": active_service},
        )
        status = _service_status(status_call, active_service)
        call = await call_structured(
            Diagnosis,
            _prompt(normalized_subject, normalized_body, active_category, evidence, status),
            system_prompt=TROUBLESHOOTING_PROMPT,
            llm=self._llm,
        )
        return TroubleshootingAgentResult(
            output=_enrich(call.output, playbook, status),
            tool_calls=(status_call,),
            usage=call.usage,
            duration_ms=max(0, round((perf_counter() - started) * 1_000)),
            llm_duration_ms=call.duration_ms,
            estimated_cost=call.estimated_cost,
            provider=call.provider,
            model=call.model,
            attempts=call.attempts,
        )
