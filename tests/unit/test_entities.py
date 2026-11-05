"""P2-1 tests for portable SQLAlchemy entities and domain enums."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.core.database import Base
from app.models import Customer, Product, Subscription, Ticket, TicketMessage, Workspace
from app.schemas.common import (
    Channel,
    MessageDirection,
    SubscriptionPlan,
    TicketCategory,
    TicketStatus,
)
from sqlalchemy import JSON, String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

EXPECTED_TABLES = {
    "profiles",
    "customers",
    "subscriptions",
    "workspaces",
    "products",
    "tickets",
    "ticket_messages",
    "support_articles",
    "incidents",
    "workflow_runs",
    "workflow_events",
    "resolution_actions",
    "approval_requests",
    "escalations",
    "customer_memory",
    "audit_logs",
}


@pytest.fixture
def sqlite_engine() -> Iterator[Engine]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_ticket_category_has_exactly_the_ten_locked_values() -> None:
    assert {category.value for category in TicketCategory} == {
        "login_issue",
        "billing",
        "api_failure",
        "workspace_permissions",
        "storage_quota",
        "integration",
        "feature_request",
        "account",
        "security",
        "other",
    }


def test_metadata_contains_all_sixteen_portable_tables(sqlite_engine: Engine) -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES

    for table in Base.metadata.sorted_tables:
        assert isinstance(table.c.id.type, String)
        assert table.c.id.type.length == 36
        assert "created_at" in table.c
        assert "updated_at" in table.c

        for column in table.c:
            if isinstance(column.type, JSON):
                assert column.type.__class__ is JSON


def test_f1_f4_customer_context_and_ticket_round_trip(sqlite_engine: Engine) -> None:
    with Session(sqlite_engine) as session:
        customer = Customer(name="Asha Rao", email="asha@example.test", company="Acme")
        customer.subscription = Subscription(plan=SubscriptionPlan.BUSINESS, seats=8)
        workspace = Workspace(
            name="Acme Workspace",
            slug="acme-workspace",
            storage_limit_bytes=100_000,
        )
        customer.workspaces.append(workspace)
        product = Product(name="CloudDesk", slug="clouddesk")
        ticket = Ticket(
            display_id="CD-TEST-1",
            customer=customer,
            workspace=workspace,
            product=product,
            subject="Refund for unused seats",
            body="We paid for eight seats and use five.",
            channel=Channel.EMAIL,
            category=TicketCategory.BILLING,
        )
        ticket.messages.append(
            TicketMessage(
                direction=MessageDirection.INBOUND,
                author_name="Asha Rao",
                body=ticket.body,
                channel=Channel.EMAIL,
            )
        )
        session.add(ticket)
        session.commit()
        ticket_id = ticket.id

        session.expire_all()
        stored = session.get(Ticket, ticket_id)

        assert stored is not None
        assert len(stored.id) == 36
        assert stored.status is TicketStatus.NEW
        assert stored.category is TicketCategory.BILLING
        assert stored.customer.subscription is not None
        assert stored.customer.subscription.plan is SubscriptionPlan.BUSINESS
        assert stored.workspace is not None
        assert stored.workspace.slug == "acme-workspace"
        assert stored.product is not None
        assert stored.product.slug == "clouddesk"
        assert [message.body for message in stored.messages] == [ticket.body]
        assert stored.created_at is not None
        assert stored.updated_at is not None


def test_invalid_ticket_category_is_rejected(sqlite_engine: Engine) -> None:
    with Session(sqlite_engine) as session:
        customer = Customer(name="Invalid Test", email="invalid@example.test")
        ticket = Ticket(
            display_id="CD-INVALID",
            customer=customer,
            subject="Invalid category",
            body="This should not persist.",
            channel=Channel.WEB,
            category="not_a_category",  # type: ignore[arg-type]
        )
        session.add(ticket)

        with pytest.raises(StatementError, match="not_a_category"):
            session.commit()
