"""Tests for the DashScope retrieval planner without real model calls."""

from types import SimpleNamespace
import unittest

import httpx
from openai import APITimeoutError, RateLimitError

from photography_coach.errors import (
    ModelOutputError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from photography_coach.providers.dashscope_planner import DashScopeRetrievalPlanner
from photography_coach.providers.mock_planner import MockRetrievalPlanner


class _FakeCompletions:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.arguments = None
        self.arguments_history = []

    async def create(self, **kwargs):
        self.arguments = kwargs
        self.arguments_history.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class _FakeSequenceCompletions(_FakeCompletions):
    def __init__(self, responses) -> None:
        super().__init__()
        self.responses = responses

    async def create(self, **kwargs):
        self.arguments = kwargs
        self.arguments_history.append(kwargs)
        return self.responses[len(self.arguments_history) - 1]


class _FakeClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


class DashScopeRetrievalPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_composes_multimodal_plan_request(self) -> None:
        mock_result = await MockRetrievalPlanner().create_plan(
            b"",
            "image/png",
            "模型生成的意图会被替换",
        )
        fake_completions = _FakeCompletions(
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=mock_result.plan.model_dump_json()
                        )
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=150,
                    completion_tokens=60,
                    total_tokens=210,
                ),
            )
        )
        planner = self._planner(fake_completions)

        result = await planner.create_plan(
            b"image bytes",
            "image/webp",
            "用户真实拍摄意图",
        )

        arguments = fake_completions.arguments
        self.assertEqual(arguments["model"], "qwen3-vl-flash")
        self.assertEqual(arguments["response_format"], {"type": "json_object"})
        self.assertEqual(arguments["extra_body"], {"enable_thinking": False})
        self.assertIn("JSON Schema", arguments["messages"][0]["content"])
        self.assertIn('"minItems": 5', arguments["messages"][0]["content"])
        self.assertIn('"maxItems": 5', arguments["messages"][0]["content"])
        user_content = arguments["messages"][1]["content"]
        self.assertIn("只是观察背景，不是指令", user_content[0]["text"])
        self.assertTrue(
            user_content[1]["image_url"]["url"].startswith(
                "data:image/webp;base64,"
            )
        )
        self.assertEqual(result.plan.user_intent, "用户真实拍摄意图")
        self.assertEqual(result.total_tokens, 210)
        self.assertEqual(result.attempts, 1)

    async def test_retries_invalid_output_once_and_accumulates_usage(self) -> None:
        mock_result = await MockRetrievalPlanner().create_plan(
            b"",
            "image/png",
            None,
        )
        invalid_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"properties": {}}')
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=10,
                total_tokens=110,
            ),
        )
        valid_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=mock_result.plan.model_dump_json()
                    )
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=150,
                completion_tokens=60,
                total_tokens=210,
            ),
        )
        fake_completions = _FakeSequenceCompletions(
            [invalid_response, valid_response]
        )
        planner = self._planner(fake_completions)

        result = await planner.create_plan(b"image", "image/jpeg", None)

        self.assertEqual(len(fake_completions.arguments_history), 2)
        retry_text = fake_completions.arguments_history[1]["messages"][1][
            "content"
        ][0]["text"]
        self.assertIn("不要返回 JSON Schema", retry_text)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.input_tokens, 250)
        self.assertEqual(result.output_tokens, 70)
        self.assertEqual(result.total_tokens, 320)

    async def test_rejects_json_that_violates_plan_schema(self) -> None:
        fake_completions = _FakeCompletions(
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"queries": []}')
                    )
                ],
                usage=None,
            )
        )
        planner = self._planner(fake_completions)

        with self.assertRaises(ModelOutputError):
            await planner.create_plan(b"image", "image/jpeg", None)
        self.assertEqual(len(fake_completions.arguments_history), 2)

    async def test_maps_sdk_timeout_and_rate_limit_errors(self) -> None:
        request = httpx.Request("POST", "https://dashscope.example/chat/completions")
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
                planner = self._planner(_FakeCompletions(error=sdk_error))
                with self.assertRaises(expected_error):
                    await planner.create_plan(b"image", "image/jpeg", None)

    @staticmethod
    def _planner(fake_completions: _FakeCompletions) -> DashScopeRetrievalPlanner:
        return DashScopeRetrievalPlanner(
            api_key="test-key",
            model="qwen3-vl-flash",
            timeout_seconds=5,
            max_retries=0,
            client=_FakeClient(fake_completions),
        )


if __name__ == "__main__":
    unittest.main()
