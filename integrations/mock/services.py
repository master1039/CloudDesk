"""Stateful, deterministic mocks that never call an external service."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from integrations.protocols import JsonScalar


class IdempotencyConflictError(ValueError):
    """Raised when one idempotency key is reused for a different operation."""


class MockIncident(BaseModel):
    """Validated incident shape loaded from checked-in demo data."""

    model_config = ConfigDict(frozen=True)

    product_slug: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    status: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    affected_services: list[str] = Field(min_length=1)

    @property
    def id(self) -> str:
        return str(uuid5(NAMESPACE_URL, f"clouddesk:incident:{self.product_slug}:{self.title}"))


class MockBillingService:
    """Record refund requests in memory without moving money."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._requests: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}

    @property
    def refund_requests(self) -> Mapping[str, Mapping[str, Any]]:
        """Return immutable copies for demos and assertions."""

        return MappingProxyType(
            {key: MappingProxyType(dict(value[1])) for key, value in self._requests.items()}
        )

    async def create_refund_request(
        self,
        *,
        ticket_id: str,
        customer_id: str,
        amount: Decimal,
        currency: str,
        reason: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        normalized_currency = currency.strip().upper()
        normalized_reason = reason.strip()
        normalized_key = idempotency_key.strip()
        if amount <= 0:
            raise ValueError("refund amount must be positive")
        if len(normalized_currency) != 3:
            raise ValueError("currency must be a three-letter code")
        if not normalized_reason or not normalized_key:
            raise ValueError("reason and idempotency key must not be blank")

        fingerprint = (
            ticket_id,
            customer_id,
            amount,
            normalized_currency,
            normalized_reason,
        )
        async with self._lock:
            existing = self._requests.get(normalized_key)
            if existing is not None:
                if existing[0] != fingerprint:
                    raise IdempotencyConflictError(
                        "idempotency key was already used for a different refund request"
                    )
                return dict(existing[1])

            response = {
                "request_id": str(uuid5(NAMESPACE_URL, f"clouddesk:refund:{normalized_key}")),
                "ticket_id": ticket_id,
                "customer_id": customer_id,
                "amount": format(amount, "f"),
                "currency": normalized_currency,
                "status": "requested",
                "is_mock": True,
                "money_moved": False,
            }
            self._requests[normalized_key] = fingerprint, response
            return dict(response)


class MockWorkspaceAdminService:
    """Simulate workspace settings in memory without changing an account."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._settings: dict[str, dict[str, JsonScalar]] = {}

    @property
    def workspace_settings(self) -> Mapping[str, Mapping[str, JsonScalar]]:
        """Return immutable copies for demos and assertions."""

        return MappingProxyType(
            {
                workspace_id: MappingProxyType(dict(settings))
                for workspace_id, settings in self._settings.items()
            }
        )

    async def reset_demo_setting(
        self,
        *,
        workspace_id: str,
        setting: str,
        value: JsonScalar,
    ) -> Mapping[str, Any]:
        normalized_setting = setting.strip()
        if not workspace_id.strip() or not normalized_setting:
            raise ValueError("workspace and setting must not be blank")

        async with self._lock:
            workspace = self._settings.setdefault(workspace_id, {})
            previous_value = workspace.get(normalized_setting)
            workspace[normalized_setting] = value
            return {
                "operation_id": str(
                    uuid5(
                        NAMESPACE_URL,
                        f"clouddesk:workspace:{workspace_id}:{normalized_setting}:{value!r}",
                    )
                ),
                "workspace_id": workspace_id,
                "setting": normalized_setting,
                "previous_value": previous_value,
                "value": value,
                "status": "updated",
                "is_mock": True,
                "external_change": False,
            }


class MockServiceStatusService:
    """Serve checked-in incident data without contacting a status vendor."""

    def __init__(self, incidents: Iterable[Mapping[str, Any]] = ()) -> None:
        self._incidents = tuple(MockIncident.model_validate(incident) for incident in incidents)

    async def check_service_status(self, service: str | None = None) -> Mapping[str, Any]:
        normalized_service = service.strip().casefold() if service else None
        matching = self._incidents
        if normalized_service:
            matching = tuple(
                incident
                for incident in matching
                if normalized_service
                in {affected.casefold() for affected in incident.affected_services}
            )
        return {
            "service": normalized_service or "all",
            "status": "degraded" if matching else "operational",
            "incidents": [
                {
                    "id": incident.id,
                    "product_slug": incident.product_slug,
                    "title": incident.title,
                    "description": incident.description,
                    "status": incident.status,
                    "severity": incident.severity,
                    "affected_services": list(incident.affected_services),
                }
                for incident in matching
            ],
            "is_mock": True,
        }
