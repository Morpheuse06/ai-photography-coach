"""Persistent Chroma index for project-managed photography embeddings."""

import asyncio
from hashlib import sha256
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

from photography_coach.knowledge.embeddings import EmbeddingProvider
from photography_coach.knowledge.retrieval import RetrievalPlan, RetrievalQuery
from photography_coach.knowledge.schemas import KnowledgeChunk, KnowledgeCorpus
from photography_coach.knowledge.search import (
    RetrievalResult,
    _merge_ranked_matches,
    build_chunk_embedding_text,
    validate_retrieval_overrides,
)


class ChromaKnowledgeIndex:
    """Persist supplied vectors locally and query them with metadata filters."""

    def __init__(
        self,
        *,
        collection: Any,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._collection = collection
        self._embedding_provider = embedding_provider

    @classmethod
    async def build(
        cls,
        corpus: KnowledgeCorpus,
        embedding_provider: EmbeddingProvider,
        *,
        persist_path: Path,
        collection_name: str | None = None,
        batch_size: int = 20,
    ) -> "ChromaKnowledgeIndex":
        """Create or safely reuse an index for one exact corpus and model."""

        if batch_size < 1 or batch_size > 100:
            raise ValueError("batch_size must be between 1 and 100")
        persist_path.mkdir(parents=True, exist_ok=True)
        client = await asyncio.to_thread(
            chromadb.PersistentClient,
            path=str(persist_path),
            settings=Settings(anonymized_telemetry=False),
        )
        name = collection_name or _default_collection_name(corpus)
        expected_metadata = _collection_metadata(corpus, embedding_provider)
        collection = await asyncio.to_thread(
            client.get_or_create_collection,
            name=name,
            configuration={"hnsw": {"space": "cosine"}},
            metadata=expected_metadata,
        )
        _validate_collection_metadata(collection.metadata, expected_metadata)

        stored = await asyncio.to_thread(collection.get, include=[])
        stored_ids = set(stored["ids"])
        expected_ids = {chunk.chunk_id for chunk in corpus.chunks}
        if stored_ids == expected_ids:
            return cls(
                collection=collection,
                embedding_provider=embedding_provider,
            )
        if stored_ids:
            raise ValueError(
                "the persisted collection is incomplete; rebuild it in a new local path"
            )

        for start in range(0, len(corpus.chunks), batch_size):
            chunk_batch = corpus.chunks[start : start + batch_size]
            documents = [build_chunk_embedding_text(chunk) for chunk in chunk_batch]
            embedding_result = await embedding_provider.embed_documents(documents)
            if len(embedding_result.vectors) != len(chunk_batch):
                raise ValueError("embedding result count does not match chunk batch")
            if embedding_result.dimensions != embedding_provider.dimensions:
                raise ValueError("embedding result dimensions do not match provider")

            await asyncio.to_thread(
                collection.upsert,
                ids=[chunk.chunk_id for chunk in chunk_batch],
                embeddings=[list(vector) for vector in embedding_result.vectors],
                documents=documents,
                metadatas=[_chunk_metadata(chunk) for chunk in chunk_batch],
            )

        return cls(collection=collection, embedding_provider=embedding_provider)

    async def retrieve(
        self,
        plan: RetrievalPlan,
        *,
        candidate_k_per_query: int | None = None,
        max_total_chunks: int | None = None,
    ) -> RetrievalResult:
        validate_retrieval_overrides(candidate_k_per_query, max_total_chunks)
        ranked_by_query: list[
            tuple[RetrievalQuery, list[tuple[KnowledgeChunk, float]]]
        ] = []
        for query in plan.queries:
            embedding_result = await self._embedding_provider.embed_query(
                query.query_text
            )
            if len(embedding_result.vectors) != 1:
                raise ValueError("query embedding must return exactly one vector")
            if embedding_result.dimensions != self._embedding_provider.dimensions:
                raise ValueError("query embedding dimensions do not match provider")

            query_result = await asyncio.to_thread(
                self._collection.query,
                query_embeddings=[list(embedding_result.vectors[0])],
                n_results=candidate_k_per_query or query.top_k,
                where={"dimension": query.dimension},
                include=["metadatas", "distances"],
            )
            ranked_by_query.append(
                (query, _parse_query_matches(query_result))
            )

        return RetrievalResult(
            chunks=_merge_ranked_matches(
                ranked_by_query,
                max_total_chunks=max_total_chunks or plan.max_total_chunks,
            ),
            embedding_provider=self._embedding_provider.name,
            embedding_model=self._embedding_provider.model,
            embedding_dimensions=self._embedding_provider.dimensions,
        )


def _default_collection_name(corpus: KnowledgeCorpus) -> str:
    version = corpus.source.version.replace(".", "-")
    return f"photo-knowledge-{corpus.source.source_id}-{version}"


def _collection_metadata(
    corpus: KnowledgeCorpus,
    embedding_provider: EmbeddingProvider,
) -> dict[str, str | int]:
    corpus_json = corpus.model_dump_json()
    return {
        "source_id": corpus.source.source_id,
        "source_version": corpus.source.version,
        "corpus_sha256": sha256(corpus_json.encode("utf-8")).hexdigest(),
        "embedding_provider": embedding_provider.name,
        "embedding_model": embedding_provider.model,
        "embedding_dimensions": embedding_provider.dimensions,
    }


def _validate_collection_metadata(
    actual: dict[str, Any] | None,
    expected: dict[str, str | int],
) -> None:
    if actual is None:
        raise ValueError("persisted collection metadata is missing")
    mismatched = [key for key, value in expected.items() if actual.get(key) != value]
    if mismatched:
        raise ValueError(
            "persisted collection does not match: " + ", ".join(mismatched)
        )


def _chunk_metadata(chunk: KnowledgeChunk) -> dict[str, str | int]:
    return {
        "chunk_id": chunk.chunk_id,
        "source_id": chunk.source_id,
        "source_version": chunk.source_version,
        "dimension": chunk.dimension,
        "difficulty": chunk.difficulty,
        "chunk_index": chunk.chunk_index,
        "chunk_json": chunk.model_dump_json(),
    }


def _parse_query_matches(
    query_result: dict[str, Any],
) -> list[tuple[KnowledgeChunk, float]]:
    metadata_batches = query_result.get("metadatas")
    distance_batches = query_result.get("distances")
    if not metadata_batches or not distance_batches:
        return []

    matches: list[tuple[KnowledgeChunk, float]] = []
    for metadata, distance in zip(
        metadata_batches[0],
        distance_batches[0],
        strict=True,
    ):
        if not isinstance(metadata, dict) or "chunk_json" not in metadata:
            raise ValueError("Chroma result is missing chunk metadata")
        chunk = KnowledgeChunk.model_validate_json(metadata["chunk_json"])
        matches.append((chunk, 1.0 - float(distance)))
    return matches
