"""Contracts and utilities for the photography knowledge base."""

from photography_coach.knowledge.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    EmbeddingResult,
    EmbeddingVector,
)
from photography_coach.knowledge.retrieval import (
    PhotoObservation,
    RetrievalPlan,
    RetrievalQuery,
    VisibleEvidence,
)
from photography_coach.knowledge.search import (
    InMemoryKnowledgeIndex,
    RetrievalResult,
    RetrievedChunk,
    build_chunk_embedding_text,
)
from photography_coach.knowledge.schemas import (
    KnowledgeChunk,
    KnowledgeCorpus,
    KnowledgeDimension,
    KnowledgeSource,
    SourceKind,
    UsageRights,
)

__all__ = [
    "DeterministicEmbeddingProvider",
    "EmbeddingProvider",
    "EmbeddingResult",
    "EmbeddingVector",
    "KnowledgeChunk",
    "KnowledgeCorpus",
    "KnowledgeDimension",
    "KnowledgeSource",
    "InMemoryKnowledgeIndex",
    "PhotoObservation",
    "RetrievalPlan",
    "RetrievalQuery",
    "RetrievalResult",
    "RetrievedChunk",
    "SourceKind",
    "UsageRights",
    "VisibleEvidence",
    "build_chunk_embedding_text",
]
