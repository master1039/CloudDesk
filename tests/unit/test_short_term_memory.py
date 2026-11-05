"""P8-1 tests for the ticket-scoped Redis short-term memory facade (F4/F11)."""

from __future__ import annotations

import json

import pytest
from fakeredis.aioredis import FakeRedis

from memory.short_term import SHORT_TERM_TTL_SECONDS, ShortTermMemory


@pytest.fixture
async def short_term_memory() -> tuple[ShortTermMemory, FakeRedis]:
    redis = FakeRedis(decode_responses=True)
    try:
        yield ShortTermMemory(redis), redis
    finally:
        await redis.aclose()


async def test_conversation_is_ticket_scoped_ordered_and_expires_after_24_hours(
    short_term_memory: tuple[ShortTermMemory, FakeRedis],
) -> None:
    memory, redis = short_term_memory

    await memory.append_message("ticket-1", {"role": "customer", "content": "Need help"})
    await memory.append_message("ticket-1", {"role": "agent", "content": "Investigating"})
    await memory.append_message("ticket-2", {"role": "customer", "content": "Separate issue"})

    assert await memory.get_conversation("ticket-1") == [
        {"content": "Need help", "role": "customer"},
        {"content": "Investigating", "role": "agent"},
    ]
    assert await memory.get_conversation("ticket-2") == [
        {"content": "Separate issue", "role": "customer"}
    ]
    ttl = await redis.ttl(memory.conversation_key("ticket-1"))
    assert SHORT_TERM_TTL_SECONDS - 1 <= ttl <= SHORT_TERM_TTL_SECONDS


async def test_workflow_state_round_trips_and_replacement_refreshes_ttl(
    short_term_memory: tuple[ShortTermMemory, FakeRedis],
) -> None:
    memory, redis = short_term_memory
    key = memory.workflow_state_key("CD-1002")

    await memory.save_workflow_state("CD-1002", {"node": "understand", "attempt": 1})
    await redis.expire(key, 60)
    await memory.save_workflow_state("CD-1002", {"node": "approval", "attempt": 2})

    assert await memory.get_workflow_state("CD-1002") == {
        "attempt": 2,
        "node": "approval",
    }
    ttl = await redis.ttl(key)
    assert SHORT_TERM_TTL_SECONDS - 1 <= ttl <= SHORT_TERM_TTL_SECONDS


async def test_missing_expired_and_cleared_ticket_memory_returns_empty_values(
    short_term_memory: tuple[ShortTermMemory, FakeRedis],
) -> None:
    memory, redis = short_term_memory

    assert await memory.get_conversation("missing") == []
    assert await memory.get_workflow_state("missing") is None

    await memory.append_message("ticket-1", {"role": "customer", "content": "hello"})
    await memory.save_workflow_state("ticket-1", {"node": "customer_context"})
    await memory.clear_ticket("ticket-1")

    assert await memory.get_conversation("ticket-1") == []
    assert await memory.get_workflow_state("ticket-1") is None
    assert await redis.exists(memory.conversation_key("ticket-1")) == 0
    assert await redis.exists(memory.workflow_state_key("ticket-1")) == 0


async def test_corrupt_ephemeral_values_are_ignored_without_leaking_other_tickets(
    short_term_memory: tuple[ShortTermMemory, FakeRedis],
) -> None:
    memory, redis = short_term_memory
    await redis.rpush(memory.conversation_key("ticket-1"), "not-json", json.dumps(["not-object"]))
    await redis.rpush(
        memory.conversation_key("ticket-1"),
        json.dumps({"role": "agent", "content": "safe"}),
    )
    await redis.set(memory.workflow_state_key("ticket-1"), "not-json")
    await memory.save_workflow_state("ticket-2", {"node": "other-customer"})

    assert await memory.get_conversation("ticket-1") == [
        {"role": "agent", "content": "safe"}
    ]
    assert await memory.get_workflow_state("ticket-1") is None
    assert await memory.get_workflow_state("ticket-2") == {"node": "other-customer"}


@pytest.mark.parametrize("ticket_id", ["", "   ", "ticket:other", "../ticket", "ticket/id"])
async def test_invalid_ticket_ids_cannot_escape_the_ticket_namespace(
    short_term_memory: tuple[ShortTermMemory, FakeRedis],
    ticket_id: str,
) -> None:
    memory, _ = short_term_memory

    with pytest.raises(ValueError, match="ticket_id"):
        await memory.get_conversation(ticket_id)


async def test_non_json_values_and_invalid_ttl_are_rejected(
    short_term_memory: tuple[ShortTermMemory, FakeRedis],
) -> None:
    memory, redis = short_term_memory

    with pytest.raises(ValueError, match="JSON-serializable"):
        await memory.save_workflow_state("ticket-1", {"value": object()})
    with pytest.raises(ValueError, match="TTL must be positive"):
        ShortTermMemory(redis, ttl_seconds=0)
