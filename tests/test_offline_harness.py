"""P1-3 acceptance tests for the offline pytest harness."""

from __future__ import annotations

import os
import socket
from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings


def test_f14_harness_forces_offline_settings(
    offline_env: Mapping[str, str], offline_data_dir: Path
) -> None:
    settings = get_settings()

    assert settings.demo_mode is True
    assert settings.environment == "test"
    assert settings.llm_provider == "fake"
    assert settings.llm_api_key is None
    assert settings.embedding_provider == "fake"
    assert settings.vector_store == "memory"
    assert settings.use_fake_redis is True
    assert settings.redis_url is None
    assert settings.checkpoint_db_path == ":memory:"
    assert offline_data_dir.as_posix() in settings.database_url
    assert offline_env["LANGCHAIN_TRACING_V2"] == "false"
    assert "LANGCHAIN_API_KEY" not in os.environ


def test_f14_harness_blocks_outbound_network() -> None:
    with pytest.raises(RuntimeError, match="outbound network access is blocked"):
        socket.create_connection(("example.com", 443))


def test_test_environment_does_not_load_local_dotenv(
    monkeypatch: pytest.MonkeyPatch, offline_data_dir: Path
) -> None:
    dotenv = offline_data_dir / ".env"
    dotenv.write_text("LLM_API_KEY=must-not-load\n", encoding="utf-8")
    monkeypatch.chdir(offline_data_dir)
    get_settings.cache_clear()

    assert get_settings().llm_api_key is None


def test_sync_client_fixture_runs_in_process(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_async_client_fixture_runs_in_session_loop(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
