"""P4-1 contract tests for ticket creation (F1) and customer context (F4)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.schemas.common import Channel
from app.schemas.customers import CustomerDetail, CustomerListParams
from app.schemas.tickets import (
    CreateTicketRequest,
    TicketListParams,
    TicketListResponse,
    TicketSummary,
)
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("channel", ["email", "chat", "web", "api"])
def test_f1_create_ticket_contract_accepts_every_supported_channel(channel: str) -> None:
    request = CreateTicketRequest(
        customer_id="00000000-0000-0000-0000-000000000001",
        subject="  Unable to sign in  ",
        body="  Customer-provided text  ",
        channel=channel,
    )

    assert request.channel is Channel(channel)
    assert request.subject == "Unable to sign in"
    assert request.body == "Customer-provided text"


@pytest.mark.parametrize("field", ["subject", "body"])
def test_f1_create_ticket_contract_rejects_blank_customer_text(field: str) -> None:
    payload = {
        "customer_id": "00000000-0000-0000-0000-000000000001",
        "subject": "Sign-in failure",
        "body": "Cannot access the workspace",
        "channel": "email",
    }
    payload[field] = "   "

    with pytest.raises(ValidationError):
        CreateTicketRequest.model_validate(payload)


def test_f1_ticket_list_uses_the_shared_pagination_envelope() -> None:
    now = datetime.now(UTC)
    ticket = TicketSummary(
        id="00000000-0000-0000-0000-000000000010",
        display_id="CD-1001",
        subject="SSO login fails",
        customer_id="00000000-0000-0000-0000-000000000001",
        customer_name="Asha Rao",
        channel="email",
        status="new",
        created_at=now,
        updated_at=now,
    )

    response = TicketListResponse(items=[ticket], total=13, limit=50, offset=0)

    assert response.total == 13
    assert response.items[0].display_id == "CD-1001"


def test_list_query_contracts_share_safe_pagination_bounds() -> None:
    assert TicketListParams().model_dump()["limit"] == 50
    assert CustomerListParams().model_dump()["offset"] == 0

    with pytest.raises(ValidationError):
        TicketListParams(limit=101)
    with pytest.raises(ValidationError):
        CustomerListParams(offset=-1)


def test_f4_customer_detail_contract_caps_context_collections_at_ten() -> None:
    fields = CustomerDetail.model_fields

    assert fields["subscription"].annotation is not None
    assert fields["workspace"].annotation is not None
    assert fields["previous_tickets"].metadata[0].max_length == 10
    assert fields["memory_notes"].metadata[0].max_length == 10


def test_contract_is_synchronized_across_docs_backend_and_frontend() -> None:
    docs = (PROJECT_ROOT / "docs" / "API_CONTRACT.md").read_text(encoding="utf-8")
    frontend = (PROJECT_ROOT / "frontend" / "lib" / "types.ts").read_text(encoding="utf-8")

    for type_name in (
        "CreateTicketRequest",
        "TicketListParams",
        "TicketSummary",
        "TicketDetail",
        "CustomerSummary",
        "CustomerListParams",
        "CustomerDetail",
        "Subscription",
        "Workspace",
        "CustomerMemoryNote",
    ):
        assert type_name in docs
        assert type_name in frontend

    for channel in Channel:
        assert f'"{channel.value}"' in frontend

