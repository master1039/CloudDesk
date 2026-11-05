"""Load CloudDesk knowledge articles and split them into traceable RAG chunks."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from app.schemas.common import TicketCategory

MAX_CHUNK_CHARS = 900
CHUNK_OVERLAP_CHARS = 150
_FRONT_MATTER_DELIMITER = "---"
_HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class KnowledgeArticleError(ValueError):
    """Raised when a knowledge article cannot satisfy the ingestion contract."""


@dataclass(frozen=True, slots=True)
class KnowledgeArticle:
    """Validated Markdown article before embedding or persistence."""

    slug: str
    title: str
    category: TicketCategory
    tags: tuple[str, ...]
    summary: str
    body: str
    source_path: str


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """One deterministic, cited section window ready for indexing."""

    id: str
    article_slug: str
    title: str
    category: TicketCategory
    tags: tuple[str, ...]
    heading: str
    text: str
    source: str
    section_index: int
    window_index: int

    @property
    def prefix(self) -> str:
        return f"{self.title} - {self.heading}"

    @property
    def content(self) -> str:
        """Return the exact text that later embedding and keyword indexes consume."""

        return f"{self.prefix}\n\n{self.text.strip()}"


def _article_error(path: Path, detail: str) -> KnowledgeArticleError:
    return KnowledgeArticleError(f"{path.as_posix()}: {detail}")


def _non_empty_text(metadata: Mapping[str, Any], field: str, path: Path) -> str:
    value = metadata.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _article_error(path, f"front matter field '{field}' must be non-empty text")
    return value.strip()


def _parse_tags(metadata: Mapping[str, Any], path: Path) -> tuple[str, ...]:
    value = metadata.get("tags")
    if not isinstance(value, list) or not value:
        raise _article_error(path, "front matter field 'tags' must be a non-empty list")
    tags: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise _article_error(path, "every tag must be non-empty text")
        normalized = item.strip().casefold()
        if normalized not in tags:
            tags.append(normalized)
    return tuple(tags)


def _split_front_matter(text: str, path: Path) -> tuple[Mapping[str, Any], str]:
    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != _FRONT_MATTER_DELIMITER:
        raise _article_error(path, "missing opening YAML front matter delimiter")
    try:
        closing_index = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == _FRONT_MATTER_DELIMITER
        )
    except StopIteration as error:
        raise _article_error(path, "missing closing YAML front matter delimiter") from error

    raw_metadata = "\n".join(lines[1:closing_index])
    try:
        metadata = yaml.safe_load(raw_metadata)
    except yaml.YAMLError as error:
        raise _article_error(path, f"invalid YAML front matter: {error}") from error
    if not isinstance(metadata, Mapping):
        raise _article_error(path, "YAML front matter must be a mapping")

    body = "\n".join(lines[closing_index + 1 :]).strip()
    if not body:
        raise _article_error(path, "article body must not be empty")
    return metadata, body


def load_article_file(path: str | Path) -> KnowledgeArticle:
    """Load and validate one Markdown knowledge article."""

    article_path = Path(path)
    if article_path.suffix.casefold() != ".md":
        raise _article_error(article_path, "knowledge articles must use the .md extension")
    if not article_path.is_file():
        raise _article_error(article_path, "article file does not exist")
    if not _SLUG_PATTERN.fullmatch(article_path.stem):
        raise _article_error(article_path, "filename must be a lowercase kebab-case slug")

    metadata, body = _split_front_matter(article_path.read_text(encoding="utf-8"), article_path)
    category_text = _non_empty_text(metadata, "category", article_path)
    try:
        category = TicketCategory(category_text)
    except ValueError as error:
        raise _article_error(article_path, f"unknown ticket category '{category_text}'") from error

    return KnowledgeArticle(
        slug=article_path.stem,
        title=_non_empty_text(metadata, "title", article_path),
        category=category,
        tags=_parse_tags(metadata, article_path),
        summary=_non_empty_text(metadata, "summary", article_path),
        body=body,
        source_path=article_path.as_posix(),
    )


def load_article_files(directory: str | Path) -> list[KnowledgeArticle]:
    """Load all Markdown articles in stable slug order and reject duplicates."""

    article_directory = Path(directory)
    if not article_directory.is_dir():
        raise KnowledgeArticleError(
            f"{article_directory.as_posix()}: knowledge article directory does not exist"
        )

    articles = [load_article_file(path) for path in sorted(article_directory.glob("*.md"))]
    if not articles:
        raise KnowledgeArticleError(
            f"{article_directory.as_posix()}: no Markdown knowledge articles found"
        )

    titles: set[str] = set()
    for article in articles:
        normalized_title = article.title.casefold()
        if normalized_title in titles:
            raise KnowledgeArticleError(
                f"{article.source_path}: duplicate knowledge article title '{article.title}'"
            )
        titles.add(normalized_title)
    return articles


def _anchor(value: str, fallback: str) -> str:
    anchor = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return anchor or fallback


def _sections(body: str, default_heading: str) -> list[tuple[str, str]]:
    matches = list(_HEADING_PATTERN.finditer(body))
    if not matches:
        return [(default_heading, body.strip())]

    sections: list[tuple[str, str]] = []
    preamble = body[: matches[0].start()].strip()
    if preamble:
        sections.append((default_heading, preamble))
    for index, match in enumerate(matches):
        content_start = match.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        content = body[content_start:content_end].strip()
        if content:
            sections.append((match.group(2).strip(), content))
    return sections


def _windows(text: str, *, capacity: int, overlap: int) -> list[str]:
    if len(text) <= capacity:
        return [text]
    windows: list[str] = []
    start = 0
    step = capacity - overlap
    while start < len(text):
        windows.append(text[start : start + capacity])
        if start + capacity >= len(text):
            break
        start += step
    return windows


def chunk_article(
    article: KnowledgeArticle,
    *,
    chunk_size: int = MAX_CHUNK_CHARS,
    overlap: int = CHUNK_OVERLAP_CHARS,
) -> list[KnowledgeChunk]:
    """Split an article on headings, then into overlapping character windows.

    ``chunk_size`` includes the required ``"{title} - {heading}"`` prefix so the final
    indexable content stays within the configured size.
    """

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[KnowledgeChunk] = []
    for section_index, (heading, section_text) in enumerate(
        _sections(article.body, article.title)
    ):
        prefix = f"{article.title} - {heading}"
        capacity = chunk_size - len(prefix) - 2
        if capacity <= overlap:
            raise ValueError("chunk_size is too small for the title, heading, and overlap")
        source = f"kb://{article.slug}#{_anchor(heading, f'section-{section_index + 1}') }"
        for window_index, text in enumerate(
            _windows(section_text, capacity=capacity, overlap=overlap)
        ):
            chunks.append(
                KnowledgeChunk(
                    id=f"{article.slug}:{section_index:02d}:{window_index:02d}",
                    article_slug=article.slug,
                    title=article.title,
                    category=article.category,
                    tags=article.tags,
                    heading=heading,
                    text=text,
                    source=source,
                    section_index=section_index,
                    window_index=window_index,
                )
            )
    if not chunks:
        raise KnowledgeArticleError(f"{article.source_path}: article has no indexable section text")
    return chunks


def chunk_articles(
    articles: Iterable[KnowledgeArticle],
    *,
    chunk_size: int = MAX_CHUNK_CHARS,
    overlap: int = CHUNK_OVERLAP_CHARS,
) -> list[KnowledgeChunk]:
    """Chunk articles in input order while preserving stable per-article IDs."""

    return [
        chunk
        for article in articles
        for chunk in chunk_article(article, chunk_size=chunk_size, overlap=overlap)
    ]

