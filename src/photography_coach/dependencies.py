"""FastAPI dependency factories for configured application services."""

from functools import lru_cache

from photography_coach.config import Settings, get_settings
from photography_coach.errors import ModelUnavailableError
from photography_coach.knowledge.chroma_store import ChromaKnowledgeIndex
from photography_coach.knowledge.embeddings import DeterministicEmbeddingProvider
from photography_coach.knowledge.reranking import (
    DeterministicRerankingProvider,
    RerankingProvider,
)
from photography_coach.knowledge.schemas import KnowledgeCorpus
from photography_coach.providers.base import PhotographyProvider
from photography_coach.providers.dashscope import (
    DEFAULT_DASHSCOPE_BASE_URL,
    DashScopePhotographyProvider,
)
from photography_coach.providers.mock import MockPhotographyProvider
from photography_coach.providers.dashscope_embedding import DashScopeEmbeddingProvider
from photography_coach.providers.dashscope_planner import DashScopeRetrievalPlanner
from photography_coach.providers.dashscope_reranker import (
    DashScopeRerankingProvider,
)
from photography_coach.providers.mock_planner import MockRetrievalPlanner
from photography_coach.providers.planner import RetrievalPlanner
from photography_coach.providers.responses_compatible import (
    ResponsesCompatiblePhotographyProvider,
)
from photography_coach.services.analysis import AnalysisService
from photography_coach.services.rag_analysis import RagAnalysisService
from photography_coach.services.rag_context import RagContextService
from photography_coach.services.retrieval_reranking import (
    RetrievalRerankingService,
)


@lru_cache
def get_analysis_service() -> AnalysisService:
    """Build one analysis service from validated environment settings."""
    settings = get_settings()
    provider = _build_photography_provider(settings)

    return AnalysisService(
        provider,
        timeout_seconds=settings.model_timeout_seconds,
    )


async def get_rag_analysis_service() -> RagAnalysisService:
    """Build the configured RAG service when its explicit switch is enabled."""

    return await build_rag_analysis_service(get_settings())


async def build_rag_analysis_service(settings: Settings) -> RagAnalysisService:
    """Assemble a mock or DashScope RAG pipeline from validated settings."""

    if not settings.rag_enabled:
        raise ModelUnavailableError("RAG analysis is not enabled.")

    provider = _build_photography_provider(settings)
    corpus = KnowledgeCorpus.model_validate_json(
        settings.knowledge_corpus_path.read_text(encoding="utf-8")
    )

    if settings.model_provider == "mock":
        planner: RetrievalPlanner = MockRetrievalPlanner()
        embedding_provider = DeterministicEmbeddingProvider(
            dimensions=settings.embedding_dimensions
        )
        reranking_provider: RerankingProvider = DeterministicRerankingProvider()
    elif settings.model_provider == "dashscope":
        api_key = _require_api_key(settings)
        base_url = settings.model_base_url or DEFAULT_DASHSCOPE_BASE_URL
        if settings.rerank_base_url is None:
            raise ModelUnavailableError(
                "RERANK_BASE_URL is required for DashScope RAG."
            )
        planner = DashScopeRetrievalPlanner(
            api_key=api_key,
            model=settings.rag_planner_model or settings.model_name,
            base_url=base_url,
            timeout_seconds=settings.rag_context_timeout_seconds,
            max_retries=settings.model_max_retries,
        )
        embedding_provider = DashScopeEmbeddingProvider(
            api_key=api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            max_batch_size=settings.embedding_max_batch_size,
            base_url=base_url,
            timeout_seconds=settings.rag_context_timeout_seconds,
            max_retries=settings.model_max_retries,
        )
        reranking_provider = DashScopeRerankingProvider(
            api_key=api_key,
            base_url=settings.rerank_base_url,
            model=settings.rerank_model,
            timeout_seconds=settings.rag_context_timeout_seconds,
            max_retries=settings.model_max_retries,
        )
    else:
        raise ModelUnavailableError(
            "RAG currently supports MODEL_PROVIDER=mock or dashscope."
        )

    index = await ChromaKnowledgeIndex.build(
        corpus,
        embedding_provider,
        persist_path=settings.chroma_path,
        batch_size=settings.embedding_max_batch_size,
    )
    context_service = RagContextService(
        planner,
        index,
        reranking_service=RetrievalRerankingService(
            reranking_provider,
            final_max_chunks=settings.rerank_final_max_chunks,
        ),
        candidate_k_per_query=settings.rerank_candidate_k,
        timeout_seconds=settings.rag_context_timeout_seconds,
    )
    return RagAnalysisService(
        provider,
        context_service,
        report_timeout_seconds=settings.model_timeout_seconds,
    )


def _build_photography_provider(settings: Settings) -> PhotographyProvider:
    if settings.model_provider == "mock":
        return MockPhotographyProvider()
    if settings.model_provider == "dashscope":
        return DashScopePhotographyProvider(
            api_key=_require_api_key(settings),
            model=settings.model_name,
            base_url=settings.model_base_url or DEFAULT_DASHSCOPE_BASE_URL,
            timeout_seconds=settings.model_timeout_seconds,
            max_retries=settings.model_max_retries,
        )

    return ResponsesCompatiblePhotographyProvider(
        api_key=_require_api_key(settings),
        model=settings.model_name,
        base_url=settings.model_base_url,
        timeout_seconds=settings.model_timeout_seconds,
        max_retries=settings.model_max_retries,
    )


def _require_api_key(settings: Settings) -> str:
    if settings.model_api_key is None:
        raise ModelUnavailableError(
            f"MODEL_API_KEY is required when MODEL_PROVIDER={settings.model_provider}."
        )
    return settings.model_api_key.get_secret_value()
