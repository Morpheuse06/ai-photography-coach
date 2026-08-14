"""OpenAI-compatible adapter for Alibaba Cloud text embedding models."""

from collections.abc import Sequence
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)

from photography_coach.errors import (
    ModelOutputError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from photography_coach.knowledge.embeddings import EmbeddingResult
from photography_coach.providers.dashscope import DEFAULT_DASHSCOPE_BASE_URL


class DashScopeEmbeddingProvider:
    """Create dense text vectors through a configurable DashScope endpoint."""

    name = "dashscope"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "qwen3.7-text-embedding",
        dimensions: int = 1_024,
        max_batch_size: int = 20,
        timeout_seconds: float,
        max_retries: int,
        base_url: str = DEFAULT_DASHSCOPE_BASE_URL,
        client: Any | None = None,
    ) -> None:
        if dimensions < 1:
            raise ValueError("dimensions must be positive")
        if max_batch_size < 1:
            raise ValueError("max_batch_size must be positive")
        self.model = model
        self.dimensions = dimensions
        self.max_batch_size = max_batch_size
        self._client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    async def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        return await self._embed(texts)

    async def embed_query(self, text: str) -> EmbeddingResult:
        return await self._embed([text])

    async def _embed(self, texts: Sequence[str]) -> EmbeddingResult:
        normalized_texts = [text.strip() for text in texts]
        if not normalized_texts:
            raise ValueError("texts cannot be empty")
        if len(normalized_texts) > self.max_batch_size:
            raise ValueError(
                f"embedding batch cannot exceed {self.max_batch_size} texts"
            )
        if any(not text for text in normalized_texts):
            raise ValueError("embedding text cannot be blank")

        try:
            response = await self._client.embeddings.create(
                model=self.model,
                input=normalized_texts,
                dimensions=self.dimensions,
            )
        except APITimeoutError as exc:
            raise ModelTimeoutError("Text embedding timed out.") from exc
        except RateLimitError as exc:
            raise ModelRateLimitError("Text embedding was rate limited.") from exc
        except (AuthenticationError, APIConnectionError) as exc:
            raise ModelUnavailableError("Text embedding is unavailable.") from exc
        except APIStatusError as exc:
            raise ModelUnavailableError(
                "DashScope embedding returned an API error."
            ) from exc
        except OpenAIError as exc:
            raise ModelUnavailableError("Text embedding is unavailable.") from exc

        try:
            ordered_data = sorted(response.data, key=lambda item: item.index)
            vectors = tuple(
                tuple(float(value) for value in item.embedding)
                for item in ordered_data
            )
            usage = getattr(response, "usage", None)
            result = EmbeddingResult(
                vectors=vectors,
                input_tokens=getattr(usage, "prompt_tokens", None),
            )
            if len(result.vectors) != len(normalized_texts):
                raise ValueError("embedding response count does not match input count")
            if result.dimensions != self.dimensions:
                raise ValueError("embedding response dimensions do not match configuration")
            return result
        except (AttributeError, TypeError, ValueError) as exc:
            raise ModelOutputError("The embedding model returned invalid vectors.") from exc
