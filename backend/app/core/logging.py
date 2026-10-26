"""Structured JSON logging with request and workflow correlation context."""

from __future__ import annotations

import json
import logging
import logging.config
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Iterator


_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_workflow_id: ContextVar[str | None] = ContextVar("workflow_id", default=None)

_STANDARD_LOG_RECORD_FIELDS = frozenset(
    logging.LogRecord(
        name="",
        level=0,
        pathname="",
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    ).__dict__
) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Render one compact JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
            "workflow_id": getattr(record, "workflow_id", None) or get_workflow_id(),
        }

        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_FIELDS and key not in payload:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def setup_logging(level: str | int = "INFO") -> None:
    """Configure application and server logs as JSON without duplicate handlers."""

    resolved_level = logging._checkLevel(level)  # noqa: SLF001 - stdlib's canonical validator
    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": JsonFormatter}},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "level": resolved_level,
                "stream": "ext://sys.stdout",
            }
        },
        "root": {"handlers": ["console"], "level": resolved_level},
        "loggers": {
            "uvicorn": {"handlers": ["console"], "level": resolved_level, "propagate": False},
            "uvicorn.error": {"level": resolved_level},
            "uvicorn.access": {
                "handlers": ["console"],
                "level": resolved_level,
                "propagate": False,
            },
        },
    }
    logging.config.dictConfig(config)


def get_logger(name: str) -> logging.Logger:
    """Return a standard logger configured by :func:`setup_logging`."""

    return logging.getLogger(name)


def get_request_id() -> str | None:
    """Return the request correlation id bound to the current context."""

    return _request_id.get()


def get_workflow_id() -> str | None:
    """Return the workflow correlation id bound to the current context."""

    return _workflow_id.get()


def set_request_id(value: str | None) -> Token[str | None]:
    """Bind a request id and return a token that can restore the prior value."""

    return _request_id.set(value)


def set_workflow_id(value: str | None) -> Token[str | None]:
    """Bind a workflow id and return a token that can restore the prior value."""

    return _workflow_id.set(value)


@contextmanager
def log_context(
    *, request_id: str | None = None, workflow_id: str | None = None
) -> Iterator[None]:
    """Temporarily bind correlation ids and reliably restore prior context."""

    request_token = set_request_id(request_id)
    workflow_token = set_workflow_id(workflow_id)
    try:
        yield
    finally:
        _workflow_id.reset(workflow_token)
        _request_id.reset(request_token)
