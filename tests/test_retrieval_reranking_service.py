"""Tests for selecting a small balanced context from broad candidates."""

from pathlib import Path
import unittest

from photography_coach.knowledge.embeddings import DeterministicEmbeddingProvider
from photography_coach.knowledge.reranking import (
    DeterministicRerankingProvider,
    RerankedItem,
    RerankResult,
)
from photography_coach.knowledge.schemas import KnowledgeCorpus
from photography_coach.knowledge.search import InMemoryKnowledgeIndex
from photography_coach.providers.mock_planner import MockRetrievalPlanner
from photography_coach.services.retrieval_reranking import (
    RetrievalRerankingService,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class UsageRerankingProvider:
    name = "usage-test"
    model = "usage-test-v1"

    def __init__(self) -> None:
        self.calls = 0

    async def rerank(self, query, documents, *, top_n):
        del query
        self.calls += 1
        return RerankResult(
            items=tuple(
                RerankedItem(
                    document_index=index,
                    relevance_score=1.0 - index / len(documents),
                )
                for index in range(top_n)
            ),
            input_tokens=10,
        )


class RetrievalRerankingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        corpus = KnowledgeCorpus.model_validate_json(
            (
                PROJECT_ROOT
                / "knowledge/chunks/ai-photography-coach-handbook.json"
            ).read_text(encoding="utf-8")
        )
        self.index = await InMemoryKnowledgeIndex.build(
            corpus,
            DeterministicEmbeddingProvider(dimensions=128),
        )
        self.plan = (
            await MockRetrievalPlanner().create_plan(
                b"image",
                "image/jpeg",
                None,
            )
        ).plan

    async def test_reranks_broad_candidates_into_five_dimension_context(self) -> None:
        candidates = await self.index.retrieve(
            self.plan,
            candidate_k_per_query=8,
            max_total_chunks=40,
        )
        service = RetrievalRerankingService(
            DeterministicRerankingProvider(),
            final_max_chunks=6,
        )

        result = await service.rerank(self.plan, candidates)

        self.assertEqual(len(candidates.chunks), 10)
        self.assertEqual(len(result.chunks), 6)
        self.assertEqual(
            {chunk.chunk.dimension for chunk in result.chunks},
            {
                "composition",
                "lighting",
                "color",
                "subject_expression",
                "visual_storytelling",
            },
        )
        self.assertTrue(
            all(chunk.rerank_score is not None for chunk in result.chunks)
        )
        self.assertEqual(result.reranker_provider, "deterministic")

    async def test_rejects_final_limit_smaller_than_dimension_count(self) -> None:
        candidates = await self.index.retrieve(
            self.plan,
            candidate_k_per_query=8,
            max_total_chunks=40,
        )
        service = RetrievalRerankingService(
            DeterministicRerankingProvider(),
            final_max_chunks=4,
        )

        with self.assertRaisesRegex(ValueError, "query count"):
            await service.rerank(self.plan, candidates)

    async def test_accumulates_usage_from_all_five_dimension_calls(self) -> None:
        candidates = await self.index.retrieve(
            self.plan,
            candidate_k_per_query=8,
            max_total_chunks=40,
        )
        provider = UsageRerankingProvider()
        service = RetrievalRerankingService(provider, final_max_chunks=6)

        result = await service.rerank(self.plan, candidates)

        self.assertEqual(provider.calls, 5)
        self.assertEqual(result.reranker_input_tokens, 50)
        self.assertEqual(result.reranker_provider, "usage-test")


if __name__ == "__main__":
    unittest.main()
