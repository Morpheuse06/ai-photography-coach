"""HTTP tests for the opt-in RAG photo analysis endpoint."""

import asyncio
from io import BytesIO
from pathlib import Path
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from photography_coach.dependencies import get_rag_analysis_service
from photography_coach.errors import ModelUnavailableError
from photography_coach.knowledge.embeddings import DeterministicEmbeddingProvider
from photography_coach.knowledge.schemas import KnowledgeCorpus
from photography_coach.knowledge.search import InMemoryKnowledgeIndex
from photography_coach.main import app
from photography_coach.providers.mock import MockPhotographyProvider
from photography_coach.providers.mock_planner import MockRetrievalPlanner
from photography_coach.services.rag_analysis import RagAnalysisService
from photography_coach.services.rag_context import RagContextService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 12), color=(40, 80, 120)).save(buffer, format="PNG")
    return buffer.getvalue()


async def _mock_rag_service() -> RagAnalysisService:
    corpus = KnowledgeCorpus.model_validate_json(
        (
            PROJECT_ROOT / "knowledge/chunks/ai-photography-coach-handbook.json"
        ).read_text(encoding="utf-8")
    )
    index = await InMemoryKnowledgeIndex.build(
        corpus,
        DeterministicEmbeddingProvider(dimensions=128),
    )
    context_service = RagContextService(
        MockRetrievalPlanner(),
        index,
        timeout_seconds=1,
    )
    return RagAnalysisService(
        MockPhotographyProvider(),
        context_service,
        report_timeout_seconds=1,
    )


class RagAnalysisEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = asyncio.run(_mock_rag_service())
        app.dependency_overrides[get_rag_analysis_service] = lambda: self.service
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()

    def test_analyzes_valid_photo_through_rag_pipeline(self) -> None:
        response = self.client.post(
            "/api/v2/analyze",
            files={"photo": ("sample.png", _png_bytes(), "image/png")},
            data={"intent": "表现安静的环境人像"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["metadata"]["prompt_version"],
            "photography-coach-rag-v1.1",
        )
        self.assertEqual(body["metadata"]["image"]["width"], 16)
        self.assertEqual(len(body["report"]["dimensions"]), 5)

    def test_reuses_image_validation_for_rag_endpoint(self) -> None:
        response = self.client.post(
            "/api/v2/analyze",
            files={"photo": ("fake.jpg", b"not an image", "image/jpeg")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_image")

    def test_reports_when_rag_is_not_enabled(self) -> None:
        async def disabled_service():
            raise ModelUnavailableError("RAG analysis is not enabled.")

        app.dependency_overrides[get_rag_analysis_service] = disabled_service

        response = self.client.post(
            "/api/v2/analyze",
            files={"photo": ("sample.png", _png_bytes(), "image/png")},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "model_unavailable")


if __name__ == "__main__":
    unittest.main()
