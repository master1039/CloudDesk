"""External-service boundaries and offline adapters for CloudDesk."""

from .factory import IntegrationConfigurationError, IntegrationServices, create_integrations
from .protocols import BillingProvider, ServiceStatusProvider, WorkspaceAdminProvider

__all__ = [
    "BillingProvider",
    "IntegrationConfigurationError",
    "IntegrationServices",
    "ServiceStatusProvider",
    "WorkspaceAdminProvider",
    "create_integrations",
]
