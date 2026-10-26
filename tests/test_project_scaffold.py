"""P1-4 tests for reproducible local setup files."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        assert separator, f"Invalid .env.example line: {raw_line}"
        assert key not in values, f"Duplicate .env.example key: {key}"
        values[key] = value
    return values


def test_env_example_covers_every_setting_with_no_real_keys() -> None:
    values = _env_values()
    expected = {field_name.upper() for field_name in Settings.model_fields}

    assert set(values) == expected
    assert values["LLM_API_KEY"] == ""
    assert values["QDRANT_API_KEY"] == ""
    assert values["LANGCHAIN_API_KEY"] == ""
    assert values["SUPABASE_JWT_SECRET"] == ""
    assert values["JWT_SECRET"].startswith("replace-with-")
    assert values["LLM_PROVIDER"] == "fake"
    assert values["VECTOR_STORE"] == "memory"


def test_makefile_defines_phase_one_commands() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    for target in ("setup", "backend", "test", "lint"):
        assert re.search(rf"(?m)^{target}:\s*$", makefile), f"Missing make target: {target}"

    assert "$(UV) sync --all-groups" in makefile
    assert "$(UV) run uvicorn app.main:app --app-dir backend" in makefile
    assert "$(UV) run pytest" in makefile
    assert "$(UV) run ruff check backend tests main.py" in makefile
