"""Environment-backed application settings.

The settings object is immutable and cached. Restart the process, or explicitly
clear ``get_settings`` in a test, after changing environment variables.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


CorsOrigins = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    """CloudDesk runtime settings loaded from environment variables or `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )

    demo_mode: bool = True
    environment: str = "development"
    cors_origins: CorsOrigins = Field(default_factory=lambda: ["http://localhost:3000"])

    jwt_secret: SecretStr | None = None
    supabase_jwt_secret: SecretStr | None = None

    database_url: str = "sqlite+aiosqlite:///./data/support.db"
    checkpoint_db_path: str = "./data/checkpoints.db"

    redis_url: str | None = None
    use_fake_redis: bool = True

    llm_provider: str = "fake"
    llm_api_key: SecretStr | None = None
    llm_model: str = "fake"

    embedding_provider: str = "fake"
    embedding_model: str = "fake-embedding"
    embedding_dimensions: int = Field(default=384, gt=0)

    vector_store: str = "memory"
    qdrant_url: str | None = None
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "clouddesk_knowledge"

    approval_required_for_refunds: bool = True
    max_refund_without_approval: Decimal = Field(default=Decimal("0"), ge=0)
    tool_timeout_seconds: float = Field(default=30.0, gt=0)
    rate_limit_per_minute: int = Field(default=120, gt=0)
    sample_data_dir: Path = Path("sample_data")

    langchain_tracing_v2: bool = False
    langchain_api_key: SecretStr | None = None
    langchain_project: str = "clouddesk-support"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        """Accept a JSON array or a comma-separated environment value."""

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                decoded = json.loads(stripped)
                if not isinstance(decoded, list):
                    raise ValueError("CORS_ORIGINS JSON value must be an array")
                value = decoded
            else:
                value = stripped.split(",")

        if not isinstance(value, (list, tuple, set)):
            raise ValueError("CORS_ORIGINS must be a list or comma-separated string")

        origins = [str(origin).strip().rstrip("/") for origin in value if str(origin).strip()]
        return list(dict.fromkeys(origins))

    @property
    def effective_jwt_secret(self) -> str | None:
        """Return the Supabase secret when configured, otherwise the local secret."""

        secret = self.supabase_jwt_secret or self.jwt_secret
        return secret.get_secret_value() if secret else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings snapshot."""

    env_file = None if os.getenv("ENVIRONMENT", "").casefold() == "test" else ".env"
    return Settings(_env_file=env_file)
