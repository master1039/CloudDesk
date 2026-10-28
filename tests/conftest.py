"""Offline-first pytest configuration shared by the entire test suite.

Environment values are installed before importing the application so cached
settings and module-level app construction can never select live providers.
"""

from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import tempfile
from collections.abc import AsyncIterator, Iterator, Mapping
from pathlib import Path
from typing import NoReturn

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="clouddesk-tests-"))
OFFLINE_ENV: dict[str, str] = {
    "DEMO_MODE": "true",
    "ENVIRONMENT": "test",
    "DATABASE_URL": f"sqlite+aiosqlite:///{(_TEST_DATA_DIR / 'support.db').as_posix()}",
    "CHECKPOINT_DB_PATH": ":memory:",
    "JWT_SECRET": "offline-test-jwt-secret-not-for-production",
    "REDIS_URL": "",
    "USE_FAKE_REDIS": "true",
    "LLM_PROVIDER": "fake",
    "LLM_MODEL": "fake",
    "EMBEDDING_PROVIDER": "fake",
    "EMBEDDING_MODEL": "fake-embedding",
    "EMBEDDING_DIMENSIONS": "384",
    "VECTOR_STORE": "memory",
    "LANGCHAIN_TRACING_V2": "false",
}

for _name, _value in OFFLINE_ENV.items():
    os.environ[_name] = _value

for _secret_name in (
    "ANTHROPIC_API_KEY",
    "LLM_API_KEY",
    "OPENAI_API_KEY",
    "QDRANT_API_KEY",
    "LANGCHAIN_API_KEY",
    "SUPABASE_JWT_SECRET",
):
    os.environ.pop(_secret_name, None)


# Application imports intentionally follow the environment bootstrap above.
from app.core.config import get_settings
from app.main import create_app


class NetworkAccessBlocked(RuntimeError):
    """Raised when a test attempts to open a real network connection."""


_original_create_connection = socket.create_connection
_original_socket_connect = socket.socket.connect
_original_socket_connect_ex = socket.socket.connect_ex


def _is_loopback(address: object) -> bool:
    if not isinstance(address, tuple) or not address:
        return True
    host = str(address[0])
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _deny_network(address: object) -> NoReturn:
    raise NetworkAccessBlocked("Tests must run offline; outbound network access is blocked")


def _guarded_create_connection(address: object, *args: object, **kwargs: object) -> socket.socket:
    if not _is_loopback(address):
        _deny_network(address)
    return _original_create_connection(address, *args, **kwargs)  # type: ignore[arg-type]


def _guarded_connect(sock: socket.socket, address: object) -> None:
    if not _is_loopback(address):
        _deny_network(address)
    _original_socket_connect(sock, address)  # type: ignore[arg-type]


def _guarded_connect_ex(sock: socket.socket, address: object) -> int:
    if not _is_loopback(address):
        _deny_network(address)
    return _original_socket_connect_ex(sock, address)  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def offline_env() -> Mapping[str, str]:
    """Expose the enforced offline environment to tests without mutating it."""

    return OFFLINE_ENV.copy()


@pytest.fixture(scope="session")
def offline_data_dir() -> Path:
    """Return the isolated directory used for any test database files."""

    return _TEST_DATA_DIR


@pytest.fixture(autouse=True)
def offline_runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reset cached settings and reject outbound sockets for every test."""

    get_settings.cache_clear()
    monkeypatch.setattr(socket, "create_connection", _guarded_create_connection)
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture
def app() -> FastAPI:
    """Create a fresh application instance for an isolated test."""

    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Provide an in-process synchronous API client with lifespan handling."""

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
async def async_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Provide an in-process asynchronous API client without network I/O."""

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


def pytest_sessionfinish() -> None:
    """Remove any test databases or checkpoints created during the session."""

    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)
