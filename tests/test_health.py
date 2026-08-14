"""HTTP-level tests for the application health endpoint."""

import unittest

from fastapi.testclient import TestClient

from photography_coach.config import Settings
from photography_coach.main import create_app


class HealthEndpointTests(unittest.TestCase):
    def test_health_endpoint_returns_ok(self) -> None:
        application = create_app(
            Settings(_env_file=None, rag_enabled=False)
        )
        with TestClient(application) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response.headers["content-type"], "application/json")


if __name__ == "__main__":
    unittest.main()
