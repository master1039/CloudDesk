"""Request correlation middleware for HTTP requests and JSON logs."""

from __future__ import annotations

from uuid import uuid4

from app.core.logging import get_logger, reset_request_id, set_request_id
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
MAX_REQUEST_ID_LENGTH = 128
logger = get_logger(__name__)


def request_id_from(headers: Headers) -> str:
    """Return a safe caller request ID or generate a new UUID."""

    candidate = (headers.get(REQUEST_ID_HEADER) or "").strip()
    is_printable_ascii = all(32 < ord(character) < 127 for character in candidate)
    if candidate and len(candidate) <= MAX_REQUEST_ID_LENGTH and is_printable_ascii:
        return candidate
    return str(uuid4())


class RequestIdMiddleware:
    """Bind one request ID to context and include it on every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = request_id_from(Headers(scope=scope))
        token = set_request_id(request_id)
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                response_headers = MutableHeaders(scope=message)
                response_headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            if response_started:
                raise
            logger.exception("Unhandled request error")
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
            )
            await response(scope, receive, send_with_request_id)
        finally:
            reset_request_id(token)
