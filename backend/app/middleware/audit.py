"""Audit every state-changing HTTP request without retaining request bodies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import decode_access_token
from app.middleware.request_id import REQUEST_ID_HEADER, request_id_from
from app.schemas.auth import AuthenticatedUser
from app.services.audit_service import AuditEvent, write_audit_event
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

AuditWriter = Callable[[AuditEvent], Awaitable[None]]
logger = get_logger(__name__)


def _bearer_user(headers: Headers) -> AuthenticatedUser | None:
    authorization = (headers.get("Authorization") or "").strip()
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        return None
    try:
        return decode_access_token(token.strip(), get_settings())
    except HTTPException:
        return None


class AuditMiddleware:
    """Persist request metadata for every method except GET."""

    def __init__(self, app: ASGIApp, *, writer: AuditWriter = write_audit_event) -> None:
        self.app = app
        self.writer = writer

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") == "GET":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        fallback_request_id = request_id_from(headers)
        response_request_id = fallback_request_id
        status_code = 500

        async def capture_response(message: Message) -> None:
            nonlocal response_request_id, status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = Headers(raw=message.get("headers", []))
                response_request_id = response_headers.get(REQUEST_ID_HEADER) or fallback_request_id
            await send(message)

        await self.app(scope, receive, capture_response)

        client = scope.get("client")
        user = _bearer_user(headers)
        outcome = (
            "success"
            if status_code < 400
            else "client_error"
            if status_code < 500
            else "server_error"
        )
        event = AuditEvent(
            method=scope.get("method", ""),
            path=scope.get("path", ""),
            status_code=status_code,
            request_id=response_request_id,
            change_summary={"outcome": outcome, "authenticated": user is not None},
            ip_address=client[0] if client else None,
            user_agent=headers.get("User-Agent"),
            user=user,
        )
        try:
            await self.writer(event)
        except Exception as error:  # noqa: BLE001 -- audit telemetry must never alter the response
            logger.error(
                "Audit persistence failed",
                extra={"error_type": type(error).__name__, "status_code": status_code},
            )
