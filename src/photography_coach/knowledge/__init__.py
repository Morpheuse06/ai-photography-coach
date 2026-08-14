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
    "PhotoObservation",
    "RetrievalPlan",
    "RetrievalQuery",
    "SourceKind",
    "UsageRights",
    "VisibleEvidence",
]
