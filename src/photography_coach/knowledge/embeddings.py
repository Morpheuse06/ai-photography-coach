"""Provider-independent embedding contracts and a deterministic test provider."""

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import blake2b
from math import isfinite, sqrt
from typing import Protocol


EmbeddingVector = tuple[float, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """A batch of same-sized vectors returned by one embedding model."""

    vectors: tuple[EmbeddingVector, ...]
    input_tokens: int | None = None

    def __post_init__(self) -> None:
        if not self.vectors:
            raise ValueError("vectors cannot be empty")

        dimensions = len(self.vectors[0])
        if dimensions == 0:
            raise ValueError("embedding vectors cannot be empty")
        for vector in self.vectors:
            if len(vector) != dimensions:
                raise ValueError("all embedding vectors must use the same dimensions")
            if not all(isfinite(value) for value in vector):
                raise ValueError("embedding vectors must contain only finite numbers")

        if self.input_tokens is not None and self.input_tokens < 0:
            raise ValueError("input_tokens cannot be negative")

    @property
    def dimensions(self) -> int:
        """Return the number of numeric coordinates in each vector."""

        return len(self.vectors[0])


class EmbeddingProvider(Protocol):
    """Small interface implemented by real and simulated embedding services."""

    name: str
    model: str
    dimensions: int

    async def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        """Embed knowledge documents for indexing."""
        ...

    async def embed_query(self, text: str) -> EmbeddingResult:
        """Embed one retrieval query in the same vector space."""
        ...


class DeterministicEmbeddingProvider:
    """Create repeatable local vectors without calling an external API.

    Character bigrams give tests a small amount of lexical similarity while a
    stable cryptographic hash keeps results identical across Python processes.
    These vectors are for development only and are not a replacement for a
    trained semantic embedding model.
    """

    name = "deterministic"
    model = "deterministic-char-bigram-v1"

    def __init__(self, dimensions: int = 64) -> None:
        if dimensions < 8:
            raise ValueError("dimensions must be at least 8")
        self.dimensions = dimensions

    async def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        normalized_texts = _validate_texts(texts)
        return EmbeddingResult(
            vectors=tuple(self._embed_text(text) for text in normalized_texts)
        )

    async def embed_query(self, text: str) -> EmbeddingResult:
        normalized_text = _validate_texts([text])[0]
        return EmbeddingResult(vectors=(self._embed_text(normalized_text),))

    def _embed_text(self, text: str) -> EmbeddingVector:
        compact_text = "".join(text.casefold().split())
        features = _character_features(compact_text)
        vector = [0.0] * self.dimensions

        for feature in features:
            digest = blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], byteorder="big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        magnitude = sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            raise ValueError("text did not produce any embedding features")
        return tuple(value / magnitude for value in vector)


def _validate_texts(texts: Sequence[str]) -> list[str]:
    if not texts:
        raise ValueError("texts cannot be empty")
    if len(texts) > 100:
        raise ValueError("a local embedding batch cannot exceed 100 texts")

    normalized_texts = [text.strip() for text in texts]
    if any(not text for text in normalized_texts):
        raise ValueError("embedding text cannot be blank")
    return normalized_texts


def _character_features(text: str) -> list[str]:
    if len(text) == 1:
        return [text]
    return [text[index : index + 2] for index in range(len(text) - 1)]
