"""Tests for configuration-driven service construction."""

import unittest
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, patch

from photography_coach.config import Settings, get_settings
from photography_coach.dependencies import (
    build_rag_analysis_service,
    get_analysis_service,
)
from photography_coach.errors import ModelUnavailableError
from photography_coach.providers.dashscope import DashScopePhotographyProvider
from photography_coach.providers.dashscope_embedding import DashScopeEmbeddingProvider
from photography_coach.providers.dashscope_planner import DashScopeRetrievalPlanner
from photography_coach.providers.dashscope_reranker import (
    DashScopeRerankingProvider,
)
from photography_coach.knowledge.reranking import (
    DeterministicRerankingProvider,
)
from photography_coach.providers.mock import MockPhotographyProvider


class DependencyFactoryTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_analysis_service.cache_clear()
        get_settings.cache_clear()

    def test_builds_dashscope_provider_from_settings(self) -> None:
        settings = Settings(
            model_provider="dashscope",
            model_api_key="test-key",
            model_name="qwen3.7-plus",
            model_base_url="https://workspace.example/compatible-mode/v1",
        )

        with patch(
            "photography_coach.dependencies.get_settings",
            return_value=settings,
        ):
            service = get_analysis_service()

        self.assertIsInstance(service._provider, DashScopePhotographyProvider)
        self.assertEqual(service._provider.model, "qwen3.7-plus")

    def test_requires_an_api_key_for_dashscope(self) -> None:
        settings = Settings(
            model_provider="dashscope",
            model_api_key=None,
            model_name="qwen3.7-plus",
        )

        with patch(
            "photography_coach.dependencies.get_settings",
            return_value=settings,
        ):
            with self.assertRaises(ModelUnavailableError):
                get_analysis_service()


class RagDependencyFactoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_complete_mock_rag_service_without_external_calls(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                _env_file=None,
                model_provider="mock",
                rag_enabled=True,
                embedding_dimensions=128,
                chroma_path=Path(directory),
                knowledge_corpus_path=(
                    project_root
                    / "knowledge/chunks/ai-photography-coach-handbook.json"
                ),
            )

            service = await build_rag_analysis_service(settings)

            self.assertIsInstance(service._provider, MockPhotographyProvider)
            self.assertEqual(
                service._rag_context_service._index._embedding_provider.name,
                "deterministic",
            )
            self.assertIsInstance(
                service._rag_context_service._reranking_service._provider,
                DeterministicRerankingProvider,
            )

    async def test_refuses_to_build_when_rag_switch_is_off(self) -> None:
        settings = Settings(_env_file=None, rag_enabled=False)

        with self.assertRaisesRegex(ModelUnavailableError, "not enabled"):
            await build_rag_analysis_service(settings)

    async def test_builds_dashscope_rag_adapters_from_settings(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        settings = Settings(
            _env_file=None,
            model_provider="dashscope",
            model_api_key="test-key",
            model_name="qwen3-vl-flash",
            model_base_url="https://workspace.example/compatible-mode/v1",
            rerank_base_url="https://workspace.example/compatible-api/v1",
            rag_enabled=True,
            rag_planner_model="qwen3-vl-flash",
            embedding_model="qwen3.7-text-embedding",
            embedding_dimensions=1_024,
            knowledge_corpus_path=(
                project_root / "knowledge/chunks/ai-photography-coach-handbook.json"
            ),
        )
        fake_index = AsyncMock()

        with patch(
            "photography_coach.dependencies.ChromaKnowledgeIndex.build",
            new=AsyncMock(return_value=fake_index),
        ) as build_index:
            service = await build_rag_analysis_service(settings)

        embedding_provider = build_index.await_args.args[1]
        planner = service._rag_context_service._planner
        reranker = service._rag_context_service._reranking_service._provider
        self.assertIsInstance(service._provider, DashScopePhotographyProvider)
        self.assertIsInstance(planner, DashScopeRetrievalPlanner)
        self.assertIsInstance(embedding_provider, DashScopeEmbeddingProvider)
        self.assertIsInstance(reranker, DashScopeRerankingProvider)
        self.assertEqual(embedding_provider.model, "qwen3.7-text-embedding")
        self.assertEqual(embedding_provider.dimensions, 1_024)
        self.assertEqual(reranker.model, "qwen3-rerank")

    async def test_dashscope_rag_requires_rerank_base_url(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        settings = Settings(
            _env_file=None,
            model_provider="dashscope",
            model_api_key="test-key",
            rag_enabled=True,
            rerank_base_url=None,
            knowledge_corpus_path=(
                project_root / "knowledge/chunks/ai-photography-coach-handbook.json"
            ),
        )

        with self.assertRaisesRegex(ModelUnavailableError, "RERANK_BASE_URL"):
            await build_rag_analysis_service(settings)

    async def test_dashscope_rag_requires_api_key_before_external_work(self) -> None:
        settings = Settings(
            _env_file=None,
            model_provider="dashscope",
            model_api_key=None,
            rag_enabled=True,
        )

        with self.assertRaises(ModelUnavailableError):
            await build_rag_analysis_service(settings)


if __name__ == "__main__":
    unittest.main()
