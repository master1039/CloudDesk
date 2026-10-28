"""Durable, best-effort audit event persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.database import get_session_factory
from app.repositories import AuditLogRepository, ProfileRepository
from app.schemas.auth import AuthenticatedUser


@dataclass(frozen=True)
class AuditEvent:
    method: str
    path: str
    status_code: int
    request_id: str
    change_summary: dict[str, Any]
    ip_address: str | None
    user_agent: str | None
    user: AuthenticatedUser | None = None


async def write_audit_event(event: AuditEvent) -> None:
    """Write one event in an isolated transaction after the response completes."""

    async with get_session_factory().begin() as session:
        actor_id = None
        actor_role = None
        if event.user is not None:
            profile = await ProfileRepository(session).get(event.user.id)
            if profile is not None:
                actor_id = profile.id
                actor_role = profile.role

        await AuditLogRepository(session).create(
            actor_id=actor_id,
            actor_role=actor_role,
            method=event.method[:10],
            path=event.path[:500],
            status_code=event.status_code,
            request_id=event.request_id[:128],
            change_summary=event.change_summary,
            ip_address=event.ip_address[:64] if event.ip_address else None,
            user_agent=event.user_agent[:500] if event.user_agent else None,
        )
