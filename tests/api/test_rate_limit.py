"""P3-3 tests for the N2 Redis fixed-window rate limiter."""

from __future__ import annotations

from collections.abc import Callable

import fakeredis.aioredis
import httpx
import pytest
from app.middleware import REQUEST_ID_HEADER, RequestIdMiddleware
from app.middleware.rate_limit import (
    RATE_LIMIT_HEADER,
    RATE_LIMIT_REMAINING_HEADER,
    RATE_LIMIT_RESET_HEADER,
    RETRY_AFTER_HEADER,
    FixedWindowRateLimiter,
    RateLimitMiddleware,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _limited_app(
    redis: fakeredis.aioredis.FakeRedis,
    *,
    limit: int = 2,
    clock: Callable[[], float] = lambda: 120.0,
) -> FastAPI:
    app = FastAPI()

    @app.get("/resource")
    async def resource() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/live")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(
        RateLimitMiddleware,
        limit=limit,
        redis_provider=lambda: redis,
        clock=clock,
    )
    app.add_middleware(RequestIdMiddleware)
    return app


def test_n2_fixed_window_returns_headers_then_429_with_request_id() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = TestClient(_limited_app(redis))

    first = client.get("/resource")
    second = client.get("/resource")
    blocked = client.get("/resource", headers={REQUEST_ID_HEADER: "limited-request"})

    assert first.status_code == 200
    assert first.headers[RATE_LIMIT_HEADER] == "2"
    assert first.headers[RATE_LIMIT_REMAINING_HEADER] == "1"
    assert first.headers[RATE_LIMIT_RESET_HEADER] == "180"
    assert second.status_code == 200
    assert second.headers[RATE_LIMIT_REMAINING_HEADER] == "0"
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Rate limit exceeded"}
    assert blocked.headers[RETRY_AFTER_HEADER] == "60"
    assert blocked.headers[RATE_LIMIT_REMAINING_HEADER] == "0"
    assert blocked.headers[REQUEST_ID_HEADER] == "limited-request"


async def test_n2_fixed_window_resets_and_separates_client_ips() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    now = [120.0]
    app = _limited_app(redis, limit=1, clock=lambda: now[0])
    transport_a = httpx.ASGITransport(app=app, client=("192.0.2.1", 1000))
    transport_b = httpx.ASGITransport(app=app, client=("192.0.2.2", 1000))

    async with (
        httpx.AsyncClient(transport=transport_a, base_url="http://test") as client_a,
        httpx.AsyncClient(transport=transport_b, base_url="http://test") as client_b,
    ):
        assert (await client_a.get("/resource")).status_code == 200
        assert (await client_a.get("/resource")).status_code == 429
        assert (await client_b.get("/resource")).status_code == 200
        now[0] = 180.0
        reset = await client_a.get("/resource")

    assert reset.status_code == 200
    assert reset.headers[RATE_LIMIT_REMAINING_HEADER] == "0"


def test_health_and_preflight_requests_are_exempt() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = TestClient(_limited_app(redis, limit=1))

    assert client.get("/resource").status_code == 200
    assert client.get("/resource").status_code == 429
    for _ in range(3):
        assert client.get("/health/live").status_code == 200
        assert client.options("/resource").status_code != 429


async def test_limiter_validates_configuration() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    with pytest.raises(ValueError, match="rate limit"):
        FixedWindowRateLimiter(redis, limit=0)
    with pytest.raises(ValueError, match="window_seconds"):
        FixedWindowRateLimiter(redis, limit=1, window_seconds=0)


def test_redis_failure_returns_503_instead_of_failing_open() -> None:
    class BrokenRedis:
        async def set(self, *_: object, **__: object) -> None:
            raise ConnectionError("redis unavailable")

        async def incr(self, *_: object, **__: object) -> int:
            raise AssertionError("incr must not run")

        async def aclose(self) -> None:
            return None

    app = FastAPI()

    @app.get("/resource")
    async def resource() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(
        RateLimitMiddleware,
        limit=1,
        redis_provider=lambda: BrokenRedis(),
    )

    response = TestClient(app).get("/resource")

    assert response.status_code == 503
    assert response.json() == {"detail": "Rate limiter is unavailable"}
