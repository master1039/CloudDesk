"""Portable SQLAlchemy 2 entities for the CloudDesk domain."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4

from app.core.database import Base
from app.schemas.common import (
    ActionStatus,
    ApprovalStatus,
    Channel,
    EscalationStatus,
    IncidentStatus,
    MemoryType,
    MessageDirection,
    Role,
    Severity,
    SubscriptionPlan,
    SubscriptionStatus,
    TicketCategory,
    TicketStatus,
    WorkflowStatus,
)
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


def new_uuid() -> str:
    """Return a UUID string compatible with SQLite and PostgreSQL."""

    return str(uuid4())


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def enum_type(enum_class: type[StrEnum]) -> Enum:
    """Persist enum values as portable validated strings, never native DB enums."""

    return Enum(
        enum_class,
        name=enum_class.__name__.lower(),
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class Profile(IdMixin, TimestampMixin, Base):
    __tablename__ = "profiles"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[Role] = mapped_column(enum_type(Role), nullable=False, default=Role.VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Customer(IdMixin, TimestampMixin, Base):
    __tablename__ = "customers"

    external_ref: Mapped[str | None] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    company: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    subscription: Mapped[Subscription | None] = relationship(
        back_populates="customer", cascade="all, delete-orphan", uselist=False
    )
    workspaces: Mapped[list[Workspace]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    tickets: Mapped[list[Ticket]] = relationship(back_populates="customer")
    memory_notes: Mapped[list[CustomerMemory]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )


class Subscription(IdMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("customer_id", name="uq_subscriptions_customer_id"),)

    customer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    plan: Mapped[SubscriptionPlan] = mapped_column(
        enum_type(SubscriptionPlan), nullable=False, default=SubscriptionPlan.FREE
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        enum_type(SubscriptionStatus), nullable=False, default=SubscriptionStatus.ACTIVE
    )
    seats: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal(0))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    billing_interval: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    customer: Mapped[Customer] = relationship(back_populates="subscription")


class Workspace(IdMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    customer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    storage_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    customer: Mapped[Customer] = relationship(back_populates="workspaces")
    tickets: Mapped[list[Ticket]] = relationship(back_populates="workspace")


class Product(IdMixin, TimestampMixin, Base):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    tickets: Mapped[list[Ticket]] = relationship(back_populates="product")
    incidents: Mapped[list[Incident]] = relationship(back_populates="product")


class Ticket(IdMixin, TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        Index("ix_tickets_status_severity", "status", "severity"),
        Index("ix_tickets_customer_created_at", "customer_id", "created_at"),
    )

    display_id: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    customer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    product_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    assigned_to_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("profiles.id", ondelete="SET NULL"), index=True
    )
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[Channel] = mapped_column(enum_type(Channel), nullable=False)
    status: Mapped[TicketStatus] = mapped_column(
        enum_type(TicketStatus), nullable=False, default=TicketStatus.NEW, index=True
    )
    category: Mapped[TicketCategory | None] = mapped_column(enum_type(TicketCategory), index=True)
    severity: Mapped[Severity | None] = mapped_column(enum_type(Severity), index=True)
    summary: Mapped[str | None] = mapped_column(String(500))
    injection_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer] = relationship(back_populates="tickets")
    workspace: Mapped[Workspace | None] = relationship(back_populates="tickets")
    product: Mapped[Product | None] = relationship(back_populates="tickets")
    messages: Mapped[list[TicketMessage]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="TicketMessage.created_at"
    )
    workflow_runs: Mapped[list[WorkflowRun]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )
    escalations: Mapped[list[Escalation]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )


class TicketMessage(IdMixin, TimestampMixin, Base):
    __tablename__ = "ticket_messages"

    ticket_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    direction: Mapped[MessageDirection] = mapped_column(enum_type(MessageDirection), nullable=False)
    author_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("profiles.id", ondelete="SET NULL")
    )
    author_name: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[Channel | None] = mapped_column(enum_type(Channel))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    ticket: Mapped[Ticket] = relationship(back_populates="messages")


class SupportArticle(IdMixin, TimestampMixin, Base):
    __tablename__ = "support_articles"

    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[TicketCategory] = mapped_column(
        enum_type(TicketCategory), nullable=False, index=True
    )
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_path: Mapped[str] = mapped_column(String(500), nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Incident(IdMixin, TimestampMixin, Base):
    __tablename__ = "incidents"

    product_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(
        enum_type(IncidentStatus), nullable=False, default=IncidentStatus.INVESTIGATING, index=True
    )
    severity: Mapped[Severity] = mapped_column(enum_type(Severity), nullable=False, index=True)
    affected_services: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    product: Mapped[Product | None] = relationship(back_populates="incidents")


class WorkflowRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "workflow_runs"

    ticket_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    thread_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    status: Mapped[WorkflowStatus] = mapped_column(
        enum_type(WorkflowStatus), nullable=False, default=WorkflowStatus.QUEUED, index=True
    )
    current_node: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    completed_nodes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal(0)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    ticket: Mapped[Ticket] = relationship(back_populates="workflow_runs")
    events: Mapped[list[WorkflowEvent]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowEvent.created_at"
    )
    actions: Mapped[list[ResolutionAction]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[ApprovalRequest]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    escalations: Mapped[list[Escalation]] = relationship(back_populates="workflow")


class WorkflowEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "workflow_events"
    __table_args__ = (Index("ix_workflow_events_workflow_created", "workflow_id", "created_at"),)

    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticket_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    node: Mapped[str | None] = mapped_column(String(100), index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal(0)
    )
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    workflow: Mapped[WorkflowRun] = relationship(back_populates="events")


class ResolutionAction(IdMixin, TimestampMixin, Base):
    __tablename__ = "resolution_actions"

    ticket_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[ActionStatus] = mapped_column(
        enum_type(ActionStatus), nullable=False, default=ActionStatus.PLANNED, index=True
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workflow: Mapped[WorkflowRun] = relationship(back_populates="actions")
    approval: Mapped[ApprovalRequest | None] = relationship(
        back_populates="resolution_action", uselist=False
    )


class ApprovalRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "approval_requests"

    ticket_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resolution_action_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("resolution_actions.id", ondelete="SET NULL"), unique=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus), nullable=False, default=ApprovalStatus.PENDING, index=True
    )
    requested_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("profiles.id", ondelete="SET NULL")
    )
    decided_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("profiles.id", ondelete="SET NULL")
    )
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workflow: Mapped[WorkflowRun] = relationship(back_populates="approvals")
    resolution_action: Mapped[ResolutionAction | None] = relationship(back_populates="approval")


class Escalation(IdMixin, TimestampMixin, Base):
    __tablename__ = "escalations"

    ticket_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="SET NULL"), index=True
    )
    team: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    policy_rules: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    priority: Mapped[Severity] = mapped_column(
        enum_type(Severity), nullable=False, default=Severity.MEDIUM
    )
    status: Mapped[EscalationStatus] = mapped_column(
        enum_type(EscalationStatus), nullable=False, default=EscalationStatus.OPEN, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    ticket: Mapped[Ticket] = relationship(back_populates="escalations")
    workflow: Mapped[WorkflowRun | None] = relationship(back_populates="escalations")


class CustomerMemory(IdMixin, TimestampMixin, Base):
    __tablename__ = "customer_memory"
    __table_args__ = (
        UniqueConstraint(
            "customer_id", "memory_type", "fingerprint", name="uq_customer_memory_dedup"
        ),
    )

    customer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    memory_type: Mapped[MemoryType] = mapped_column(
        enum_type(MemoryType), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ticket_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tickets.id", ondelete="SET NULL")
    )
    source_workflow_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="SET NULL")
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    customer: Mapped[Customer] = relationship(back_populates="memory_notes")


class AuditLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_actor_created", "actor_id", "created_at"),)

    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("profiles.id", ondelete="SET NULL"), index=True
    )
    actor_role: Mapped[Role | None] = mapped_column(enum_type(Role))
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    change_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(500))
