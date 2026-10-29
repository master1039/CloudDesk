"""Customer read use cases and bounded F4 context projection."""

from __future__ import annotations

from app.models import Customer, CustomerMemory, Subscription, Workspace
from app.repositories import CustomerMemoryRepository, CustomerRepository, TicketRepository
from app.schemas.customers import (
    CustomerDetail,
    CustomerListParams,
    CustomerListResponse,
    CustomerMemoryNote,
    CustomerSummary,
    SubscriptionResponse,
    WorkspaceResponse,
)
from app.services.ticket_service import as_utc, ticket_summary
from sqlalchemy.ext.asyncio import AsyncSession


class CustomerNotFoundError(LookupError):
    """Raised when an internal customer UUID does not exist."""


def _primary_workspace(customer: Customer) -> Workspace | None:
    return min(customer.workspaces, key=lambda item: (item.name, item.id), default=None)


def _customer_summary(customer: Customer) -> CustomerSummary:
    workspace = _primary_workspace(customer)
    return CustomerSummary(
        id=customer.id,
        name=customer.name,
        email=customer.email,
        company=customer.company,
        plan=customer.subscription.plan if customer.subscription else None,
        workspace_id=workspace.id if workspace else None,
        created_at=as_utc(customer.created_at),
    )


def _subscription_response(subscription: Subscription | None) -> SubscriptionResponse | None:
    if subscription is None:
        return None
    return SubscriptionResponse(
        id=subscription.id,
        plan=subscription.plan,
        status=subscription.status,
        seats=subscription.seats,
        amount=subscription.amount,
        currency=subscription.currency,
        billing_interval=subscription.billing_interval,
        current_period_end=(
            as_utc(subscription.current_period_end) if subscription.current_period_end else None
        ),
    )


def _workspace_response(workspace: Workspace | None) -> WorkspaceResponse | None:
    if workspace is None:
        return None
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        storage_used_bytes=workspace.storage_used_bytes,
        storage_limit_bytes=workspace.storage_limit_bytes,
    )


def _memory_response(memory: CustomerMemory) -> CustomerMemoryNote:
    """Expose only the safe note fields defined by the contract."""

    return CustomerMemoryNote(
        id=memory.id,
        memory_type=memory.memory_type,
        content=memory.content,
        source_ticket_id=memory.source_ticket_id,
        created_at=as_utc(memory.created_at),
    )


class CustomerService:
    """Coordinate bounded customer-context reads through repositories."""

    def __init__(self, session: AsyncSession) -> None:
        self.customers = CustomerRepository(session)
        self.tickets = TicketRepository(session)
        self.memory = CustomerMemoryRepository(session)

    async def list_customers(self, params: CustomerListParams) -> CustomerListResponse:
        filters = params.model_dump(exclude={"limit", "offset"})
        customers = await self.customers.list_filtered(
            **filters,
            limit=params.limit,
            offset=params.offset,
        )
        total = await self.customers.count_filtered(**filters)
        return CustomerListResponse(
            items=[_customer_summary(customer) for customer in customers],
            total=total,
            limit=params.limit,
            offset=params.offset,
        )

    async def get_customer(self, customer_id: str) -> CustomerDetail:
        customer = await self.customers.get_with_context(customer_id)
        if customer is None:
            raise CustomerNotFoundError(customer_id)

        tickets = await self.tickets.list_for_customer(customer_id, limit=10)
        memory_notes = await self.memory.list_for_customer(customer_id, limit=10)
        return CustomerDetail(
            **_customer_summary(customer).model_dump(),
            subscription=_subscription_response(customer.subscription),
            workspace=_workspace_response(_primary_workspace(customer)),
            previous_tickets=[ticket_summary(ticket) for ticket in tickets],
            memory_notes=[_memory_response(note) for note in memory_notes],
        )

