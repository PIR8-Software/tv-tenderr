"""App-level backend health checks.

These boot the real FastAPI app through TestClient and exercise the live
middleware/routing/auth layer with no upstream services, so they stay fast
and non-flaky while proving more than a repo layout check: the app imports,
the guard middleware enforces the token boundary, and the health contract
responds without leaking configuration.
"""

import os
import unittest

from fastapi.testclient import TestClient

import backend

SYNTHETIC_TOKEN = "synthetic-test-token"
AUTH = {"Authorization": f"Bearer {SYNTHETIC_TOKEN}"}


class BackendHealthTests(unittest.TestCase):
    def setUp(self):
        self._prior = os.environ.get(backend.API_TOKEN_ENV)
        os.environ[backend.API_TOKEN_ENV] = SYNTHETIC_TOKEN
        self.client = TestClient(backend.app)

    def tearDown(self):
        if self._prior is None:
            os.environ.pop(backend.API_TOKEN_ENV, None)
        else:
            os.environ[backend.API_TOKEN_ENV] = self._prior

    def test_health_endpoint_is_reachable_without_auth(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_health_endpoint_does_not_leak_configuration(self):
        response = self.client.get("/api/health")
        self.assertEqual(set(response.json().keys()), {"ok"})

    def test_api_rejects_requests_without_token(self):
        response = self.client.get("/api/config")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "unauthorized"})

    def test_api_accepts_valid_token(self):
        response = self.client.get("/api/config", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("hasRadarrKey", payload)
        self.assertIn("hasSonarrKey", payload)

    def test_api_rejects_invalid_token(self):
        response = self.client.get(
            "/api/config", headers={"Authorization": "Bearer wrong-token"}
        )
        self.assertEqual(response.status_code, 401)

    def test_docs_are_locked_without_token(self):
        response = self.client.get("/docs")
        self.assertEqual(response.status_code, 401)

    def test_unknown_api_route_returns_404(self):
        response = self.client.get("/api/definitely-not-a-route", headers=AUTH)
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
