"""Tests for DashScope embeddings without external API calls."""

from types import SimpleNamespace
import unittest

import httpx
from openai import APITimeoutError, RateLimitError

from photography_coach.errors import (
    ModelOutputError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from photography_coach.providers.dashscope_embedding import (
    DashScopeEmbeddingProvider,
)


class _FakeEmbeddings:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.arguments = None

    async def create(self, **kwargs):
        self.arguments = kwargs
        if self.error:
            raise self.error
        return self.response


class _FakeClient:
    def __init__(self, embeddings: _FakeEmbeddings) -> None:
        self.embeddings = embeddings


def _response(*vectors) -> SimpleNamespace:
    data = [
        SimpleNamespace(index=index, embedding=vector)
        for index, vector in reversed(list(enumerate(vectors)))
    ]
    return SimpleNamespace(
        data=data,
        usage=SimpleNamespace(prompt_tokens=42, total_tokens=42),
    )


class DashScopeEmbeddingProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_composes_embedding_request_and_restores_input_order(self) -> None:
        fake_embeddings = _FakeEmbeddings(
            _response([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
        )
        provider = self._provider(fake_embeddings, dimensions=3)

        result = await provider.embed_documents(["第一段", "第二段"])

        self.assertEqual(
            fake_embeddings.arguments,
            {
                "model": "qwen3.7-text-embedding",
                "input": ["第一段", "第二段"],
                "dimensions": 3,
            },
        )
        self.assertEqual(result.vectors[0], (1.0, 0.0, 0.0))
        self.assertEqual(result.vectors[1], (0.0, 1.0, 0.0))
        self.assertEqual(result.input_tokens, 42)

    async def test_embeds_one_query_in_the_same_configured_space(self) -> None:
        fake_embeddings = _FakeEmbeddings(_response([0.1, 0.2, 0.3]))
        provider = self._provider(fake_embeddings, dimensions=3)

        result = await provider.embed_query("如何处理逆光人物？")

        self.assertEqual(fake_embeddings.arguments["input"], ["如何处理逆光人物？"])
        self.assertEqual(result.dimensions, 3)

    async def test_rejects_wrong_response_count_or_dimensions(self) -> None:
        cases = [
            _response([1.0, 0.0, 0.0]),
            _response([1.0, 0.0], [0.0, 1.0]),
        ]

        for response in cases:
            with self.subTest(response=response):
                provider = self._provider(_FakeEmbeddings(response), dimensions=3)
                with self.assertRaises(ModelOutputError):
                    await provider.embed_documents(["第一段", "第二段"])

    async def test_enforces_configured_batch_limit(self) -> None:
        provider = self._provider(_FakeEmbeddings(), max_batch_size=2)

        with self.assertRaisesRegex(ValueError, "cannot exceed 2"):
            await provider.embed_documents(["一", "二", "三"])

    async def test_maps_sdk_timeout_and_rate_limit_errors(self) -> None:
        request = httpx.Request("POST", "https://dashscope.example/embeddings")
        response = httpx.Response(429, request=request)
        cases = [
            (APITimeoutError(request=request), ModelTimeoutError),
            (
                RateLimitError("rate limited", response=response, body=None),
                ModelRateLimitError,
            ),
        ]

        for sdk_error, expected_error in cases:
            with self.subTest(expected_error=expected_error.__name__):
                provider = self._provider(_FakeEmbeddings(error=sdk_error))
                with self.assertRaises(expected_error):
                    await provider.embed_query("测试查询")

    @staticmethod
    def _provider(
        fake_embeddings: _FakeEmbeddings,
        *,
        dimensions: int = 3,
        max_batch_size: int = 20,
    ) -> DashScopeEmbeddingProvider:
        return DashScopeEmbeddingProvider(
            api_key="test-key",
            model="qwen3.7-text-embedding",
            dimensions=dimensions,
            max_batch_size=max_batch_size,
            timeout_seconds=5,
            max_retries=0,
            client=_FakeClient(fake_embeddings),
        )


if __name__ == "__main__":
    unittest.main()
