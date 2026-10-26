"""P1-2 tests for health routes and N3 request correlation."""

from __future__ import annotations

import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from app.core.logging import get_request_id
from app.main import APP_VERSION, create_app
from app.middleware import REQUEST_ID_HEADER


class HealthRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_health_returns_version_without_authentication(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "version": APP_VERSION})

    def test_liveness_is_minimal_and_dependency_free(self) -> None:
        response = self.client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readiness_has_extensible_dependency_results(self) -> None:
        response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "version": APP_VERSION, "dependencies": {}},
        )


class RequestIdMiddlewareTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()

        @app.get("/_test/request-context")
        async def request_context() -> dict[str, str | None]:
            return {"request_id": get_request_id()}

        self.client = TestClient(app)

    def test_n3_generates_uuid_when_header_is_missing(self) -> None:
        response = self.client.get("/health/live")

        request_id = response.headers[REQUEST_ID_HEADER]
        self.assertEqual(str(UUID(request_id)), request_id)

    def test_n3_preserves_caller_request_id_and_binds_log_context(self) -> None:
        response = self.client.get(
            "/_test/request-context",
            headers={REQUEST_ID_HEADER: "client-request-123"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers[REQUEST_ID_HEADER], "client-request-123")
        self.assertEqual(response.json(), {"request_id": "client-request-123"})
        self.assertIsNone(get_request_id())

    def test_n3_header_is_present_on_not_found_response(self) -> None:
        response = self.client.get("/route-that-does-not-exist")

        self.assertEqual(response.status_code, 404)
        self.assertIn(REQUEST_ID_HEADER, response.headers)

    def test_n3_header_is_present_on_unhandled_error_response(self) -> None:
        app = create_app()

        @app.get("/_test/unhandled-error")
        async def unhandled_error() -> None:
            raise RuntimeError("test failure")

        response = TestClient(app, raise_server_exceptions=False).get(
            "/_test/unhandled-error",
            headers={REQUEST_ID_HEADER: "error-request-123"},
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "Internal server error"})
        self.assertEqual(response.headers[REQUEST_ID_HEADER], "error-request-123")

    def test_request_id_is_exposed_to_allowed_browser_origin(self) -> None:
        response = self.client.get(
            "/health/live",
            headers={"Origin": "http://localhost:3000"},
        )

        exposed = response.headers.get("access-control-expose-headers", "").lower()
        self.assertIn(REQUEST_ID_HEADER.lower(), exposed)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://localhost:3000",
        )


if __name__ == "__main__":
    unittest.main()
