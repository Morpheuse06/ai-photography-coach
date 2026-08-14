"""Provider-independent contracts and a deterministic local text reranker."""

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RerankDocument:
    """One candidate document with a stable ID and complete searchable text."""

    document_id: str
    text: str

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise ValueError("document_id cannot be blank")
        if not self.text.strip():
            raise ValueError("rerank document text cannot be blank")


@dataclass(frozen=True, slots=True)
class RerankedItem:
    """One selected candidate and its provider-assigned relevance score."""

    document_index: int
    relevance_score: float

    def __post_init__(self) -> None:
        if self.document_index < 0:
            raise ValueError("document_index cannot be negative")
        if not isfinite(self.relevance_score):
            raise ValueError("relevance_score must be finite")


@dataclass(frozen=True, slots=True)
class RerankResult:
    """Ordered reranking output plus optional provider usage metadata."""

    items: tuple[RerankedItem, ...]
    input_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.input_tokens is not None and self.input_tokens < 0:
            raise ValueError("input_tokens cannot be negative")


class RerankingProvider(Protocol):
    """Interface shared by local and external text reranking providers."""

    name: str
    model: str

    async def rerank(
        self,
        query: str,
        documents: Sequence[RerankDocument],
        *,
        top_n: int,
    ) -> RerankResult:
        """Return up to top_n candidate indexes in descending relevance order."""
        ...


class DeterministicRerankingProvider:
    """Rank local test documents by normalized character-bigram overlap."""

    name = "deterministic"
    model = "deterministic-character-bigram-rerank-v1"

    async def rerank(
        self,
        query: str,
        documents: Sequence[RerankDocument],
        *,
        top_n: int,
    ) -> RerankResult:
        normalized_query = query.strip()
        _validate_request(normalized_query, documents, top_n)
        query_bigrams = _character_bigrams(normalized_query)
        scored_items = [
            RerankedItem(
                document_index=index,
                relevance_score=_overlap_score(
                    query_bigrams,
                    _character_bigrams(document.text),
                ),
            )
            for index, document in enumerate(documents)
        ]
        scored_items.sort(
            key=lambda item: (-item.relevance_score, item.document_index)
        )
        return RerankResult(items=tuple(scored_items[:top_n]))


def validate_rerank_result(
    result: RerankResult,
    *,
    document_count: int,
    top_n: int,
) -> None:
    """Reject malformed provider output before it can select wrong chunks."""

    if not result.items:
        raise ValueError("reranker returned no items")
    if len(result.items) > top_n:
        raise ValueError("reranker returned more items than top_n")

    indexes = [item.document_index for item in result.items]
    if len(indexes) != len(set(indexes)):
        raise ValueError("reranker returned duplicate document indexes")
    if any(index >= document_count for index in indexes):
        raise ValueError("reranker returned an out-of-range document index")


def _validate_request(
    query: str,
    documents: Sequence[RerankDocument],
    top_n: int,
) -> None:
    if not query:
        raise ValueError("rerank query cannot be blank")
    if not documents:
        raise ValueError("rerank documents cannot be empty")
    if top_n < 1 or top_n > len(documents):
        raise ValueError("top_n must be between 1 and the document count")

    document_ids = [document.document_id for document in documents]
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("rerank document IDs must be unique")


def _character_bigrams(text: str) -> set[str]:
    normalized = "".join(
        character.casefold()
        for character in text
        if not character.isspace()
    )
    if len(normalized) < 2:
        return {normalized}
    return {
        normalized[index : index + 2]
        for index in range(len(normalized) - 1)
    }


def _overlap_score(query_bigrams: set[str], document_bigrams: set[str]) -> float:
    if not query_bigrams or not document_bigrams:
        return 0.0
    return len(query_bigrams & document_bigrams) / len(query_bigrams)
