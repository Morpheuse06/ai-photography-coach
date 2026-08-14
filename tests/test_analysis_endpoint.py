"""End-to-end HTTP tests for the photo analysis endpoint."""

from io import BytesIO
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from photography_coach.dependencies import get_analysis_service
from photography_coach.errors import (
    ModelOutputError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from photography_coach.main import app
from photography_coach.providers.mock import MockPhotographyProvider
from photography_coach.services.analysis import AnalysisService


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 12), color=(30, 90, 150)).save(buffer, format="PNG")
    return buffer.getvalue()


class _FailingProvider:
    name = "failing-test-provider"
    model = "failing-test-model"

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def analyze(
        self,
        image_bytes: bytes,
        media_type: str,
        shooting_intent: str | None,
    ) -> object:
        del image_bytes, media_type, shooting_intent
        raise self._error


class AnalysisEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides[get_analysis_service] = lambda: AnalysisService(
            MockPhotographyProvider(),
            timeout_seconds=1,
        )
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()

    def test_analyzes_a_valid_photo_with_optional_intent(self) -> None:
        response = self.client.post(
            "/api/v1/analyze",
            files={"photo": ("sample.png", _png_bytes(), "image/png")},
            data={"intent": "我想表现安静的清晨氛围"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["metadata"]["provider"], "mock")
        self.assertEqual(body["metadata"]["prompt_version"], "photography-coach-v1.2")
        self.assertEqual(body["metadata"]["image"]["media_type"], "image/png")
        self.assertEqual(body["metadata"]["image"]["width"], 16)
        self.assertEqual(len(body["report"]["priority_actions"]), 3)
        self.assertEqual(len(body["report"]["dimensions"]), 5)

    def test_rejects_non_image_uploads(self) -> None:
        response = self.client.post(
            "/api/v1/analyze",
            files={"photo": ("fake.jpg", b"not an image", "image/jpeg")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_image")

    def test_rejects_uploads_over_ten_mebibytes(self) -> None:
        response = self.client.post(
            "/api/v1/analyze",
            files={
                "photo": (
                    "large.jpg",
                    b"x" * (10 * 1024 * 1024 + 1),
                    "image/jpeg",
                )
            },
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "image_too_large")

    def test_missing_photo_uses_the_uniform_error_shape(self) -> None:
        response = self.client.post("/api/v1/analyze")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json(),
            {
                "error": {
                    "code": "invalid_request",
                    "message": "The request data is invalid.",
                }
            },
        )

    def test_maps_expected_model_failures_to_http_errors(self) -> None:
        cases = [
            (ModelRateLimitError(), 429, "model_rate_limited"),
            (ModelOutputError(), 502, "invalid_model_output"),
            (ModelUnavailableError(), 503, "model_unavailable"),
            (ModelTimeoutError(), 504, "model_timeout"),
        ]

        for error, status_code, error_code in cases:
            with self.subTest(error_code=error_code):
                provider = _FailingProvider(error)
                app.dependency_overrides[get_analysis_service] = lambda: AnalysisService(
                    provider,  # type: ignore[arg-type]
                    timeout_seconds=1,
                )

                response = self.client.post(
                    "/api/v1/analyze",
                    files={"photo": ("sample.png", _png_bytes(), "image/png")},
                )

                self.assertEqual(response.status_code, status_code)
                self.assertEqual(response.json()["error"]["code"], error_code)


if __name__ == "__main__":
    unittest.main()
