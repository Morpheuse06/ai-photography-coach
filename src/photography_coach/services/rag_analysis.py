"""End-to-end RAG photography analysis orchestration."""

import asyncio
from dataclasses import dataclass
import logging
from time import perf_counter

from photography_coach.errors import ModelTimeoutError
from photography_coach.image_validation import ValidatedImage
from photography_coach.prompts import RAG_PROMPT_VERSION
from photography_coach.providers.base import PhotographyProvider
from photography_coach.schemas.analysis import (
    AnalysisMetadata,
    AnalysisResponse,
    ImageMetadata,
    ModelUsage,
)
from photography_coach.services.rag_context import PreparedKnowledge, RagContextService


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RagAnalysisResult:
    """Public report plus internal retrieval evidence for evaluation and logs."""

    response: AnalysisResponse
    prepared_knowledge: PreparedKnowledge


class RagAnalysisService:
    """Prepare relevant knowledge, then generate one grounded coaching report."""

    def __init__(
        self,
        provider: PhotographyProvider,
        rag_context_service: RagContextService,
        *,
        report_timeout_seconds: float,
    ) -> None:
        if report_timeout_seconds <= 0:
            raise ValueError("report_timeout_seconds must be positive")
        self._provider = provider
        self._rag_context_service = rag_context_service
        self._report_timeout_seconds = report_timeout_seconds

    async def analyze(
        self,
        image_bytes: bytes,
        image: ValidatedImage,
        shooting_intent: str | None,
    ) -> RagAnalysisResult:
        started_at = perf_counter()
        prepared = await self._rag_context_service.prepare(
            image_bytes,
            image.media_type,
            shooting_intent,
        )

        try:
            provider_result = await asyncio.wait_for(
                self._provider.analyze(
                    image_bytes,
                    image.media_type,
                    shooting_intent,
                    prepared.context_text,
                ),
                timeout=self._report_timeout_seconds,
            )
        except TimeoutError as exc:
            raise ModelTimeoutError("RAG photography report generation timed out.") from exc

        latency_ms = round((perf_counter() - started_at) * 1_000)
        response = AnalysisResponse(
            report=provider_result.report,
            metadata=AnalysisMetadata(
                provider=self._provider.name,
                model=self._provider.model,
                prompt_version=RAG_PROMPT_VERSION,
                latency_ms=latency_ms,
                image=ImageMetadata(
                    media_type=image.media_type,
                    width=image.width,
                    height=image.height,
                    size_bytes=image.size_bytes,
                ),
                usage=ModelUsage(
                    input_tokens=_sum_optional(
                        prepared.input_tokens,
                        provider_result.input_tokens,
                    ),
                    output_tokens=_sum_optional(
                        prepared.output_tokens,
                        provider_result.output_tokens,
                    ),
                    total_tokens=_sum_optional(
                        prepared.total_tokens,
                        provider_result.total_tokens,
                    ),
                ),
            ),
        )
        logger.info(
            "rag_analysis_completed",
            extra={
                "event_data": {
                    "provider": self._provider.name,
                    "model": self._provider.model,
                    "prompt_version": RAG_PROMPT_VERSION,
                    "planner_provider": prepared.planner_provider,
                    "planner_model": prepared.planner_model,
                    "planner_prompt_version": prepared.planner_prompt_version,
                    "planner_attempts": prepared.planner_attempts,
                    "embedding_provider": prepared.retrieval.embedding_provider,
                    "embedding_model": prepared.retrieval.embedding_model,
                    "reranker_provider": prepared.retrieval.reranker_provider,
                    "reranker_model": prepared.retrieval.reranker_model,
                    "retrieved_chunk_ids": [
                        match.chunk.chunk_id for match in prepared.retrieval.chunks
                    ],
                    "latency_ms": latency_ms,
                }
            },
        )
        return RagAnalysisResult(
            response=response,
            prepared_knowledge=prepared,
        )


def _sum_optional(*values: int | None) -> int | None:
    available_values = [value for value in values if value is not None]
    return sum(available_values) if available_values else None
