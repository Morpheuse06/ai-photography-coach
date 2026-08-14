"""Select a small, dimension-balanced context from broad vector candidates."""

import asyncio

from photography_coach.knowledge.reranking import (
    RerankDocument,
    RerankResult,
    RerankingProvider,
    validate_rerank_result,
)
from photography_coach.knowledge.retrieval import RetrievalPlan, RetrievalQuery
from photography_coach.knowledge.search import (
    RetrievedChunk,
    RetrievalResult,
    build_chunk_embedding_text,
)


class RetrievalRerankingService:
    """Rerank each planned dimension, preserving coverage and query priority."""

    def __init__(
        self,
        provider: RerankingProvider,
        *,
        final_max_chunks: int = 6,
    ) -> None:
        if final_max_chunks < 1:
            raise ValueError("final_max_chunks must be positive")
        self._provider = provider
        self._final_max_chunks = final_max_chunks

    async def rerank(
        self,
        plan: RetrievalPlan,
        candidates: RetrievalResult,
    ) -> RetrievalResult:
        if self._final_max_chunks < len(plan.queries):
            raise ValueError(
                "final_max_chunks cannot be smaller than the query count"
            )

        grouped_candidates = [
            self._candidates_for_query(query, candidates)
            for query in plan.queries
        ]
        top_n_by_query = _allocate_top_n(
            grouped_candidates,
            final_max_chunks=self._final_max_chunks,
        )
        results = await asyncio.gather(
            *(
                self._rerank_query(query, query_candidates, top_n=top_n)
                for query, query_candidates, top_n in zip(
                    plan.queries,
                    grouped_candidates,
                    top_n_by_query,
                    strict=True,
                )
            )
        )

        selected: list[RetrievedChunk] = []
        input_tokens: int | None = None
        for query_candidates, result in zip(
            grouped_candidates,
            results,
            strict=True,
        ):
            input_tokens = _sum_optional(input_tokens, result.input_tokens)
            selected.extend(
                RetrievedChunk(
                    chunk=query_candidates[item.document_index].chunk,
                    score=query_candidates[item.document_index].score,
                    matched_query_ids=query_candidates[
                        item.document_index
                    ].matched_query_ids,
                    rerank_score=item.relevance_score,
                )
                for item in result.items
            )

        return RetrievalResult(
            chunks=tuple(selected),
            embedding_provider=candidates.embedding_provider,
            embedding_model=candidates.embedding_model,
            embedding_dimensions=candidates.embedding_dimensions,
            reranker_provider=self._provider.name,
            reranker_model=self._provider.model,
            reranker_input_tokens=input_tokens,
        )

    @staticmethod
    def _candidates_for_query(
        query: RetrievalQuery,
        candidates: RetrievalResult,
    ) -> tuple[RetrievedChunk, ...]:
        matches = tuple(
            match
            for match in candidates.chunks
            if query.query_id in match.matched_query_ids
        )
        if not matches:
            raise ValueError(
                f"retrieval returned no candidates for query '{query.query_id}'"
            )
        return matches

    async def _rerank_query(
        self,
        query: RetrievalQuery,
        candidates: tuple[RetrievedChunk, ...],
        *,
        top_n: int,
    ) -> RerankResult:
        documents = [
            RerankDocument(
                document_id=candidate.chunk.chunk_id,
                text=build_chunk_embedding_text(candidate.chunk),
            )
            for candidate in candidates
        ]
        rerank_query = (
            f"摄影问题：{query.query_text}\n"
            f"教学目标：{query.teaching_goal}"
        )
        result = await self._provider.rerank(
            rerank_query,
            documents,
            top_n=top_n,
        )
        validate_rerank_result(
            result,
            document_count=len(documents),
            top_n=top_n,
        )
        return result


def _allocate_top_n(
    grouped_candidates: list[tuple[RetrievedChunk, ...]],
    *,
    final_max_chunks: int,
) -> list[int]:
    allocations = [1] * len(grouped_candidates)
    remaining = final_max_chunks - len(allocations)
    for index, candidates in enumerate(grouped_candidates):
        if remaining == 0:
            break
        additional = min(len(candidates) - 1, remaining)
        allocations[index] += additional
        remaining -= additional
    return allocations


def _sum_optional(left: int | None, right: int | None) -> int | None:
    values = [value for value in (left, right) if value is not None]
    return sum(values) if values else None
