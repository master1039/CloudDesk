"""Fail-closed selection of CloudDesk integration implementations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings

from .mock import MockBillingService, MockServiceStatusService, MockWorkspaceAdminService
from .protocols import BillingProvider, ServiceStatusProvider, WorkspaceAdminProvider


class IntegrationConfigurationError(RuntimeError):
    """Raised when no safe integration set exists for the selected runtime."""


@dataclass(frozen=True, slots=True)
class IntegrationServices:
    """One coherent provider set injected into support tools."""

    billing: BillingProvider
    workspace_admin: WorkspaceAdminProvider
    service_status: ServiceStatusProvider


def _load_incidents(path: Path) -> list[dict[str, Any]]:
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntegrationConfigurationError("demo incident data could not be loaded") from error
    if not isinstance(content, list) or any(not isinstance(item, dict) for item in content):
        raise IntegrationConfigurationError("demo incident data must be a JSON array of objects")
    return content


def create_integrations(settings: Settings | None = None) -> IntegrationServices:
    """Create isolated mocks in demo mode and refuse unsafe implicit fallbacks."""

    active_settings = settings if settings is not None else get_settings()
    if not active_settings.demo_mode:
        raise IntegrationConfigurationError(
            "real integrations are not implemented; enable demo mode to use mocks"
        )

    incidents = _load_incidents(active_settings.sample_data_dir / "incidents.json")
    return IntegrationServices(
        billing=MockBillingService(),
        workspace_admin=MockWorkspaceAdminService(),
        service_status=MockServiceStatusService(incidents),
    )
