"""Bounded read-only capabilities used by CloudDesk specialist agents."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.core.redis import RedisClient, get_redis_client
from app.repositories import CustomerRepository, IncidentRepository, TicketRepository
from app.schemas.common import TicketCategory
from app.services.knowledge_service import KnowledgeRuntime, get_knowledge_runtime
from langchain_core.tools import BaseTool, tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from integrations.protocols import ServiceStatusProvider

from .policy import ToolPolicy
from .registry import ToolRegistry

type SessionFactory = async_sessionmaker[AsyncSession]
type RetrievalMode = Literal["hybrid", "semantic", "keyword"]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _money(value: Decimal) -> str:
    return format(value, "f")


class RepositoryServiceStatusProvider:
    """Offline status provider backed by checked-in active incident records."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def check_service_status(self, service: str | None = None) -> Mapping[str, Any]:
        normalized_service = service.strip().casefold() if service else None
        async with self._session_factory() as session:
            incidents = await IncidentRepository(session).list_active()

        if normalized_service:
            incidents = [
                incident
                for incident in incidents
                if normalized_service in {item.casefold() for item in incident.affected_services}
            ]
        return {
            "service": normalized_service or "all",
            "status": "degraded" if incidents else "operational",
            "incidents": [
                {
                    "id": incident.id,
                    "title": incident.title,
                    "status": incident.status.value,
                    "severity": incident.severity.value,
                    "affected_services": list(incident.affected_services),
                    "started_at": _iso(incident.started_at),
                    "updated_at": _iso(incident.updated_at),
                }
                for incident in incidents
            ],
        }


def create_read_tools(
    *,
    session_factory: SessionFactory | None = None,
    settings: Settings | None = None,
    cache: RedisClient | None = None,
    knowledge_runtime: KnowledgeRuntime | None = None,
    status_provider: ServiceStatusProvider | None = None,
) -> tuple[BaseTool, ...]:
    """Create the five read-only tools with explicit, replaceable dependencies."""

    active_factory = session_factory if session_factory is not None else get_session_factory()
    active_settings = settings if settings is not None else get_settings()
    active_cache = cache if cache is not None else get_redis_client()
    active_runtime = knowledge_runtime if knowledge_runtime is not None else get_knowledge_runtime()
    active_status = (
        status_provider
        if status_provider is not None
        else RepositoryServiceStatusProvider(active_factory)
    )

    @tool("get_customer")
    async def get_customer(customer_id: str) -> dict[str, Any]:
        """Load safe customer identity and account context by internal customer ID."""

        async with active_factory() as session:
            customer = await CustomerRepository(session).get_with_context(customer_id)
        if customer is None:
            return {"found": False, "customer_id": customer_id}
        primary_workspace = min(
            customer.workspaces,
            key=lambda workspace: (workspace.name, workspace.id),
            default=None,
        )
        return {
            "found": True,
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "company": customer.company,
            "workspace": (
                {
                    "id": primary_workspace.id,
                    "name": primary_workspace.name,
                    "slug": primary_workspace.slug,
                    "storage_used_bytes": primary_workspace.storage_used_bytes,
                    "storage_limit_bytes": primary_workspace.storage_limit_bytes,
                }
                if primary_workspace
                else None
            ),
            "created_at": _iso(customer.created_at),
        }

    @tool("get_subscription")
    async def get_subscription(customer_id: str) -> dict[str, Any]:
        """Load a customer's current subscription without exposing internal attributes."""

        async with active_factory() as session:
            customer = await CustomerRepository(session).get_with_context(customer_id)
        subscription = customer.subscription if customer else None
        if subscription is None:
            return {"found": False, "customer_id": customer_id}
        return {
            "found": True,
            "id": subscription.id,
            "customer_id": subscription.customer_id,
            "plan": subscription.plan.value,
            "status": subscription.status.value,
            "seats": subscription.seats,
            "amount": _money(subscription.amount),
            "currency": subscription.currency,
            "billing_interval": subscription.billing_interval,
            "current_period_end": _iso(subscription.current_period_end),
        }

    @tool("get_ticket_history")
    async def get_ticket_history(
        customer_id: str,
        exclude_ticket_id: str | None = None,
        limit: Annotated[int, Field(ge=1, le=10)] = 10,
    ) -> dict[str, Any]:
        """Return up to ten recent ticket summaries without ticket or message bodies."""

        async with active_factory() as session:
            tickets = await TicketRepository(session).list_for_customer(
                customer_id,
                exclude_ticket_id=exclude_ticket_id,
                limit=limit,
            )
        return {
            "customer_id": customer_id,
            "items": [
                {
                    "id": ticket.id,
                    "display_id": ticket.display_id,
                    "subject": ticket.subject,
                    "status": ticket.status.value,
                    "category": ticket.category.value if ticket.category else None,
                    "severity": ticket.severity.value if ticket.severity else None,
                    "channel": ticket.channel.value,
                    "summary": ticket.summary,
                    "created_at": _iso(ticket.created_at),
                    "updated_at": _iso(ticket.updated_at),
                }
                for ticket in tickets
            ],
        }

    @tool("search_docs")
    async def search_docs(
        query: str,
        category: TicketCategory | None = None,
        mode: RetrievalMode = "hybrid",
        top_k: Annotated[int, Field(ge=1, le=10)] = 5,
    ) -> dict[str, Any]:
        """Search support knowledge and return bounded cited evidence."""

        index = await active_runtime.ensure_index(active_settings, active_cache)
        evidence = await index.retriever.retrieve(
            query,
            category=category.value if category else None,
            mode=mode,
            top_k=top_k,
        )
        return {
            "items": [
                {
                    "id": item.id,
                    "title": item.title,
                    "source": item.source,
                    "snippet": item.snippet,
                    "score": item.score,
                    "url": item.url,
                    "article_id": item.article_id,
                }
                for item in evidence
            ]
        }

    @tool("check_service_status")
    async def check_service_status(service: str | None = None) -> dict[str, Any]:
        """Check current service health through the configured status provider."""

        return dict(await active_status.check_service_status(service))

    return (
        get_customer,
        get_subscription,
        get_ticket_history,
        search_docs,
        check_service_status,
    )


def create_read_tool_registry(
    *,
    session_factory: SessionFactory | None = None,
    settings: Settings | None = None,
    cache: RedisClient | None = None,
    knowledge_runtime: KnowledgeRuntime | None = None,
    status_provider: ServiceStatusProvider | None = None,
    policy: ToolPolicy | None = None,
) -> ToolRegistry:
    """Build the approved P6-2 registry; callers still invoke only ``execute``."""

    active_settings = settings if settings is not None else get_settings()
    tools = create_read_tools(
        session_factory=session_factory,
        settings=active_settings,
        cache=cache,
        knowledge_runtime=knowledge_runtime,
        status_provider=status_provider,
    )
    return ToolRegistry(tools, policy=policy, settings=active_settings)
