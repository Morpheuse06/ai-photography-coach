"""Tests for persistent Chroma storage with project-managed embeddings."""

from pathlib import Path
import tempfile
import unittest

from photography_coach.knowledge.chroma_store import ChromaKnowledgeIndex
from photography_coach.knowledge.embeddings import DeterministicEmbeddingProvider
from photography_coach.knowledge.retrieval import (
    PhotoObservation,
    RetrievalPlan,
    RetrievalQuery,
    VisibleEvidence,
)
from photography_coach.knowledge.schemas import KnowledgeCorpus
from photography_coach.knowledge.search import KnowledgeIndex


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _corpus() -> KnowledgeCorpus:
    path = PROJECT_ROOT / "knowledge/chunks/ai-photography-coach-handbook.json"
    return KnowledgeCorpus.model_validate_json(path.read_text(encoding="utf-8"))


def _plan() -> RetrievalPlan:
    evidence = VisibleEvidence(
        evidence_id="lighting-contrast",
        dimension="lighting",
        description="背景亮区明显强于主体，主体的局部明暗细节相对较弱。",
        location="画面背景和主体区域",
    )
    return RetrievalPlan(
        observation=PhotoObservation(
            scene_summary="主体与明亮背景同时出现，画面具有明显亮度反差。",
            evidence=[evidence],
            unknowns=["无法仅凭图片确定相机、镜头和曝光参数"],
        ),
        queries=[
            RetrievalQuery(
                query_id="lighting-contrast-query",
                dimension="lighting",
                evidence_ids=[evidence.evidence_id],
                query_text="在高反差中选择保留主体细节或清楚轮廓，处理窗边逆光人物。",
                teaching_goal="处理主体和明亮背景之间的反差",
                top_k=2,
            )
        ],
        max_total_chunks=2,
    )


class CountingEmbeddingProvider(DeterministicEmbeddingProvider):
    def __init__(self, dimensions: int = 128) -> None:
        super().__init__(dimensions=dimensions)
        self.document_calls = 0
        self.query_calls = 0

    async def embed_documents(self, texts):
        self.document_calls += 1
        return await super().embed_documents(texts)

    async def embed_query(self, text):
        self.query_calls += 1
        return await super().embed_query(text)


class ChromaKnowledgeIndexTests(unittest.IsolatedAsyncioTestCase):
    async def test_persists_and_retrieves_dimension_filtered_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = CountingEmbeddingProvider()
            index: KnowledgeIndex = await ChromaKnowledgeIndex.build(
                _corpus(),
                provider,
                persist_path=Path(directory),
                batch_size=5,
            )

            result = await index.retrieve(_plan())

            self.assertEqual(provider.document_calls, 3)
            self.assertEqual(provider.query_calls, 1)
            self.assertEqual(len(result.chunks), 2)
            self.assertTrue(
                all(match.chunk.dimension == "lighting" for match in result.chunks)
            )
            self.assertEqual(
                result.chunks[0].chunk.chunk_id,
                "ai-photography-coach-handbook-lighting-contrast-silhouette",
            )
            self.assertTrue((Path(directory) / "chroma.sqlite3").exists())

    async def test_reuses_complete_matching_index_without_reembedding_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            first_provider = CountingEmbeddingProvider()
            await ChromaKnowledgeIndex.build(
                _corpus(),
                first_provider,
                persist_path=path,
            )
            second_provider = CountingEmbeddingProvider()

            reopened = await ChromaKnowledgeIndex.build(
                _corpus(),
                second_provider,
                persist_path=path,
            )
            result = await reopened.retrieve(_plan())

            self.assertEqual(first_provider.document_calls, 1)
            self.assertEqual(second_provider.document_calls, 0)
            self.assertEqual(second_provider.query_calls, 1)
            self.assertEqual(len(result.chunks), 2)

    async def test_rejects_index_created_with_different_embedding_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            await ChromaKnowledgeIndex.build(
                _corpus(),
                CountingEmbeddingProvider(dimensions=128),
                persist_path=path,
            )

            with self.assertRaisesRegex(ValueError, "embedding_dimensions"):
                await ChromaKnowledgeIndex.build(
                    _corpus(),
                    CountingEmbeddingProvider(dimensions=256),
                    persist_path=path,
                )

    async def test_rejects_changed_corpus_with_unchanged_source_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            corpus = _corpus()
            await ChromaKnowledgeIndex.build(
                corpus,
                CountingEmbeddingProvider(),
                persist_path=path,
            )
            changed_payload = corpus.model_dump()
            changed_payload["chunks"][0]["content"] += " 内容发生了变化。"
            changed_corpus = KnowledgeCorpus.model_validate(changed_payload)

            with self.assertRaisesRegex(ValueError, "corpus_sha256"):
                await ChromaKnowledgeIndex.build(
                    changed_corpus,
                    CountingEmbeddingProvider(),
                    persist_path=path,
                )


if __name__ == "__main__":
    unittest.main()
