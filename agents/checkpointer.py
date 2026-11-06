"""Lifecycle-managed LangGraph checkpointer selection for tests and local runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
from app.core.config import Settings, get_settings
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

_CHECKPOINT_TYPE_ALLOWLIST: tuple[tuple[str, str], ...] = (
    ("app.core.guardrails", "CustomerOutputValidation"),
    ("app.core.guardrails", "OutputRisk"),
    ("app.core.guardrails", "OutputViolation"),
    ("app.core.guardrails", "OutputViolationCode"),
    ("app.schemas.common", "ActionStatus"),
    ("app.schemas.common", "Channel"),
    ("app.schemas.common", "Severity"),
    ("app.schemas.common", "SubscriptionPlan"),
    ("app.schemas.common", "SubscriptionStatus"),
    ("app.schemas.common", "TicketCategory"),
    ("app.schemas.workflow", "Classification"),
    ("app.schemas.workflow", "CustomerContext"),
    ("app.schemas.workflow", "CustomerProfile"),
    ("app.schemas.workflow", "Diagnosis"),
    ("app.schemas.workflow", "EscalationDecision"),
    ("app.schemas.workflow", "Evidence"),
    ("app.schemas.workflow", "MemoryNoteContext"),
    ("app.schemas.workflow", "PlannedAction"),
    ("app.schemas.workflow", "PreviousCase"),
    ("app.schemas.workflow", "ResolutionPlan"),
    ("app.schemas.workflow", "SeverityAssessment"),
    ("app.schemas.workflow", "SubscriptionContext"),
    ("app.schemas.workflow", "TicketRunSummary"),
    ("app.schemas.workflow", "TokenUsage"),
    ("app.schemas.workflow", "WorkspaceContext"),
)


def _serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_TYPE_ALLOWLIST)


def _checkpoint_path(value: str) -> str | Path:
    normalized = value.strip()
    if not normalized:
        raise ValueError("checkpoint database path must not be blank")
    if normalized == ":memory:":
        return normalized
    if "\x00" in normalized:
        raise ValueError("checkpoint database path contains an invalid null byte")
    return Path(normalized).expanduser()


@asynccontextmanager
async def create_checkpointer(
    *,
    settings: Settings | None = None,
    checkpoint_db_path: str | None = None,
) -> AsyncIterator[BaseCheckpointSaver[Any]]:
    """Yield the configured saver and close file-backed resources on exit."""

    active_settings = settings if settings is not None else get_settings()
    configured_path = (
        checkpoint_db_path
        if checkpoint_db_path is not None
        else active_settings.checkpoint_db_path
    )
    path = _checkpoint_path(configured_path)
    if path == ":memory:":
        yield InMemorySaver(serde=_serializer())
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path.as_posix()) as connection:
        saver = AsyncSqliteSaver(connection, serde=_serializer())
        await saver.setup()
        yield saver
