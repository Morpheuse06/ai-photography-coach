"""Alibaba Cloud Model Studio adapter for qwen3-rerank."""

import asyncio
from collections.abc import Sequence
import json
from typing import Any

import httpx

from photography_coach.errors import (
    ModelOutputError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from photography_coach.knowledge.reranking import (
    RerankDocument,
    RerankedItem,
    RerankResult,
    validate_rerank_result,
)


DEFAULT_RERANK_INSTRUCT = (
    "Given a photography coaching question, retrieve reference passages that "
    "provide actionable guidance grounded in visible image evidence."
)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class DashScopeRerankingProvider:
    """Rerank text candidates through the qwen3-rerank HTTP endpoint."""

    name = "dashscope"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = "qwen3-rerank",
        timeout_seconds: float,
        max_retries: int,
        retry_delay_seconds: float = 0.25,
        client: Any | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("rerank base_url cannot be blank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")
        self.model = model
        self._endpoint = f"{base_url.rstrip('/')}/reranks"
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def rerank(
        self,
        query: str,
        documents: Sequence[RerankDocument],
        *,
        top_n: int,
    ) -> RerankResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("rerank query cannot be blank")
        if not documents:
            raise ValueError("rerank documents cannot be empty")
        if top_n < 1 or top_n > len(documents):
            raise ValueError("top_n must be between 1 and the document count")

        response = await self._post_with_retries(
            {
                "model": self.model,
                "query": normalized_query,
                "documents": [document.text for document in documents],
                "top_n": top_n,
                "instruct": DEFAULT_RERANK_INSTRUCT,
            }
        )
        return self._parse_response(
            response,
            document_count=len(documents),
            top_n=top_n,
        )

    async def _post_with_retries(self, payload: dict[str, Any]) -> httpx.Response:
        last_transport_error: httpx.RequestError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(self._endpoint, json=payload)
            except httpx.TimeoutException as exc:
                last_transport_error = exc
                if attempt < self._max_retries:
                    await self._wait_before_retry(attempt)
                    continue
                raise ModelTimeoutError("Text reranking timed out.") from exc
            except httpx.RequestError as exc:
                last_transport_error = exc
                if attempt < self._max_retries:
                    await self._wait_before_retry(attempt)
                    continue
                raise ModelUnavailableError("Text reranking is unavailable.") from exc

            if response.status_code not in RETRYABLE_STATUS_CODES:
                return self._require_success(response)
            if attempt < self._max_retries:
                await self._wait_before_retry(attempt)
                continue
            if response.status_code == 429:
                raise ModelRateLimitError("Text reranking was rate limited.")
            raise ModelUnavailableError("Text reranking returned a server error.")

        raise ModelUnavailableError("Text reranking is unavailable.") from last_transport_error

    async def _wait_before_retry(self, attempt: int) -> None:
        delay = self._retry_delay_seconds * (2**attempt)
        if delay > 0:
            await asyncio.sleep(delay)

    @staticmethod
    def _require_success(response: httpx.Response) -> httpx.Response:
        if response.status_code == 429:
            raise ModelRateLimitError("Text reranking was rate limited.")
        if response.status_code >= 400:
            raise ModelUnavailableError("Text reranking returned an API error.")
        return response

    @staticmethod
    def _parse_response(
        response: httpx.Response,
        *,
        document_count: int,
        top_n: int,
    ) -> RerankResult:
        try:
            payload = response.json()
            raw_results = payload["results"]
            if not isinstance(raw_results, list):
                raise TypeError("results must be a list")
            items = tuple(
                RerankedItem(
                    document_index=_strict_int(item["index"]),
                    relevance_score=_official_score(item["relevance_score"]),
                )
                for item in raw_results
            )
            usage = payload.get("usage") or {}
            input_tokens = _optional_nonnegative_int(usage.get("total_tokens"))
            result = RerankResult(items=items, input_tokens=input_tokens)
            validate_rerank_result(
                result,
                document_count=document_count,
                top_n=top_n,
            )
            return result
        except (
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise ModelOutputError(
                "The reranking model returned invalid results."
            ) from exc


def _strict_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("rerank index must be an integer")
    return value


def _official_score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("relevance score must be numeric")
    score = float(value)
    if score < 0 or score > 1:
        raise ValueError("relevance score must be between 0 and 1")
    return score


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    parsed = _strict_int(value)
    if parsed < 0:
        raise ValueError("token usage cannot be negative")
    return parsed
