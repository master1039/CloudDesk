"""Transport schemas for the ticket API contract (F1 and F4)."""

from __future__ import annotations

from datetime import datetime

from app.schemas.common import (
    ApprovalStatus,
    Channel,
    EscalationStatus,
    MessageDirection,
    Severity,
    TicketCategory,
    TicketStatus,
    WorkflowStatus,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PaginatedResponse[T](BaseModel):
    """Stable envelope used by list endpoints."""

    items: list[T]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class CreateTicketRequest(BaseModel):
    """Customer-supplied ticket content; the body must remain untrusted data."""

    customer_id: str = Field(min_length=1, max_length=36)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=50_000)
    channel: Channel

    @field_validator("customer_id", "subject", "body")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class TicketListParams(BaseModel):
    """Filters and pagination accepted by ``GET /api/v1/tickets``."""

    status: TicketStatus | None = None
    severity: Severity | None = None
    category: TicketCategory | None = None
    channel: Channel | None = None
    customer_id: str | None = Field(default=None, min_length=1, max_length=36)
    search: str | None = Field(default=None, min_length=1, max_length=200)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class TicketMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ticket_id: str
    direction: MessageDirection
    author: str | None = None
    body: str
    created_at: datetime


class TicketSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_id: str
    subject: str
    customer_id: str
    customer_name: str
    channel: Channel
    status: TicketStatus
    category: TicketCategory | None = None
    severity: Severity | None = None
    summary: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowReference(BaseModel):
    id: str
    status: WorkflowStatus
    url: str


class ApprovalReference(BaseModel):
    id: str
    status: ApprovalStatus
    url: str


class EscalationReference(BaseModel):
    id: str
    status: EscalationStatus
    team: str
    url: str


class CustomerContextLinks(BaseModel):
    """Links avoid duplicating the full customer account graph in a ticket response."""

    customer: str
    subscription: str | None = None
    workspace: str | None = None
    previous_tickets: str


class TicketDetail(TicketSummary):
    body: str
    messages: list[TicketMessageResponse] = Field(default_factory=list)
    workflow: WorkflowReference | None = None
    approval: ApprovalReference | None = None
    escalation: EscalationReference | None = None
    customer_context_links: CustomerContextLinks


TicketListResponse = PaginatedResponse[TicketSummary]

