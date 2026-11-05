"""Composition root for the complete Phase 6 support-tool registry."""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.redis import RedisClient
from app.services.knowledge_service import KnowledgeRuntime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from integrations import IntegrationServices, create_integrations

from .policy import ToolPolicy
from .read_tools import create_read_tools
from .registry import ToolRegistry
from .write_tools import create_write_tools

type SessionFactory = async_sessionmaker[AsyncSession]


def create_support_tool_registry(
    *,
    session_factory: SessionFactory | None = None,
    settings: Settings | None = None,
    cache: RedisClient | None = None,
    knowledge_runtime: KnowledgeRuntime | None = None,
    integrations: IntegrationServices | None = None,
    policy: ToolPolicy | None = None,
) -> ToolRegistry:
    """Register all read/write tools with one mock provider set and one policy boundary."""

    active_settings = settings if settings is not None else get_settings()
    active_integrations = (
        integrations if integrations is not None else create_integrations(active_settings)
    )
    tools = (
        *create_read_tools(
            session_factory=session_factory,
            settings=active_settings,
            cache=cache,
            knowledge_runtime=knowledge_runtime,
            status_provider=active_integrations.service_status,
        ),
        *create_write_tools(
            session_factory=session_factory,
            workspace_admin=active_integrations.workspace_admin,
            billing=active_integrations.billing,
        ),
    )
    return ToolRegistry(tools, policy=policy, settings=active_settings)
