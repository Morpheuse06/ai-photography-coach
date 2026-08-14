"""Tests for qwen3-rerank HTTP adaptation without external calls."""

import json
import unittest

import httpx

from photography_coach.errors import (
    ModelOutputError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from photography_coach.knowledge.reranking import RerankDocument
from photography_coach.providers.dashscope_reranker import (
    DashScopeRerankingProvider,
)


class FakeHttpClient:
    def __init__(self, *responses_or_errors) -> None:
        self._responses_or_errors = list(responses_or_errors)
        self.calls = []

    async def post(self, url, *, json):
        self.calls.append({"url": url, "json": json})
        outcome = self._responses_or_errors.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(status_code: int, payload) -> httpx.Response:
    request = httpx.Request("POST", "https://workspace.example/reranks")
    if isinstance(payload, str):
        return httpx.Response(
            status_code,
            text=payload,
            request=request,
        )
    return httpx.Response(
        status_code,
        json=payload,
        request=request,
    )


def _documents() -> list[RerankDocument]:
    return [
        RerankDocument(document_id="chunk-a", text="构图与视觉路径知识"),
        RerankDocument(document_id="chunk-b", text="清理画面边缘干扰知识"),
    ]


class DashScopeRerankingProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_composes_request_and_parses_ranked_indexes(self) -> None:
        client = FakeHttpClient(
            _response(
                200,
                {
                    "results": [
                        {"index": 1, "relevance_score": 0.91},
                        {"index": 0, "relevance_score": 0.42},
                    ],
                    "usage": {"total_tokens": 79},
                },
            )
        )
        provider = self._provider(client)

        result = await provider.rerank(
            "怎样清理画面边缘？",
            _documents(),
            top_n=2,
        )

        call = client.calls[0]
        self.assertEqual(
            call["url"],
            "https://workspace.example/compatible-api/v1/reranks",
        )
        self.assertEqual(call["json"]["model"], "qwen3-rerank")
        self.assertEqual(call["json"]["top_n"], 2)
        self.assertIn("photography coaching", call["json"]["instruct"])
        self.assertEqual(
            [item.document_index for item in result.items],
            [1, 0],
        )
        self.assertEqual(result.input_tokens, 79)

    async def test_retries_one_server_error_then_succeeds(self) -> None:
        client = FakeHttpClient(
            _response(503, {"code": "ServiceUnavailable"}),
            _response(
                200,
                {
                    "results": [{"index": 0, "relevance_score": 0.8}],
                    "usage": {"total_tokens": 10},
                },
            ),
        )
        provider = self._provider(client, max_retries=1)

        result = await provider.rerank(
            "构图问题",
            _documents(),
            top_n=1,
        )

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(result.items[0].document_index, 0)

    async def test_maps_timeout_rate_limit_and_server_errors(self) -> None:
        request = httpx.Request(
            "POST",
            "https://workspace.example/compatible-api/v1/reranks",
        )
        cases = [
            (
                httpx.ReadTimeout("timed out", request=request),
                ModelTimeoutError,
            ),
            (_response(429, {"code": "Throttling"}), ModelRateLimitError),
            (_response(503, {"code": "Unavailable"}), ModelUnavailableError),
            (_response(401, {"code": "InvalidApiKey"}), ModelUnavailableError),
        ]

        for outcome, expected_error in cases:
            with self.subTest(expected_error=expected_error.__name__):
                provider = self._provider(FakeHttpClient(outcome))
                with self.assertRaises(expected_error):
                    await provider.rerank(
                        "构图问题",
                        _documents(),
                        top_n=1,
                    )

    async def test_rejects_malformed_provider_results(self) -> None:
        invalid_payloads = [
            {"results": [{"index": 0, "relevance_score": 1.2}]},
            {
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.8},
                ]
            },
            {"results": [{"index": 2, "relevance_score": 0.9}]},
            {"results": "not-a-list"},
        ]
        outcomes = [
            _response(200, payload) for payload in invalid_payloads
        ] + [_response(200, json.dumps("not-an-object"))]

        for outcome in outcomes:
            with self.subTest(body=outcome.text):
                provider = self._provider(FakeHttpClient(outcome))
                with self.assertRaises(ModelOutputError):
                    await provider.rerank(
                        "构图问题",
                        _documents(),
                        top_n=2,
                    )

    @staticmethod
    def _provider(
        client: FakeHttpClient,
        *,
        max_retries: int = 0,
    ) -> DashScopeRerankingProvider:
        return DashScopeRerankingProvider(
            api_key="test-key",
            base_url="https://workspace.example/compatible-api/v1",
            timeout_seconds=5,
            max_retries=max_retries,
            retry_delay_seconds=0,
            client=client,
        )


if __name__ == "__main__":
    unittest.main()
