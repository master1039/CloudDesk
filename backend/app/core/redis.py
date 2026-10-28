"""Process-wide async Redis client with an offline fakeredis implementation."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from app.core.config import get_settings
from redis.asyncio import Redis


class RedisClient(Protocol):
    """Subset shared by redis-py and fakeredis for CloudDesk infrastructure."""

    async def set(self, name: str, value: Any, **kwargs: Any) -> Any: ...

    async def incr(self, name: str, amount: int = 1) -> int: ...

    async def aclose(self) -> None: ...


@lru_cache(maxsize=1)
def get_redis_client() -> RedisClient:
    """Return a lazy real Redis client or an in-process fake for offline mode."""

    settings = get_settings()
    if settings.use_fake_redis or not settings.redis_url:
        from fakeredis.aioredis import FakeRedis

        return FakeRedis(decode_responses=True)
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def close_redis() -> None:
    """Close and clear the cached client when the application lifespan ends."""

    if get_redis_client.cache_info().currsize:
        await get_redis_client().aclose()
    get_redis_client.cache_clear()
