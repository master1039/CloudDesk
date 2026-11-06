"""P10-1 tests for SupportState reducers and LangGraph checkpoint persistence."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from app.schemas.workflow import Classification, TokenUsage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from agents.checkpointer import create_checkpointer
from agents.state import SupportState, append_items, merge_cost, merge_usage


def test_support_state_reducers_append_and_sum_without_mutating_inputs() -> None:
    completed = ["understand_ticket"]
    errors = [{"node": "knowledge_retrieval", "code": "timeout"}]
    usage = TokenUsage(prompt_tokens=4, completion_tokens=2)

    merged_nodes = append_items(completed, ["classify_severity"])
    merged_errors = append_items(errors, [{"node": "troubleshooting", "code": "tool_error"}])
    merged_usage = merge_usage(usage, {"prompt_tokens": 3, "completion_tokens": 1})

    assert merged_nodes == ["understand_ticket", "classify_severity"]
    assert merged_errors == [
        {"node": "knowledge_retrieval", "code": "timeout"},
        {"node": "troubleshooting", "code": "tool_error"},
    ]
    assert merged_usage == TokenUsage(prompt_tokens=7, completion_tokens=3)
    assert merge_cost(Decimal("0.010001"), "0.020002") == Decimal("0.030003")
    assert completed == ["understand_ticket"]
    assert errors == [{"node": "knowledge_retrieval", "code": "timeout"}]
    assert usage == TokenUsage(prompt_tokens=4, completion_tokens=2)


def _graph(checkpointer: InMemorySaver | AsyncSqliteSaver):
    builder = StateGraph(SupportState)

    async def understand_ticket(_: SupportState) -> dict:
        return {
            "classification": Classification(
                category="api_failure",
                summary="API requests are rate limited.",
                confidence=0.95,
            ),
            "completed_nodes": ["understand_ticket"],
            "current_node": "understand_ticket",
            "token_usage": TokenUsage(prompt_tokens=5, completion_tokens=2),
            "estimated_cost": Decimal("0.001000"),
        }

    async def classify_severity(state: SupportState) -> dict:
        assert state["classification"].category == "api_failure"
        assert state["completed_nodes"] == ["understand_ticket"]
        return {
            "completed_nodes": ["classify_severity"],
            "current_node": "classify_severity",
            "token_usage": TokenUsage(prompt_tokens=3, completion_tokens=1),
            "estimated_cost": Decimal("0.002000"),
        }

    builder.add_node("understand_ticket", understand_ticket)
    builder.add_node("classify_severity", classify_severity)
    builder.add_edge(START, "understand_ticket")
    builder.add_edge("understand_ticket", "classify_severity")
    builder.add_edge("classify_severity", END)
    return builder.compile(checkpointer=checkpointer)


async def test_memory_checkpointer_preserves_reduced_state_by_thread() -> None:
    async with create_checkpointer(checkpoint_db_path=":memory:") as checkpointer:
        assert isinstance(checkpointer, InMemorySaver)
        graph = _graph(checkpointer)
        config = {"configurable": {"thread_id": "memory-thread"}}

        result = await graph.ainvoke(
            {
                "workflow_id": "workflow-memory",
                "thread_id": "memory-thread",
                "ticket_id": "ticket-memory",
                "customer_id": "customer-memory",
                "subject": "API 429",
                "body": "Requests are rate limited.",
                "completed_nodes": [],
                "errors": [],
                "token_usage": TokenUsage(),
                "estimated_cost": Decimal(0),
            },
            config,
        )
        snapshot = await graph.aget_state(config)
        unrelated = await graph.aget_state(
            {"configurable": {"thread_id": "unrelated-memory-thread"}}
        )

    assert result["completed_nodes"] == ["understand_ticket", "classify_severity"]
    assert result["token_usage"] == TokenUsage(prompt_tokens=8, completion_tokens=3)
    assert result["estimated_cost"] == Decimal("0.003000")
    assert snapshot.values["current_node"] == "classify_severity"
    assert snapshot.values["thread_id"] == "memory-thread"
    assert unrelated.values == {}


async def test_sqlite_checkpointer_survives_close_and_reopen(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "nested" / "checkpoints.db"
    config = {"configurable": {"thread_id": "sqlite-thread"}}

    async with create_checkpointer(checkpoint_db_path=str(checkpoint_path)) as first:
        assert isinstance(first, AsyncSqliteSaver)
        await _graph(first).ainvoke(
            {
                "workflow_id": "workflow-sqlite",
                "thread_id": "sqlite-thread",
                "ticket_id": "ticket-sqlite",
                "customer_id": "customer-sqlite",
                "subject": "API 429",
                "body": "Requests are rate limited.",
                "completed_nodes": [],
                "errors": [],
                "token_usage": TokenUsage(),
                "estimated_cost": Decimal(0),
            },
            config,
        )

    assert checkpoint_path.is_file()
    async with create_checkpointer(checkpoint_db_path=str(checkpoint_path)) as second:
        snapshot = await _graph(second).aget_state(config)

    assert snapshot.values["workflow_id"] == "workflow-sqlite"
    assert snapshot.values["completed_nodes"] == [
        "understand_ticket",
        "classify_severity",
    ]
    assert snapshot.values["classification"] == Classification(
        category="api_failure",
        summary="API requests are rate limited.",
        confidence=0.95,
    )


@pytest.mark.parametrize("value", ["", "   ", "bad\x00path"])
async def test_checkpointer_rejects_invalid_paths(value: str) -> None:
    with pytest.raises(ValueError, match="checkpoint database path"):
        async with create_checkpointer(checkpoint_db_path=value):
            pass
