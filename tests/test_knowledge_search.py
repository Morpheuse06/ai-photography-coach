"""Tests for in-memory photography knowledge vector search."""

from pathlib import Path
import unittest

from photography_coach.knowledge.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingResult,
)
from photography_coach.knowledge.retrieval import (
    PhotoObservation,
    RetrievalPlan,
    RetrievalQuery,
    VisibleEvidence,
)
from photography_coach.knowledge.schemas import KnowledgeCorpus
from photography_coach.knowledge.search import (
    InMemoryKnowledgeIndex,
    build_chunk_embedding_text,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _corpus() -> KnowledgeCorpus:
    path = PROJECT_ROOT / "knowledge/chunks/ai-photography-coach-handbook.json"
    return KnowledgeCorpus.model_validate_json(path.read_text(encoding="utf-8"))


def _plan(*queries: RetrievalQuery, max_total_chunks: int = 6) -> RetrievalPlan:
    evidence = [
        VisibleEvidence(
            evidence_id="lighting-window",
            dimension="lighting",
            description="右侧窗户区域明显比人物面部更亮，人物面部的细节相对较弱。",
            location="画面右侧和中部",
        ),
        VisibleEvidence(
            evidence_id="composition-background",
            dimension="composition",
            description="画面边缘的明亮物体和背景家具与主体争夺一部分观看注意力。",
            location="画面左上方和右侧边缘",
        ),
    ]
    return RetrievalPlan(
        observation=PhotoObservation(
            scene_summary="人物靠近花束，右侧窗户形成明显的明暗反差。",
            evidence=evidence,
            unknowns=["无法仅凭图片确定相机、镜头和曝光参数"],
        ),
        queries=list(queries),
        max_total_chunks=max_total_chunks,
    )


def _lighting_query(**overrides) -> RetrievalQuery:
    payload = {
        "query_id": "lighting-query",
        "dimension": "lighting",
        "evidence_ids": ["lighting-window"],
        "query_text": "在高反差中选择保留主体细节或清楚轮廓，处理窗边逆光人物。",
        "teaching_goal": "处理主体和明亮背景之间的反差",
        "top_k": 2,
    }
    payload.update(overrides)
    return RetrievalQuery.model_validate(payload)


class ChunkEmbeddingTextTests(unittest.TestCase):
    def test_includes_content_and_retrieval_metadata(self) -> None:
        chunk = _corpus().chunks[0]

        text = build_chunk_embedding_text(chunk)

        self.assertIn(chunk.content, text)
        self.assertIn(chunk.applicable_scenarios[0], text)
        self.assertIn(chunk.actionable_guidance[0], text)
        self.assertIn(chunk.limitations[0], text)
        self.assertIn(chunk.tags[0], text)


class InMemoryKnowledgeIndexTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.provider = DeterministicEmbeddingProvider(dimensions=128)
        self.index = await InMemoryKnowledgeIndex.build(_corpus(), self.provider)

    async def test_retrieves_only_chunks_from_query_dimension(self) -> None:
        result = await self.index.retrieve(_plan(_lighting_query()))

        self.assertEqual(len(result.chunks), 2)
        self.assertTrue(
            all(match.chunk.dimension == "lighting" for match in result.chunks)
        )

    async def test_exact_section_language_ranks_expected_chunk_first(self) -> None:
        result = await self.index.retrieve(_plan(_lighting_query(top_k=1)))

        self.assertEqual(
            result.chunks[0].chunk.chunk_id,
            "ai-photography-coach-handbook-lighting-contrast-silhouette",
        )

    async def test_respects_global_chunk_limit_across_queries(self) -> None:
        composition_query = RetrievalQuery(
            query_id="composition-query",
            dimension="composition",
            evidence_ids=["composition-background"],
            query_text="如何清理背景边缘的明亮杂物，减少背景与人物主体争夺注意力？",
            teaching_goal="简化背景并明确主体",
            top_k=3,
        )

        result = await self.index.retrieve(
            _plan(_lighting_query(top_k=3), composition_query, max_total_chunks=3)
        )

        self.assertEqual(len(result.chunks), 3)
        self.assertEqual(
            {result.chunks[0].chunk.dimension, result.chunks[1].chunk.dimension},
            {"lighting", "composition"},
        )

    async def test_deduplicates_chunk_matched_by_multiple_queries(self) -> None:
        second_query = _lighting_query(
            query_id="lighting-query-two",
            query_text="高反差逆光下应怎样决定保留面部细节还是表现主体外轮廓？",
            top_k=1,
        )

        result = await self.index.retrieve(
            _plan(_lighting_query(top_k=1), second_query)
        )

        self.assertEqual(len(result.chunks), 1)
        self.assertEqual(
            result.chunks[0].matched_query_ids,
            ("lighting-query", "lighting-query-two"),
        )

    async def test_records_embedding_model_metadata(self) -> None:
        result = await self.index.retrieve(_plan(_lighting_query(top_k=1)))

        self.assertEqual(result.embedding_provider, "deterministic")
        self.assertEqual(result.embedding_model, "deterministic-char-bigram-v1")
        self.assertEqual(result.embedding_dimensions, 128)

    async def test_builds_corpus_in_bounded_batches(self) -> None:
        index = await InMemoryKnowledgeIndex.build(
            _corpus(),
            self.provider,
            batch_size=2,
        )

        result = await index.retrieve(_plan(_lighting_query(top_k=1)))

        self.assertEqual(len(result.chunks), 1)


class IncorrectEmbeddingProvider:
    name = "incorrect"
    model = "incorrect-v1"
    dimensions = 3

    async def embed_documents(self, texts) -> EmbeddingResult:
        del texts
        return EmbeddingResult(vectors=((1.0, 0.0, 0.0),))

    async def embed_query(self, text: str) -> EmbeddingResult:
        del text
        return EmbeddingResult(vectors=((1.0, 0.0, 0.0),))


class IndexProviderValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_provider_that_returns_wrong_vector_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "vectors for"):
            await InMemoryKnowledgeIndex.build(
                _corpus(),
                IncorrectEmbeddingProvider(),
            )

    async def test_rejects_invalid_batch_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "batch_size"):
            await InMemoryKnowledgeIndex.build(
                _corpus(),
                DeterministicEmbeddingProvider(),
                batch_size=0,
            )


if __name__ == "__main__":
    unittest.main()
