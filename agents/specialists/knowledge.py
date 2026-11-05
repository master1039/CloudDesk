"""Knowledge specialist for cited retrieval and deterministic similar-case ranking."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Literal

from app.schemas.common import TicketCategory
from app.schemas.workflow import Evidence, PreviousCase, TokenUsage
from app.tools import ToolRegistry, ToolResult

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
type RetrievalMode = Literal["hybrid", "semantic", "keyword"]


class KnowledgeAgentError(RuntimeError):
    """Raised when cited knowledge cannot be assembled safely."""


@dataclass(frozen=True, slots=True)
class KnowledgeAgentResult:
    """Cited evidence and similar cases with trace-ready tool metadata."""

    evidence: tuple[Evidence, ...]
    similar_cases: tuple[PreviousCase, ...]
    tool_calls: tuple[ToolResult, ...]
    usage: TokenUsage
    duration_ms: int
    estimated_cost: Decimal = Decimal(0)


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(text.casefold()))


def jaccard_similarity(left: str, right: str) -> float:
    """Return deterministic token-set overlap in the inclusive range zero to one."""

    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def _case_text(case: PreviousCase) -> str:
    return " ".join(
        value
        for value in (case.subject, case.summary, case.resolution)
        if value is not None and value.strip()
    )


def _evidence(result: ToolResult, top_k: int) -> tuple[Evidence, ...]:
    if not result.ok or not isinstance(result.output, dict):
        code = result.error_code.value if result.error_code is not None else "invalid_output"
        raise KnowledgeAgentError(f"knowledge tool search_docs failed: {code}")
    items = result.output.get("items")
    if not isinstance(items, list):
        raise KnowledgeAgentError("knowledge tool returned invalid evidence")

    evidence: list[Evidence] = []
    seen_articles: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise KnowledgeAgentError("knowledge tool returned invalid evidence")
        projected = Evidence(
            id=item["id"],
            title=item["title"],
            source=item["source"],
            snippet=item["snippet"],
            score=item["score"],
            url=item["url"],
            article_id=item["article_id"],
        )
        if projected.article_id in seen_articles:
            continue
        seen_articles.add(projected.article_id)
        evidence.append(projected)
        if len(evidence) == top_k:
            break
    return tuple(evidence)


class KnowledgeAgent:
    """Retrieve grounded evidence and rank caller-supplied resolved cases (F5/F6)."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @staticmethod
    def similar_cases(
        query: str,
        candidates: Sequence[PreviousCase],
        *,
        limit: int = 3,
    ) -> tuple[PreviousCase, ...]:
        """Rank previously resolved cases by Jaccard overlap with stable tie-breaking."""

        if not query.strip():
            raise ValueError("similar-case query must not be blank")
        if not 1 <= limit <= 10:
            raise ValueError("similar-case limit must be between 1 and 10")

        ranked: list[PreviousCase] = []
        for candidate in candidates:
            similarity = jaccard_similarity(query, _case_text(candidate))
            if similarity <= 0:
                continue
            ranked.append(candidate.model_copy(update={"similarity": similarity}))
        ranked.sort(
            key=lambda case: (
                -(case.similarity or 0.0),
                case.display_id,
                case.ticket_id,
            )
        )
        return tuple(ranked[:limit])

    async def run(
        self,
        query: str,
        *,
        category: TicketCategory | str | None = None,
        previous_cases: Sequence[PreviousCase] = (),
        mode: RetrievalMode = "hybrid",
        top_k: int = 5,
        similar_limit: int = 3,
    ) -> KnowledgeAgentResult:
        """Retrieve cited knowledge through the registry and attach ranked resolved cases."""

        normalized_query = " ".join(query.split())
        if not normalized_query:
            raise ValueError("knowledge query must not be blank")
        if not 1 <= top_k <= 10:
            raise ValueError("top_k must be between 1 and 10")
        if mode not in {"hybrid", "semantic", "keyword"}:
            raise ValueError(f"unsupported retrieval mode: {mode}")
        ranked_cases = self.similar_cases(
            normalized_query,
            previous_cases,
            limit=similar_limit,
        )
        category_value = (
            category.value
            if isinstance(category, TicketCategory)
            else TicketCategory(category).value
            if category is not None
            else None
        )

        started = perf_counter()
        args: dict[str, object] = {
            "query": normalized_query,
            "mode": mode,
            "top_k": top_k,
        }
        if category_value is not None:
            args["category"] = category_value
        search_call = await self._registry.execute("search_docs", args)
        return KnowledgeAgentResult(
            evidence=_evidence(search_call, top_k),
            similar_cases=ranked_cases,
            tool_calls=(search_call,),
            usage=TokenUsage(),
            duration_ms=max(0, round((perf_counter() - started) * 1_000)),
        )
