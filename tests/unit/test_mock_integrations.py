"""P6-4 offline tests for deterministic mock integration adapters (F9/F14)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from app.core.config import Settings
from app.core.database import build_engine, build_session_factory, create_tables
from app.services.seed_service import bootstrap_demo_data
from app.tools import ToolErrorCode, create_support_tool_registry

from integrations import (
    BillingProvider,
    IntegrationConfigurationError,
    ServiceStatusProvider,
    WorkspaceAdminProvider,
    create_integrations,
)
from integrations.mock import IdempotencyConflictError, MockBillingService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"


def demo_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "demo_mode": True,
        "sample_data_dir": SAMPLE_DATA_DIR,
        **overrides,
    }
    return Settings(_env_file=None, **values)


async def test_factory_builds_protocol_compatible_offline_services() -> None:
    services = create_integrations(demo_settings())

    assert isinstance(services.billing, BillingProvider)
    assert isinstance(services.workspace_admin, WorkspaceAdminProvider)
    assert isinstance(services.service_status, ServiceStatusProvider)
    status = await services.service_status.check_service_status("SSO")
    assert status["status"] == "degraded"
    assert status["is_mock"] is True
    assert [incident["title"] for incident in status["incidents"]] == [
        "Enterprise SSO authentication degradation"
    ]


async def test_mock_refunds_are_idempotent_and_never_move_money() -> None:
    billing = MockBillingService()
    args = {
        "ticket_id": "CD-1002",
        "customer_id": "customer-1",
        "amount": Decimal("30.00"),
        "currency": "usd",
        "reason": "Unused seats",
        "idempotency_key": "CD-1002-refund-v1",
    }

    first = await billing.create_refund_request(**args)
    repeated = await billing.create_refund_request(**args)

    assert first == repeated
    assert first["status"] == "requested"
    assert first["money_moved"] is False
    assert len(billing.refund_requests) == 1

    with pytest.raises(IdempotencyConflictError):
        await billing.create_refund_request(**{**args, "amount": Decimal("31.00")})


async def test_mock_workspace_changes_only_in_memory() -> None:
    workspace_admin = create_integrations(demo_settings()).workspace_admin

    first = await workspace_admin.reset_demo_setting(
        workspace_id="workspace-1", setting="external_sharing", value=False
    )
    second = await workspace_admin.reset_demo_setting(
        workspace_id="workspace-1", setting="external_sharing", value=True
    )

    assert first["previous_value"] is None
    assert second["previous_value"] is False
    assert second["external_change"] is False


def test_factory_fails_closed_outside_demo_mode() -> None:
    with pytest.raises(
        IntegrationConfigurationError, match="real integrations are not implemented"
    ):
        create_integrations(demo_settings(demo_mode=False))


def test_factory_rejects_missing_demo_incident_data(tmp_path: Path) -> None:
    with pytest.raises(IntegrationConfigurationError, match="incident data could not be loaded"):
        create_integrations(demo_settings(sample_data_dir=tmp_path))


async def test_combined_registry_uses_mock_services_only_after_approval(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{(tmp_path / 'mock-tools.db').as_posix()}")
    await create_tables(engine)
    session_factory = build_session_factory(engine)
    async with session_factory.begin() as session:
        await bootstrap_demo_data(session, SAMPLE_DATA_DIR)

    services = create_integrations(demo_settings())
    assert isinstance(services.billing, MockBillingService)
    billing = services.billing
    registry = create_support_tool_registry(
        session_factory=session_factory,
        settings=demo_settings(),
        integrations=services,
    )
    args = {
        "ticket_id": "CD-1002",
        "customer_id": "customer-1",
        "amount": "30.00",
        "currency": "USD",
        "reason": "Unused seats",
        "idempotency_key": "CD-1002-refund-v1",
    }
    try:
        assert set(registry.tools) == {
            "get_customer",
            "get_subscription",
            "get_ticket_history",
            "search_docs",
            "check_service_status",
            "update_ticket",
            "reset_demo_setting",
            "create_refund_request",
            "create_escalation",
        }
        blocked = await registry.execute("create_refund_request", args)
        assert blocked.error_code == ToolErrorCode.APPROVAL_REQUIRED
        assert len(billing.refund_requests) == 0

        approved = await registry.execute("create_refund_request", args, approved=True)
        repeated = await registry.execute("create_refund_request", args, approved=True)
        status = await registry.execute("check_service_status", {"service": "sso"})

        assert approved.ok is True
        assert approved.output["money_moved"] is False
        assert repeated.output["request_id"] == approved.output["request_id"]
        assert len(billing.refund_requests) == 1
        assert status.output["status"] == "degraded"
    finally:
        await engine.dispose()
