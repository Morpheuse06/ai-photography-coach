"""Tests for the mock end-to-end RAG context preparation flow."""

import asyncio
import json
from pathlib import Path
import unittest

from photography_coach.errors import ModelOutputError, ModelTimeoutError
from photography_coach.knowledge.embeddings import DeterministicEmbeddingProvider
from photography_coach.knowledge.reranking import RerankedItem, RerankResult
from photography_coach.knowledge.schemas import KnowledgeCorpus
from photography_coach.knowledge.search import InMemoryKnowledgeIndex
from photography_coach.providers.mock_planner import MockRetrievalPlanner
from photography_coach.providers.planner import PlannerResult, RetrievalPlanner
from photography_coach.services.rag_context import (
    RagContextService,
    format_retrieval_context,
)
from photography_coach.services.retrieval_reranking import (
    RetrievalRerankingService,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


async def _index() -> InMemoryKnowledgeIndex:
    corpus_path = (
        PROJECT_ROOT / "knowledge/chunks/ai-photography-coach-handbook.json"
    )
    corpus = KnowledgeCorpus.model_validate_json(
        corpus_path.read_text(encoding="utf-8")
    )
    return await InMemoryKnowledgeIndex.build(
        corpus,
        DeterministicEmbeddingProvider(dimensions=128),
    )


class RagContextServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepares_bounded_context_with_model_metadata(self) -> None:
        service = RagContextService(
            MockRetrievalPlanner(),
            await _index(),
            timeout_seconds=1,
        )

        prepared = await service.prepare(
            b"validated-image",
            "image/jpeg",
            "表现安静的环境人像",
        )

        self.assertLessEqual(len(prepared.retrieval.chunks), 6)
        self.assertEqual(
            {match.chunk.dimension for match in prepared.retrieval.chunks},
            {
                "composition",
                "lighting",
                "color",
                "subject_expression",
                "visual_storytelling",
            },
        )
        self.assertEqual(prepared.planner_provider, "mock")
        self.assertEqual(prepared.planner_prompt_version, "photography-retrieval-v1.4")
        self.assertEqual(prepared.planner_attempts, 1)
        self.assertEqual(
            prepared.retrieval.embedding_model,
            "deterministic-char-bigram-v1",
        )
        self.assertEqual(prepared.retrieval.reranker_provider, "deterministic")
        self.assertTrue(
            all(
                match.rerank_score is not None
                for match in prepared.retrieval.chunks
            )
        )
        self.assertGreaterEqual(prepared.latency_ms, 0)

    async def test_context_is_valid_json_with_traceable_chunks(self) -> None:
        service = RagContextService(
            MockRetrievalPlanner(),
            await _index(),
            timeout_seconds=1,
        )
        prepared = await service.prepare(b"image", "image/png", None)

        payload = json.loads(prepared.context_text)

        self.assertEqual(len(payload["chunks"]), len(prepared.retrieval.chunks))
        self.assertIn("reference data", payload["usage_rules"][0])
        self.assertIn("chunk_id", payload["chunks"][0])
        self.assertIn("source_locator", payload["chunks"][0])
        self.assertNotIn("score", payload["chunks"][0])

    async def test_context_formatter_does_not_add_unretrieved_chunks(self) -> None:
        service = RagContextService(
            MockRetrievalPlanner(),
            await _index(),
            timeout_seconds=1,
        )
        prepared = await service.prepare(b"image", "image/webp", None)

        rebuilt = format_retrieval_context(prepared.retrieval)

        self.assertEqual(rebuilt, prepared.context_text)

    async def test_adds_reranker_usage_to_prepared_context_usage(self) -> None:
        service = RagContextService(
            MockRetrievalPlanner(),
            await _index(),
            reranking_service=RetrievalRerankingService(
                FixedUsageReranker()
            ),
            timeout_seconds=1,
        )

        prepared = await service.prepare(b"image", "image/jpeg", None)

        self.assertEqual(prepared.input_tokens, 50)
        self.assertEqual(prepared.total_tokens, 50)

    async def test_rejects_non_positive_timeout(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            RagContextService(
                MockRetrievalPlanner(),
                await _index(),
                timeout_seconds=0,
            )

    async def test_rejects_plan_that_does_not_cover_all_report_dimensions(self) -> None:
        service = RagContextService(
            PartialPlanner(),
            await _index(),
            timeout_seconds=1,
        )

        with self.assertRaisesRegex(ModelOutputError, "every report dimension"):
            await service.prepare(b"image", "image/jpeg", None)


class PartialPlanner(MockRetrievalPlanner):
    async def create_plan(self, image_bytes, media_type, shooting_intent):
        result = await super().create_plan(image_bytes, media_type, shooting_intent)
        partial_plan = result.plan.model_copy(
            update={"queries": result.plan.queries[:3]}
        )
        return PlannerResult(plan=partial_plan)


class FixedUsageReranker:
    name = "usage-test"
    model = "usage-test-v1"

    async def rerank(self, query, documents, *, top_n):
        del query
        return RerankResult(
            items=tuple(
                RerankedItem(index, 1.0 - index / len(documents))
                for index in range(top_n)
            ),
            input_tokens=10,
        )


class SlowPlanner:
    name = "slow"
    model = "slow-v1"

    async def create_plan(self, image_bytes, media_type, shooting_intent):
        del image_bytes, media_type, shooting_intent
        await asyncio.sleep(1)
        raise AssertionError("the timeout should cancel this call")


class RagContextTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_enforces_total_planning_and_retrieval_timeout(self) -> None:
        planner: RetrievalPlanner = SlowPlanner()
        service = RagContextService(
            planner,
            await _index(),
            timeout_seconds=0.001,
        )

        with self.assertRaises(ModelTimeoutError):
            await service.prepare(b"image", "image/jpeg", None)


if __name__ == "__main__":
    unittest.main()
