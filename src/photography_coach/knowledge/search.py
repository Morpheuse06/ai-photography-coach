"""In-memory vector search for validated photography knowledge chunks."""

from dataclasses import dataclass
from math import isfinite, sqrt

from photography_coach.knowledge.embeddings import (
    EmbeddingProvider,
    EmbeddingVector,
)
from photography_coach.knowledge.retrieval import RetrievalPlan, RetrievalQuery
from photography_coach.knowledge.schemas import (
    KnowledgeChunk,
    KnowledgeCorpus,
    KnowledgeDimension,
)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One knowledge chunk selected for one or more planned queries."""

    chunk: KnowledgeChunk
    score: float
    matched_query_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isfinite(self.score):
            raise ValueError("retrieval score must be finite")
        if not self.matched_query_ids:
            raise ValueError("matched_query_ids cannot be empty")


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Bounded, deduplicated knowledge returned for one retrieval plan."""

    chunks: tuple[RetrievedChunk, ...]
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int


@dataclass(frozen=True, slots=True)
class _IndexedChunk:
    chunk: KnowledgeChunk
    vector: EmbeddingVector


class InMemoryKnowledgeIndex:
    """A small educational vector index that is rebuilt when the process starts."""

    def __init__(
        self,
        *,
        entries: tuple[_IndexedChunk, ...],
        embedding_provider: EmbeddingProvider,
    ) -> None:
        if not entries:
            raise ValueError("knowledge index entries cannot be empty")
        self._entries = entries
        self._embedding_provider = embedding_provider

    @classmethod
    async def build(
        cls,
        corpus: KnowledgeCorpus,
        embedding_provider: EmbeddingProvider,
        *,
        batch_size: int = 50,
    ) -> "InMemoryKnowledgeIndex":
        """Embed all chunks in bounded batches and build an in-memory index."""

        if batch_size < 1 or batch_size > 100:
            raise ValueError("batch_size must be between 1 and 100")

        entries: list[_IndexedChunk] = []
        for start in range(0, len(corpus.chunks), batch_size):
            chunk_batch = corpus.chunks[start : start + batch_size]
            texts = [build_chunk_embedding_text(chunk) for chunk in chunk_batch]
            embedding_result = await embedding_provider.embed_documents(texts)
            _validate_embedding_result(
                expected_count=len(chunk_batch),
                expected_dimensions=embedding_provider.dimensions,
                actual_vectors=embedding_result.vectors,
            )
            entries.extend(
                _IndexedChunk(chunk=chunk, vector=vector)
                for chunk, vector in zip(
                    chunk_batch,
                    embedding_result.vectors,
                    strict=True,
                )
            )

        return cls(entries=tuple(entries), embedding_provider=embedding_provider)

    async def retrieve(self, plan: RetrievalPlan) -> RetrievalResult:
        """Execute planned searches, then deduplicate results in query order."""

        ranked_by_query: list[tuple[RetrievalQuery, list[tuple[KnowledgeChunk, float]]]] = []
        for query in plan.queries:
            query_result = await self._embedding_provider.embed_query(query.query_text)
            _validate_embedding_result(
                expected_count=1,
                expected_dimensions=self._embedding_provider.dimensions,
                actual_vectors=query_result.vectors,
            )
            matches = self._search_vector(
                query_result.vectors[0],
                dimension=query.dimension,
                top_k=query.top_k,
            )
            ranked_by_query.append((query, matches))

        selected: dict[str, RetrievedChunk] = {}
        max_rank = max((len(matches) for _, matches in ranked_by_query), default=0)
        for rank in range(max_rank):
            for query, matches in ranked_by_query:
                if rank >= len(matches):
                    continue
                chunk, score = matches[rank]
                existing = selected.get(chunk.chunk_id)
                if existing is not None:
                    selected[chunk.chunk_id] = RetrievedChunk(
                        chunk=existing.chunk,
                        score=max(existing.score, score),
                        matched_query_ids=(
                            existing.matched_query_ids
                            if query.query_id in existing.matched_query_ids
                            else existing.matched_query_ids + (query.query_id,)
                        ),
                    )
                    continue

                if len(selected) >= plan.max_total_chunks:
                    continue
                selected[chunk.chunk_id] = RetrievedChunk(
                    chunk=chunk,
                    score=score,
                    matched_query_ids=(query.query_id,),
                )

        return RetrievalResult(
            chunks=tuple(selected.values()),
            embedding_provider=self._embedding_provider.name,
            embedding_model=self._embedding_provider.model,
            embedding_dimensions=self._embedding_provider.dimensions,
        )

    def _search_vector(
        self,
        query_vector: EmbeddingVector,
        *,
        dimension: KnowledgeDimension,
        top_k: int,
    ) -> list[tuple[KnowledgeChunk, float]]:
        candidates = [
            entry for entry in self._entries if entry.chunk.dimension == dimension
        ]
        scored = [
            (entry.chunk, _cosine_similarity(query_vector, entry.vector))
            for entry in candidates
        ]
        scored.sort(key=lambda item: (-item[1], item[0].chunk_index))
        return scored[:top_k]


def build_chunk_embedding_text(chunk: KnowledgeChunk) -> str:
    """Compose the complete semantic text represented by a chunk vector."""

    return "\n".join(
        [
            f"章节：{' > '.join(chunk.section_path)}",
            f"摄影维度：{chunk.dimension}",
            f"核心知识：{chunk.content}",
            f"适用场景：{'；'.join(chunk.applicable_scenarios)}",
            f"可执行指导：{'；'.join(chunk.actionable_guidance)}",
            f"限制：{'；'.join(chunk.limitations)}",
            f"标签：{', '.join(chunk.tags)}",
        ]
    )


def _validate_embedding_result(
    *,
    expected_count: int,
    expected_dimensions: int,
    actual_vectors: tuple[EmbeddingVector, ...],
) -> None:
    if len(actual_vectors) != expected_count:
        raise ValueError(
            f"embedding provider returned {len(actual_vectors)} vectors for "
            f"{expected_count} texts"
        )
    if len(actual_vectors[0]) != expected_dimensions:
        raise ValueError(
            f"embedding provider declared {expected_dimensions} dimensions but "
            f"returned {len(actual_vectors[0])}"
        )


def _cosine_similarity(left: EmbeddingVector, right: EmbeddingVector) -> float:
    if len(left) != len(right):
        raise ValueError("cannot compare embedding vectors with different dimensions")

    left_magnitude = sqrt(sum(value * value for value in left))
    right_magnitude = sqrt(sum(value * value for value in right))
    if left_magnitude == 0 or right_magnitude == 0:
        raise ValueError("cannot compare a zero-length embedding vector")
    dot_product = sum(
        left_value * right_value
        for left_value, right_value in zip(left, right, strict=True)
    )
    return dot_product / (left_magnitude * right_magnitude)
