"""P1-1 tests for environment settings and structured logging."""

from __future__ import annotations

import io
import json
import logging
import os
import unittest
from unittest.mock import patch

from app.core.config import Settings, get_settings
from app.core.logging import JsonFormatter, get_request_id, get_workflow_id, log_context


class SettingsTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_f14_offline_defaults_need_no_api_key(self) -> None:
        settings = Settings(_env_file=None)

        self.assertTrue(settings.demo_mode)
        self.assertEqual(settings.llm_provider, "fake")
        self.assertEqual(settings.vector_store, "memory")
        self.assertTrue(settings.use_fake_redis)
        self.assertIsNone(settings.llm_api_key)

    def test_environment_overrides_and_cors_parsing(self) -> None:
        env = {
            "DEMO_MODE": "false",
            "CORS_ORIGINS": "https://console.example.com/, http://localhost:3000",
            "SUPABASE_JWT_SECRET": "supabase-secret",
            "JWT_SECRET": "local-secret",
            "RATE_LIMIT_PER_MINUTE": "60",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings(_env_file=None)

        self.assertFalse(settings.demo_mode)
        self.assertEqual(
            settings.cors_origins,
            ["https://console.example.com", "http://localhost:3000"],
        )
        self.assertEqual(settings.effective_jwt_secret, "supabase-secret")
        self.assertEqual(settings.rate_limit_per_minute, 60)
        self.assertNotIn("supabase-secret", repr(settings))

    def test_get_settings_returns_one_cached_snapshot(self) -> None:
        get_settings.cache_clear()
        self.assertIs(get_settings(), get_settings())


class JsonLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(JsonFormatter())
        self.logger = logging.getLogger("clouddesk.tests.json")
        self.logger.handlers = [self.handler]
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

    def tearDown(self) -> None:
        self.logger.handlers.clear()

    def test_json_log_has_correlation_ids_and_extra_fields(self) -> None:
        with log_context(request_id="req-123", workflow_id="flow-456"):
            self.logger.info("ticket received", extra={"ticket_id": "CD-1001"})

        payload = json.loads(self.stream.getvalue())
        self.assertEqual(payload["message"], "ticket received")
        self.assertEqual(payload["request_id"], "req-123")
        self.assertEqual(payload["workflow_id"], "flow-456")
        self.assertEqual(payload["ticket_id"], "CD-1001")
        self.assertEqual(payload["level"], "INFO")
        self.assertIsNone(get_request_id())
        self.assertIsNone(get_workflow_id())

    def test_json_log_always_contains_correlation_keys(self) -> None:
        self.logger.warning("no context")

        payload = json.loads(self.stream.getvalue())
        self.assertIn("request_id", payload)
        self.assertIn("workflow_id", payload)
        self.assertIsNone(payload["request_id"])
        self.assertIsNone(payload["workflow_id"])


if __name__ == "__main__":
    unittest.main()
