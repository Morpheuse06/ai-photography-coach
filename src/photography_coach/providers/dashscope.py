"""Alibaba Cloud Model Studio adapter for Qwen vision models."""

import base64
import json
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
from pydantic import ValidationError

from photography_coach.errors import (
    ModelOutputError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from photography_coach.prompts import SYSTEM_PROMPT, build_user_prompt
from photography_coach.providers.base import ProviderResult
from photography_coach.schemas.report import PhotographyReport


DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class DashScopePhotographyProvider:
    """Analyze photos with a Qwen-VL model through DashScope."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        base_url: str = DEFAULT_DASHSCOPE_BASE_URL,
        client: Any | None = None,
    ) -> None:
        self.name = "dashscope"
        self.model = model
        self._client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    async def analyze(
        self,
        image_bytes: bytes,
        media_type: str,
        shooting_intent: str | None,
        knowledge_context: str | None = None,
    ) -> ProviderResult:
        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        image_url = f"data:{media_type};base64,{image_base64}"

        try:
            completion = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._build_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": build_user_prompt(
                                    shooting_intent,
                                    knowledge_context,
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": image_url},
                            },
                        ],
                    },
                ],
                response_format={"type": "json_object"},
                extra_body={"enable_thinking": False},
            )
        except APITimeoutError as exc:
            raise ModelTimeoutError() from exc
        except RateLimitError as exc:
            raise ModelRateLimitError() from exc
        except (AuthenticationError, APIConnectionError) as exc:
            raise ModelUnavailableError() from exc
        except APIStatusError as exc:
            raise ModelUnavailableError("DashScope returned an API error.") from exc
        except OpenAIError as exc:
            raise ModelUnavailableError() from exc

        try:
            content = completion.choices[0].message.content
            if not isinstance(content, str):
                raise ModelOutputError()
            report = PhotographyReport.model_validate_json(content)
        except (AttributeError, IndexError, TypeError, ValidationError, ValueError) as exc:
            raise ModelOutputError() from exc

        usage = getattr(completion, "usage", None)
        return ProviderResult(
            report=report,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )

    @staticmethod
    def _build_system_prompt() -> str:
        report_schema = json.dumps(
            PhotographyReport.model_json_schema(),
            ensure_ascii=False,
        )
        return (
            f"{SYSTEM_PROMPT}\n"
            "Return only one valid JSON object matching this JSON Schema. "
            "Do not wrap it in Markdown code fences.\n"
            f"{report_schema}"
        )
