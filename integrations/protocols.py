"""Provider contracts kept independent from tools and concrete integrations."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

type JsonScalar = str | int | float | bool | None


@runtime_checkable
class ServiceStatusProvider(Protocol):
    """Read service health without binding tools to a status vendor."""

    async def check_service_status(self, service: str | None = None) -> Mapping[str, Any]: ...


@runtime_checkable
class WorkspaceAdminProvider(Protocol):
    """Apply an approval-gated workspace setting operation."""

    async def reset_demo_setting(
        self,
        *,
        workspace_id: str,
        setting: str,
        value: JsonScalar,
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class BillingProvider(Protocol):
    """Create an approval-gated, idempotent refund request."""

    async def create_refund_request(
        self,
        *,
        ticket_id: str,
        customer_id: str,
        amount: Decimal,
        currency: str,
        reason: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]: ...
