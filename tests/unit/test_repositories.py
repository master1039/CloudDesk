"""P2-3 offline tests for async database sessions and repositories."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from app.core.database import Base, build_engine, build_session_factory, create_tables
from app.models import (
    ApprovalRequest,
    AuditLog,
    Customer,
    CustomerMemory,
    Escalation,
    Incident,
    Product,
    Profile,
    ResolutionAction,
    Subscription,
    SupportArticle,
    Ticket,
    TicketMessage,
    WorkflowEvent,
    WorkflowRun,
    Workspace,
)
from app.repositories import (
    ApprovalRequestRepository,
    AuditLogRepository,
    CustomerMemoryRepository,
    CustomerRepository,
    EscalationRepository,
    IncidentRepository,
    ProductRepository,
    ProfileRepository,
    ResolutionActionRepository,
    SubscriptionRepository,
    SupportArticleRepository,
    TicketMessageRepository,
    TicketRepository,
    WorkflowEventRepository,
    WorkflowRunRepository,
    WorkspaceRepository,
)
from app.schemas.common import (
    Channel,
    MemoryType,
    MessageDirection,
    Severity,
    SubscriptionPlan,
    TicketCategory,
    TicketStatus,
    WorkflowStatus,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest.fixture
async def repository_database() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_tables(engine)
    factory = build_session_factory(engine)
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


def test_all_sixteen_entities_have_a_repository() -> None:
    repository_models = {
        ProfileRepository.model,
        CustomerRepository.model,
        SubscriptionRepository.model,
        WorkspaceRepository.model,
        ProductRepository.model,
        TicketRepository.model,
        TicketMessageRepository.model,
        SupportArticleRepository.model,
        IncidentRepository.model,
        WorkflowRunRepository.model,
        WorkflowEventRepository.model,
        ResolutionActionRepository.model,
        ApprovalRequestRepository.model,
        EscalationRepository.model,
        CustomerMemoryRepository.model,
        AuditLogRepository.model,
    }

    assert repository_models == {
        Profile,
        Customer,
        Subscription,
        Workspace,
        Product,
        Ticket,
        TicketMessage,
        SupportArticle,
        Incident,
        WorkflowRun,
        WorkflowEvent,
        ResolutionAction,
        ApprovalRequest,
        Escalation,
        CustomerMemory,
        AuditLog,
    }


async def test_repositories_flush_but_service_owns_transaction(
    repository_database: async_sessionmaker[AsyncSession],
) -> None:
    async with repository_database() as session:
        repository = CustomerRepository(session)
        customer = await repository.create(name="Rollback Test", email="rollback@example.test")
        assert customer.id is not None
        await session.rollback()

    async with repository_database() as session:
        assert await CustomerRepository(session).count() == 0


async def test_f1_f4_ticket_and_customer_context_queries(
    repository_database: async_sessionmaker[AsyncSession],
) -> None:
    async with repository_database.begin() as session:
        customer_repository = CustomerRepository(session)
        ticket_repository = TicketRepository(session)

        customer = Customer(
            external_ref="cust-asha",
            name="Asha Rao",
            email="ASHA@example.test",
            company="Acme",
        )
        customer.subscription = Subscription(plan=SubscriptionPlan.BUSINESS, seats=8)
        workspace = Workspace(name="Acme Workspace", slug="acme", storage_limit_bytes=100_000)
        customer.workspaces.append(workspace)
        customer.memory_notes.append(
            CustomerMemory(
                memory_type=MemoryType.PREFERENCE,
                content="Prefers email",
                fingerprint="email-preference",
            )
        )
        product = Product(name="CloudDesk", slug="clouddesk")
        current = Ticket(
            display_id="CD-CURRENT",
            customer=customer,
            workspace=workspace,
            product=product,
            subject="Current billing question",
            body="Please explain this charge.",
            channel=Channel.EMAIL,
            category=TicketCategory.BILLING,
            severity=Severity.MEDIUM,
        )
        current.messages.append(
            TicketMessage(
                direction=MessageDirection.INBOUND,
                author_name="Asha Rao",
                body=current.body,
                channel=Channel.EMAIL,
            )
        )
        previous = Ticket(
            display_id="CD-PREVIOUS",
            customer=customer,
            subject="Earlier billing question",
            body="This was solved.",
            channel=Channel.WEB,
            category=TicketCategory.BILLING,
            severity=Severity.LOW,
            status=TicketStatus.RESOLVED,
        )
        await customer_repository.add(customer)
        await ticket_repository.add(current)
        await ticket_repository.add(previous)
        current_id = current.id
        customer_id = customer.id

    async with repository_database() as session:
        customer_repository = CustomerRepository(session)
        ticket_repository = TicketRepository(session)

        found_customer = await customer_repository.get_by_email("asha@EXAMPLE.test")
        assert found_customer is not None
        assert found_customer.id == customer_id
        context = await ticket_repository.get_with_context(current_id)
        assert context is not None
        assert context.customer.subscription is not None
        assert context.customer.subscription.plan is SubscriptionPlan.BUSINESS
        assert [item.slug for item in context.customer.workspaces] == ["acme"]
        assert [note.content for note in context.customer.memory_notes] == ["Prefers email"]
        assert [message.body for message in context.messages] == [current.body]

        filtered = await ticket_repository.list_filtered(
            customer_id=customer_id,
            category=TicketCategory.BILLING,
            severity=Severity.MEDIUM,
        )
        assert [ticket.display_id for ticket in filtered] == ["CD-CURRENT"]

        previous_tickets = await ticket_repository.list_previous_resolved(
            customer_id, exclude_ticket_id=current_id
        )
        assert [ticket.display_id for ticket in previous_tickets] == ["CD-PREVIOUS"]


async def test_workflow_repositories_load_trace_in_order(
    repository_database: async_sessionmaker[AsyncSession],
) -> None:
    async with repository_database.begin() as session:
        customer = Customer(name="Workflow User", email="workflow@example.test")
        ticket = Ticket(
            display_id="CD-WORKFLOW",
            customer=customer,
            subject="Workflow test",
            body="Run the workflow.",
            channel=Channel.API,
        )
        workflow = WorkflowRun(
            ticket=ticket,
            thread_id="thread-CD-WORKFLOW",
            status=WorkflowStatus.RUNNING,
        )
        await WorkflowRunRepository(session).add(workflow)
        await WorkflowEventRepository(session).create(
            workflow_id=workflow.id,
            ticket_id=ticket.id,
            event_type="node_started",
            node="understand",
        )
        await WorkflowEventRepository(session).create(
            workflow_id=workflow.id,
            ticket_id=ticket.id,
            event_type="node_completed",
            node="understand",
        )
        workflow_id = workflow.id
        ticket_id = ticket.id

    async with repository_database() as session:
        workflow_repository = WorkflowRunRepository(session)
        active = await workflow_repository.get_active_for_ticket(ticket_id)
        assert active is not None
        assert active.id == workflow_id

        trace = await workflow_repository.get_with_trace(workflow_id)
        assert trace is not None
        assert [event.event_type for event in trace.events] == [
            "node_started",
            "node_completed",
        ]


async def test_pagination_contract_rejects_invalid_bounds(
    repository_database: async_sessionmaker[AsyncSession],
) -> None:
    async with repository_database() as session:
        repository = CustomerRepository(session)
        with pytest.raises(ValueError, match="offset"):
            await repository.list(offset=-1)
        with pytest.raises(ValueError, match="limit"):
            await repository.list(limit=501)


def test_build_engine_is_lazy() -> None:
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    assert isinstance(engine, AsyncEngine)
