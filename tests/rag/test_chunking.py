"""P5-1 tests for validated article loading and deterministic heading-aware chunking (F5)."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest
from app.schemas.common import TicketCategory

from rag.chunking import (
    CHUNK_OVERLAP_CHARS,
    MAX_CHUNK_CHARS,
    KnowledgeArticle,
    KnowledgeArticleError,
    chunk_article,
    chunk_articles,
    load_article_file,
    load_article_files,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = PROJECT_ROOT / "sample_data" / "knowledge_base"


def test_f5_loads_all_fifteen_articles_with_valid_front_matter() -> None:
    articles = load_article_files(KNOWLEDGE_DIR)

    assert len(articles) == 15
    assert [article.slug for article in articles] == sorted(article.slug for article in articles)
    assert len({article.title.casefold() for article in articles}) == 15
    assert all(article.tags for article in articles)
    assert all(article.summary for article in articles)
    assert all(article.body.startswith("# ") for article in articles)
    assert all("---" not in article.body for article in articles)
    assert all(isinstance(article.category, TicketCategory) for article in articles)


def test_mfa_article_preserves_metadata_body_and_source() -> None:
    article = load_article_file(KNOWLEDGE_DIR / "mfa-recovery.md")

    assert article.slug == "mfa-recovery"
    assert article.title == "Recover access after MFA lockout"
    assert article.category is TicketCategory.LOGIN_ISSUE
    assert article.tags == ("mfa", "recovery", "lockout")
    assert article.summary.startswith("Identity-safe recovery")
    assert "Do not ask the customer" in article.body
    assert article.source_path.endswith("sample_data/knowledge_base/mfa-recovery.md")


def test_f5_chunks_every_demo_article_by_heading_with_traceable_prefixes() -> None:
    articles = load_article_files(KNOWLEDGE_DIR)
    chunks = chunk_articles(articles)

    assert len(chunks) == 30
    assert len({chunk.id for chunk in chunks}) == len(chunks)
    assert all(chunk.content.startswith(f"{chunk.title} - {chunk.heading}\n\n") for chunk in chunks)
    assert all(len(chunk.content) <= MAX_CHUNK_CHARS for chunk in chunks)
    assert all(chunk.source.startswith(f"kb://{chunk.article_slug}#") for chunk in chunks)

    mfa_chunks = [chunk for chunk in chunks if chunk.article_slug == "mfa-recovery"]
    assert [chunk.heading for chunk in mfa_chunks] == ["MFA recovery", "Reset"]
    assert mfa_chunks[1].source == "kb://mfa-recovery#reset"


def test_long_section_uses_900_character_chunks_with_150_character_overlap() -> None:
    article = KnowledgeArticle(
        slug="long-article",
        title="Long support article",
        category=TicketCategory.OTHER,
        tags=("long",),
        summary="Exercises windowing.",
        body="# Investigation\n\n" + "0123456789" * 220,
        source_path="long-article.md",
    )

    chunks = chunk_article(article)

    assert len(chunks) > 2
    assert all(len(chunk.content) <= MAX_CHUNK_CHARS for chunk in chunks)
    assert all(
        left.text[-CHUNK_OVERLAP_CHARS:] == right.text[:CHUNK_OVERLAP_CHARS]
        for left, right in pairwise(chunks)
    )
    assert [chunk.id for chunk in chunks] == [
        f"long-article:00:{index:02d}" for index in range(len(chunks))
    ]


def test_headingless_article_uses_title_as_section_heading() -> None:
    article = KnowledgeArticle(
        slug="headingless",
        title="Headingless article",
        category=TicketCategory.OTHER,
        tags=("fallback",),
        summary="No Markdown headings.",
        body="A short paragraph without a heading.",
        source_path="headingless.md",
    )

    [chunk] = chunk_article(article)

    assert chunk.heading == article.title
    assert chunk.prefix == "Headingless article - Headingless article"
    assert chunk.source == "kb://headingless#headingless-article"


@pytest.mark.parametrize(
    ("front_matter", "expected_error"),
    [
        (
            'title: "Missing category"\ntags: [test]\nsummary: "Invalid"',
            "field 'category'",
        ),
        (
            'title: "Bad category"\ncategory: not_real\ntags: [test]\nsummary: "Invalid"',
            "unknown ticket category",
        ),
        (
            'title: "Missing tags"\ncategory: other\nsummary: "Invalid"',
            "field 'tags'",
        ),
    ],
)
def test_invalid_front_matter_fails_with_source_context(
    tmp_path: Path,
    front_matter: str,
    expected_error: str,
) -> None:
    article_path = tmp_path / "invalid-article.md"
    article_path.write_text(f"---\n{front_matter}\n---\n# Body\n\nText", encoding="utf-8")

    with pytest.raises(KnowledgeArticleError, match=expected_error) as error:
        load_article_file(article_path)

    assert "invalid-article.md" in str(error.value)


@pytest.mark.parametrize(
    ("chunk_size", "overlap", "expected_error"),
    [
        (0, 0, "positive"),
        (100, -1, "non-negative"),
        (100, 100, "smaller"),
        (50, 20, "too small"),
    ],
)
def test_chunk_configuration_rejects_invalid_bounds(
    chunk_size: int,
    overlap: int,
    expected_error: str,
) -> None:
    article = load_article_file(KNOWLEDGE_DIR / "mfa-recovery.md")

    with pytest.raises(ValueError, match=expected_error):
        chunk_article(article, chunk_size=chunk_size, overlap=overlap)

