"""Contracts and utilities for the photography knowledge base."""

from photography_coach.knowledge.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    EmbeddingResult,
    EmbeddingVector,
)
from photography_coach.knowledge.chroma_store import ChromaKnowledgeIndex
from photography_coach.knowledge.retrieval import (
    FullReportRetrievalPlan,
    PhotoObservation,
    RetrievalPlan,
    RetrievalQuery,
    VisibleEvidence,
)
from photography_coach.knowledge.search import (
    InMemoryKnowledgeIndex,
    KnowledgeIndex,
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
    "ChromaKnowledgeIndex",
    "EmbeddingProvider",
    "EmbeddingResult",
    "EmbeddingVector",
    "KnowledgeChunk",
    "KnowledgeCorpus",
    "KnowledgeDimension",
    "KnowledgeIndex",
    "KnowledgeSource",
    "InMemoryKnowledgeIndex",
    "FullReportRetrievalPlan",
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
