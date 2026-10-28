"""Redis-backed fixed-window request rate limiting."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from app.core.logging import get_logger
from app.core.redis import RedisClient, get_redis_client
from redis.exceptions import RedisError
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

RATE_LIMIT_HEADER = "X-RateLimit-Limit"
RATE_LIMIT_REMAINING_HEADER = "X-RateLimit-Remaining"
RATE_LIMIT_RESET_HEADER = "X-RateLimit-Reset"
RETRY_AFTER_HEADER = "Retry-After"
DEFAULT_WINDOW_SECONDS = 60
EXEMPT_PATHS = frozenset({"/health", "/health/live", "/health/ready"})
logger = get_logger(__name__)


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int
    retry_after: int

    @property
    def headers(self) -> dict[str, str]:
        return {
            RATE_LIMIT_HEADER: str(self.limit),
            RATE_LIMIT_REMAINING_HEADER: str(self.remaining),
            RATE_LIMIT_RESET_HEADER: str(self.reset_at),
        }


class FixedWindowRateLimiter:
    """Count requests in shared epoch-aligned windows using Redis keys."""

    def __init__(
        self,
        redis: RedisClient,
        *,
        limit: int,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if limit <= 0:
            raise ValueError("rate limit must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.redis = redis
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock

    async def check(self, client_id: str) -> RateLimitDecision:
        now = int(self.clock())
        window = now // self.window_seconds
        reset_at = (window + 1) * self.window_seconds
        retry_after = max(1, reset_at - now)
        key = f"rate_limit:{window}:{client_id}"

        await self.redis.set(key, 0, ex=retry_after, nx=True)
        count = int(await self.redis.incr(key))
        remaining = max(0, self.limit - count)
        return RateLimitDecision(
            allowed=count <= self.limit,
            limit=self.limit,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after,
        )


class RateLimitMiddleware:
    """Apply one fixed-window limit to each non-health HTTP client."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limit: int,
        redis_provider: Callable[[], RedisClient] = get_redis_client,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.app = app
        self.limit = limit
        self.redis_provider = redis_provider
        self.window_seconds = window_seconds
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") == "OPTIONS"
            or scope.get("path") in EXEMPT_PATHS
        ):
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        client_id = client[0] if client else "unknown"
        try:
            limiter = FixedWindowRateLimiter(
                self.redis_provider(),
                limit=self.limit,
                window_seconds=self.window_seconds,
                clock=self.clock,
            )
            decision = await limiter.check(client_id)
        except (RedisError, ConnectionError, TimeoutError, RuntimeError) as error:
            logger.error("Rate limiter unavailable", extra={"error_type": type(error).__name__})
            response = JSONResponse(
                status_code=503,
                content={"detail": "Rate limiter is unavailable"},
            )
            await response(scope, receive, send)
            return

        if not decision.allowed:
            headers = decision.headers | {RETRY_AFTER_HEADER: str(decision.retry_after)}
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers=headers,
            )
            await response(scope, receive, send)
            return

        async def send_with_rate_limit(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in decision.headers.items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_rate_limit)
