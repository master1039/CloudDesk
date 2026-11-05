"""Transport schemas for the customer context API contract (F4)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.schemas.common import (
    MemoryType,
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.schemas.tickets import PaginatedResponse, TicketSummary
from pydantic import BaseModel, ConfigDict, Field


class CustomerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: str
    company: str | None = None
    plan: SubscriptionPlan | None = None
    workspace_id: str | None = None
    created_at: datetime


class CustomerListParams(BaseModel):
    """Filters and pagination accepted by ``GET /api/v1/customers``."""

    search: str | None = Field(default=None, min_length=1, max_length=200)
    plan: SubscriptionPlan | None = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    plan: SubscriptionPlan
    status: SubscriptionStatus
    seats: int = Field(ge=1)
    amount: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    billing_interval: str
    current_period_end: datetime | None = None


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    storage_used_bytes: int = Field(ge=0)
    storage_limit_bytes: int = Field(ge=0)


class CustomerMemoryNote(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    memory_type: MemoryType
    content: str
    source_ticket_id: str | None = None
    created_at: datetime


class CustomerDetail(CustomerSummary):
    subscription: SubscriptionResponse | None = None
    workspace: WorkspaceResponse | None = None
    previous_tickets: list[TicketSummary] = Field(default_factory=list, max_length=10)
    memory_notes: list[CustomerMemoryNote] = Field(default_factory=list, max_length=10)


CustomerListResponse = PaginatedResponse[CustomerSummary]

