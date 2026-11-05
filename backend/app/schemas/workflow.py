"""Structured contracts shared by specialist agents and workflow state."""

from __future__ import annotations

from typing import Any

from app.schemas.common import (
    ActionStatus,
    Severity,
    SubscriptionPlan,
    SubscriptionStatus,
    TicketCategory,
)
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


class WorkflowSchema(BaseModel):
    """Strict base model for every model-generated workflow value."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TokenUsage(WorkflowSchema):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)

    @computed_field
    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class Classification(WorkflowSchema):
    category: TicketCategory
    summary: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)

    @field_validator("summary")
    @classmethod
    def summary_is_one_line(cls, value: str) -> str:
        return " ".join(value.split())


class SeverityAssessment(WorkflowSchema):
    severity: Severity
    reason: str = Field(min_length=1, max_length=1_000)
    confidence: float = Field(ge=0, le=1)


class CustomerProfile(WorkflowSchema):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    company: str | None = Field(default=None, max_length=200)


class SubscriptionContext(WorkflowSchema):
    plan: SubscriptionPlan
    status: SubscriptionStatus
    seats: int = Field(ge=1)


class WorkspaceContext(WorkflowSchema):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=120)
    storage_used_bytes: int = Field(default=0, ge=0)
    storage_limit_bytes: int = Field(default=0, ge=0)


class MemoryNoteContext(WorkflowSchema):
    memory_type: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1)


class PreviousCase(WorkflowSchema):
    ticket_id: str = Field(min_length=1)
    display_id: str = Field(min_length=1, max_length=20)
    subject: str = Field(min_length=1, max_length=500)
    category: TicketCategory | None = None
    severity: Severity | None = None
    summary: str | None = Field(default=None, max_length=500)
    resolution: str | None = None
    similarity: float | None = Field(default=None, ge=0, le=1)


class CustomerContext(WorkflowSchema):
    customer: CustomerProfile
    subscription: SubscriptionContext | None = None
    workspace: WorkspaceContext | None = None
    previous_tickets: list[PreviousCase] = Field(default_factory=list, max_length=10)
    memory_notes: list[MemoryNoteContext] = Field(default_factory=list, max_length=10)


class Evidence(WorkflowSchema):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source: str = Field(pattern=r"^kb://")
    snippet: str = Field(min_length=1)
    score: float
    url: str = Field(pattern=r"^/knowledge/")
    article_id: str = Field(min_length=1)


class Diagnosis(WorkflowSchema):
    probable_causes: list[str] = Field(min_length=1, max_length=10)
    steps: list[str] = Field(min_length=1, max_length=20)
    confidence: float = Field(ge=0, le=1)
    service_status: dict[str, Any] | None = None

    @field_validator("probable_causes", "steps")
    @classmethod
    def entries_are_non_blank(cls, values: list[str]) -> list[str]:
        normalized = [" ".join(value.split()) for value in values]
        if any(not value for value in normalized):
            raise ValueError("diagnosis entries must not be blank")
        return normalized


class PlannedAction(WorkflowSchema):
    tool: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool
    reason: str = Field(min_length=1, max_length=1_000)
    status: ActionStatus = ActionStatus.PLANNED


class ResolutionPlan(WorkflowSchema):
    summary: str = Field(min_length=1, max_length=1_000)
    customer_reply: str = Field(min_length=1)
    internal_notes: str = Field(min_length=1)
    actions: list[PlannedAction] = Field(default_factory=list)


class EscalationDecision(WorkflowSchema):
    escalation_required: bool
    team: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1)
    policy_rules: list[str] = Field(default_factory=list)
    priority: Severity = Severity.MEDIUM
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def required_escalation_has_team(self) -> EscalationDecision:
        if self.escalation_required and not self.team:
            raise ValueError("an escalation team is required")
        return self


class TicketRunSummary(WorkflowSchema):
    summary: str = Field(min_length=1, max_length=1_000)
    outcome: str = Field(min_length=1, max_length=500)
    customer_follow_up: str | None = Field(default=None, max_length=1_000)
