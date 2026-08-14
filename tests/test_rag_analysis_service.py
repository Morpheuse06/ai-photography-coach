"""Tests for the complete mock RAG photography analysis pipeline."""

import asyncio
from pathlib import Path
import unittest

from photography_coach.errors import ModelTimeoutError
from photography_coach.image_validation import ValidatedImage
from photography_coach.knowledge.embeddings import DeterministicEmbeddingProvider
from photography_coach.knowledge.schemas import KnowledgeCorpus
from photography_coach.knowledge.search import InMemoryKnowledgeIndex
from photography_coach.providers.base import ProviderResult
from photography_coach.providers.mock import MockPhotographyProvider
from photography_coach.providers.mock_planner import MockRetrievalPlanner
from photography_coach.providers.planner import PlannerResult
from photography_coach.services.rag_analysis import RagAnalysisService
from photography_coach.services.rag_context import RagContextService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _image() -> ValidatedImage:
    return ValidatedImage(
        format="JPEG",
        media_type="image/jpeg",
        width=1200,
        height=800,
        size_bytes=240_000,
    )


async def _context_service(planner=None) -> RagContextService:
    corpus_path = (
        PROJECT_ROOT / "knowledge/chunks/ai-photography-coach-handbook.json"
    )
    corpus = KnowledgeCorpus.model_validate_json(
        corpus_path.read_text(encoding="utf-8")
    )
    index = await InMemoryKnowledgeIndex.build(
        corpus,
        DeterministicEmbeddingProvider(dimensions=128),
    )
    return RagContextService(
        planner or MockRetrievalPlanner(),
        index,
        timeout_seconds=1,
    )


class CapturingPhotographyProvider(MockPhotographyProvider):
    def __init__(self) -> None:
        self.knowledge_context: str | None = None

    async def analyze(
        self,
        image_bytes: bytes,
        media_type: str,
        shooting_intent: str | None,
        knowledge_context: str | None = None,
    ) -> ProviderResult:
        self.knowledge_context = knowledge_context
        return await super().analyze(
            image_bytes,
            media_type,
            shooting_intent,
            knowledge_context,
        )


class UsagePlanner(MockRetrievalPlanner):
    async def create_plan(self, image_bytes, media_type, shooting_intent):
        result = await super().create_plan(image_bytes, media_type, shooting_intent)
        return PlannerResult(
            plan=result.plan,
            input_tokens=100,
            output_tokens=40,
            total_tokens=140,
        )


class UsagePhotographyProvider(CapturingPhotographyProvider):
    async def analyze(
        self,
        image_bytes,
        media_type,
        shooting_intent,
        knowledge_context=None,
    ):
        result = await super().analyze(
            image_bytes,
            media_type,
            shooting_intent,
            knowledge_context,
        )
        return ProviderResult(
            report=result.report,
            input_tokens=200,
            output_tokens=80,
            total_tokens=280,
        )


class RagAnalysisServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_passes_retrieved_context_to_final_provider(self) -> None:
        provider = CapturingPhotographyProvider()
        service = RagAnalysisService(
            provider,
            await _context_service(),
            report_timeout_seconds=1,
        )

        result = await service.analyze(
            b"validated-image",
            _image(),
            "表现安静的环境人像",
        )

        self.assertIsNotNone(provider.knowledge_context)
        self.assertIn("chunk_id", provider.knowledge_context or "")
        self.assertGreater(len(result.prepared_knowledge.retrieval.chunks), 0)
        self.assertEqual(
            result.response.metadata.prompt_version,
            "photography-coach-rag-v1.0",
        )

    async def test_sums_planner_and_report_model_usage(self) -> None:
        service = RagAnalysisService(
            UsagePhotographyProvider(),
            await _context_service(UsagePlanner()),
            report_timeout_seconds=1,
        )

        result = await service.analyze(b"image", _image(), None)

        self.assertEqual(result.response.metadata.usage.input_tokens, 300)
        self.assertEqual(result.response.metadata.usage.output_tokens, 120)
        self.assertEqual(result.response.metadata.usage.total_tokens, 420)

    async def test_rejects_non_positive_report_timeout(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            RagAnalysisService(
                CapturingPhotographyProvider(),
                await _context_service(),
                report_timeout_seconds=0,
            )


class SlowPhotographyProvider(CapturingPhotographyProvider):
    async def analyze(
        self,
        image_bytes,
        media_type,
        shooting_intent,
        knowledge_context=None,
    ):
        del image_bytes, media_type, shooting_intent, knowledge_context
        await asyncio.sleep(1)
        raise AssertionError("the timeout should cancel this call")


class RagReportTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_enforces_final_report_timeout(self) -> None:
        service = RagAnalysisService(
            SlowPhotographyProvider(),
            await _context_service(),
            report_timeout_seconds=0.001,
        )

        with self.assertRaises(ModelTimeoutError):
            await service.analyze(b"image", _image(), None)


if __name__ == "__main__":
    unittest.main()
