"""P9-4 offline tests for cited retrieval and similar-case ranking (F5/F6/F14)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from app.core.config import Settings
from app.core.database import build_engine, build_session_factory, create_tables
from app.schemas.common import Severity, TicketCategory
from app.schemas.workflow import PreviousCase
from app.services.knowledge_service import KnowledgeRuntime
from app.services.seed_service import bootstrap_demo_data
from app.tools import ToolRegistry, create_read_tool_registry
from fakeredis.aioredis import FakeRedis

from agents.specialists import KnowledgeAgent, KnowledgeAgentError, jaccard_similarity

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"


@pytest.fixture
async def knowledge_registry(
    tmp_path: Path,
) -> AsyncIterator[tuple[ToolRegistry, KnowledgeRuntime, FakeRedis]]:
    engine = build_engine(f"sqlite+aiosqlite:///{(tmp_path / 'knowledge-agent.db').as_posix()}")
    await create_tables(engine)
    factory = build_session_factory(engine)
    async with factory.begin() as session:
        await bootstrap_demo_data(session, SAMPLE_DATA_DIR)
    runtime = KnowledgeRuntime()
    cache = FakeRedis(decode_responses=True)
    settings = Settings(
        sample_data_dir=SAMPLE_DATA_DIR,
        vector_store="memory",
        embedding_provider="fake",
        embedding_dimensions=384,
    )
    registry = create_read_tool_registry(
        session_factory=factory,
        settings=settings,
        cache=cache,
        knowledge_runtime=runtime,
    )
    try:
        yield registry, runtime, cache
    finally:
        await runtime.close()
        await cache.aclose()
        await engine.dispose()


def _cases() -> list[PreviousCase]:
    return [
        PreviousCase(
            ticket_id="case-api",
            display_id="CD-0901",
            subject="Nightly API sync receives HTTP 429",
            category=TicketCategory.API_FAILURE,
            severity=Severity.MEDIUM,
            summary="Requests exceeded the rate limit.",
            resolution="Honored Retry-After and added exponential backoff.",
        ),
        PreviousCase(
            ticket_id="case-storage",
            display_id="CD-0902",
            subject="Storage quota blocks uploads",
            category=TicketCategory.STORAGE_QUOTA,
            severity=Severity.MEDIUM,
            summary="Workspace reached its storage limit.",
            resolution="Cleared trash and upgraded storage.",
        ),
        PreviousCase(
            ticket_id="case-mfa",
            display_id="CD-0903",
            subject="MFA recovery after phone replacement",
            category=TicketCategory.LOGIN_ISSUE,
            severity=Severity.MEDIUM,
            resolution="Verified identity and reset MFA.",
        ),
    ]


async def test_f5_f6_knowledge_agent_returns_citations_and_ranked_similar_cases(
    knowledge_registry: tuple[ToolRegistry, KnowledgeRuntime, FakeRedis],
) -> None:
    registry, _, _ = knowledge_registry

    result = await KnowledgeAgent(registry).run(
        "HTTP 429 nightly API sync Retry-After exponential backoff",
        category=TicketCategory.API_FAILURE,
        previous_cases=_cases(),
        top_k=3,
    )

    assert result.evidence
    assert result.evidence[0].article_id == "api-rate-limits"
    assert result.evidence[0].source.startswith("kb://api-rate-limits#")
    assert result.evidence[0].url == "/knowledge/api-rate-limits"
    assert len({item.article_id for item in result.evidence}) == len(result.evidence)
    assert result.similar_cases[0].ticket_id == "case-api"
    assert result.similar_cases[0].similarity is not None
    assert result.similar_cases[0].similarity > 0
    assert [call.name for call in result.tool_calls] == ["search_docs"]
    assert result.tool_calls[0].ok is True
    assert result.usage.total_tokens == 0
    assert result.estimated_cost == 0


def test_f6_jaccard_similarity_and_tie_breaking_are_deterministic() -> None:
    assert jaccard_similarity("api rate limit", "api rate limit") == 1
    assert jaccard_similarity("api rate", "storage quota") == 0
    candidates = [
        PreviousCase(ticket_id="b", display_id="CD-2", subject="API retry"),
        PreviousCase(ticket_id="a", display_id="CD-1", subject="API retry"),
    ]

    ranked = KnowledgeAgent.similar_cases("API retry", candidates)

    assert [case.ticket_id for case in ranked] == ["a", "b"]
    assert all(case.similarity == 1 for case in ranked)


async def test_knowledge_agent_fails_closed_when_search_tool_is_unavailable() -> None:
    agent = KnowledgeAgent(ToolRegistry())

    with pytest.raises(KnowledgeAgentError, match="unknown_tool"):
        await agent.run("MFA recovery", category="login_issue")


@pytest.mark.parametrize(
    ("query", "top_k", "message"),
    [(" ", 3, "must not be blank"), ("query", 0, "between 1 and 10")],
)
async def test_knowledge_agent_rejects_invalid_requests(
    knowledge_registry: tuple[ToolRegistry, KnowledgeRuntime, FakeRedis],
    query: str,
    top_k: int,
    message: str,
) -> None:
    registry, _, _ = knowledge_registry
    with pytest.raises(ValueError, match=message):
        await KnowledgeAgent(registry).run(query, top_k=top_k)
