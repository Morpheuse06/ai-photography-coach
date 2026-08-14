"""Tests for the mock end-to-end RAG context preparation flow."""

import asyncio
import json
from pathlib import Path
import unittest

from photography_coach.errors import ModelTimeoutError
from photography_coach.knowledge.embeddings import DeterministicEmbeddingProvider
from photography_coach.knowledge.schemas import KnowledgeCorpus
from photography_coach.knowledge.search import InMemoryKnowledgeIndex
from photography_coach.providers.mock_planner import MockRetrievalPlanner
from photography_coach.providers.planner import RetrievalPlanner
from photography_coach.services.rag_context import (
    RagContextService,
    format_retrieval_context,
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

        self.assertLessEqual(len(prepared.retrieval.chunks), 5)
        self.assertEqual(prepared.planner_provider, "mock")
        self.assertEqual(prepared.planner_prompt_version, "photography-retrieval-v1.1")
        self.assertEqual(
            prepared.retrieval.embedding_model,
            "deterministic-char-bigram-v1",
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

    async def test_rejects_non_positive_timeout(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            RagContextService(
                MockRetrievalPlanner(),
                await _index(),
                timeout_seconds=0,
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
