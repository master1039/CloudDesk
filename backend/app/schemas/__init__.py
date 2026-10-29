"""Pydantic schemas and shared domain enumerations."""

from .auth import AuthenticatedUser, AuthResponse, LoginRequest, ProfileResponse
from .customers import (
    CustomerDetail,
    CustomerListParams,
    CustomerListResponse,
    CustomerMemoryNote,
    CustomerSummary,
    SubscriptionResponse,
    WorkspaceResponse,
)
from .tickets import (
    ApprovalReference,
    CreateTicketRequest,
    CustomerContextLinks,
    EscalationReference,
    PaginatedResponse,
    TicketDetail,
    TicketListParams,
    TicketListResponse,
    TicketMessageResponse,
    TicketSummary,
    WorkflowReference,
)

__all__ = [
    "ApprovalReference",
    "AuthResponse",
    "AuthenticatedUser",
    "CreateTicketRequest",
    "CustomerContextLinks",
    "CustomerDetail",
    "CustomerListParams",
    "CustomerListResponse",
    "CustomerMemoryNote",
    "CustomerSummary",
    "EscalationReference",
    "LoginRequest",
    "PaginatedResponse",
    "ProfileResponse",
    "SubscriptionResponse",
    "TicketDetail",
    "TicketListParams",
    "TicketListResponse",
    "TicketMessageResponse",
    "TicketSummary",
    "WorkflowReference",
    "WorkspaceResponse",
]
