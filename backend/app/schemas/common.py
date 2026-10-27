"""Shared domain values used by persistence, APIs, agents, and the frontend contract."""

from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    AGENT = "agent"
    ADMIN = "admin"


class TicketCategory(StrEnum):
    LOGIN_ISSUE = "login_issue"
    BILLING = "billing"
    API_FAILURE = "api_failure"
    WORKSPACE_PERMISSIONS = "workspace_permissions"
    STORAGE_QUOTA = "storage_quota"
    INTEGRATION = "integration"
    FEATURE_REQUEST = "feature_request"
    ACCOUNT = "account"
    SECURITY = "security"
    OTHER = "other"


class TicketStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    WAITING_ON_CUSTOMER = "waiting_on_customer"
    WAITING_ON_APPROVAL = "waiting_on_approval"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Channel(StrEnum):
    EMAIL = "email"
    CHAT = "chat"
    WEB = "web"
    API = "api"


class SubscriptionPlan(StrEnum):
    FREE = "free"
    PRO = "pro"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    TRIALING = "trialing"


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"


class WorkflowStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_ON_APPROVAL = "waiting_on_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class ActionStatus(StrEnum):
    PLANNED = "planned"
    WAITING_ON_APPROVAL = "waiting_on_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class EscalationStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IncidentStatus(StrEnum):
    INVESTIGATING = "investigating"
    IDENTIFIED = "identified"
    MONITORING = "monitoring"
    RESOLVED = "resolved"


class MemoryType(StrEnum):
    PREFERENCE = "preference"
    PAST_ISSUE = "past_issue"
    TROUBLESHOOTING = "troubleshooting"
    NOTE = "note"
