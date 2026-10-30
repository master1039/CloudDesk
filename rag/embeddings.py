"""Embedding protocols and the deterministic offline embedding implementation."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.core.config import Settings, get_settings

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class EmbeddingConfigurationError(ValueError):
    """Raised when the configured embedding provider is unavailable or invalid."""


@runtime_checkable
class EmbeddingService(Protocol):
    """Provider-independent asynchronous embedding contract."""

    @property
    def dimensions(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[tuple[float, ...]]: ...

    async def embed_query(self, text: str) -> tuple[float, ...]: ...


class FakeEmbeddings:
    """Deterministic normalized feature hashing for offline RAG tests.

    This implementation intentionally measures lexical overlap. It validates the complete
    embedding/vector-store path without pretending to match a production semantic model.
    """

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _embed(self, text: str) -> tuple[float, ...]:
        values = [0.0] * self.dimensions
        for token in _TOKEN_PATTERN.findall(text.casefold()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            values[index] += sign

        norm = math.sqrt(sum(value * value for value in values))
        if norm:
            values = [value / norm for value in values]
        return tuple(values)

    async def embed_documents(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> tuple[float, ...]:
        return self._embed(text)


def get_embedding_service(settings: Settings | None = None) -> EmbeddingService:
    """Select an embedding implementation without leaking provider choices downstream."""

    active_settings = settings or get_settings()
    if active_settings.embedding_provider.casefold() == "fake":
        return FakeEmbeddings(active_settings.embedding_dimensions)
    raise EmbeddingConfigurationError(
        f"Unsupported embedding provider: {active_settings.embedding_provider}"
    )

