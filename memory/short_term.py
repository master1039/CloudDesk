"""Ticket-scoped short-term conversation and workflow state in Redis."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from app.core.redis import RedisClient, get_redis_client

SHORT_TERM_TTL_SECONDS = 24 * 60 * 60
_TICKET_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _ticket_id(value: str) -> str:
    normalized = value.strip()
    if not _TICKET_ID_PATTERN.fullmatch(normalized):
        raise ValueError("ticket_id must contain only letters, numbers, dots, underscores, or hyphens")
    return normalized


def _json_object(value: Mapping[str, Any], *, name: str) -> str:
    try:
        return json.dumps(dict(value), separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be JSON-serializable") from error


def _decode_object(value: str | bytes | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


class ShortTermMemory:
    """Store isolated ticket context with a sliding 24-hour lifetime."""

    def __init__(
        self,
        redis: RedisClient | None = None,
        *,
        ttl_seconds: int = SHORT_TERM_TTL_SECONDS,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("short-term memory TTL must be positive")
        self._redis = redis if redis is not None else get_redis_client()
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def conversation_key(ticket_id: str) -> str:
        """Return the namespaced Redis list key for one ticket conversation."""

        return f"memory:ticket:{_ticket_id(ticket_id)}:conversation"

    @staticmethod
    def workflow_state_key(ticket_id: str) -> str:
        """Return the namespaced Redis string key for one ticket workflow state."""

        return f"memory:ticket:{_ticket_id(ticket_id)}:workflow"

    async def append_message(self, ticket_id: str, message: Mapping[str, Any]) -> None:
        """Append one JSON message and refresh the conversation's sliding TTL."""

        key = self.conversation_key(ticket_id)
        encoded = _json_object(message, name="conversation message")
        await self._redis.rpush(key, encoded)
        await self._redis.expire(key, self.ttl_seconds)

    async def get_conversation(self, ticket_id: str) -> list[dict[str, Any]]:
        """Return valid messages in insertion order, or an empty list when absent."""

        values = await self._redis.lrange(self.conversation_key(ticket_id), 0, -1)
        messages: list[dict[str, Any]] = []
        for value in values:
            decoded = _decode_object(value)
            if decoded is not None:
                messages.append(decoded)
        return messages

    async def save_workflow_state(self, ticket_id: str, state: Mapping[str, Any]) -> None:
        """Replace one ticket's ephemeral workflow state and reset its TTL."""

        await self._redis.set(
            self.workflow_state_key(ticket_id),
            _json_object(state, name="workflow state"),
            ex=self.ttl_seconds,
        )

    async def get_workflow_state(self, ticket_id: str) -> dict[str, Any] | None:
        """Return a ticket's workflow state, or ``None`` when absent or malformed."""

        value = await self._redis.get(self.workflow_state_key(ticket_id))
        return _decode_object(value)

    async def clear_ticket(self, ticket_id: str) -> None:
        """Delete all short-term memory belonging to one ticket."""

        await self._redis.delete(
            self.conversation_key(ticket_id),
            self.workflow_state_key(ticket_id),
        )
