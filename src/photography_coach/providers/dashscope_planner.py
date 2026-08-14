"""Alibaba Cloud Model Studio adapter for photo retrieval planning."""

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
from photography_coach.knowledge.retrieval import (
    RetrievalPlan,
    require_full_report_dimension_coverage,
)
from photography_coach.providers.dashscope import DEFAULT_DASHSCOPE_BASE_URL
from photography_coach.providers.planner import PlannerResult
from photography_coach.retrieval_prompts import (
    RETRIEVAL_OUTPUT_RETRY_INSTRUCTION,
    RETRIEVAL_SYSTEM_PROMPT,
    build_retrieval_user_prompt,
)


MAX_PLAN_ATTEMPTS = 2


class DashScopeRetrievalPlanner:
    """Create image-grounded retrieval plans with a Qwen vision model."""

    name = "dashscope"

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
        self.model = model
        self._client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    async def create_plan(
        self,
        image_bytes: bytes,
        media_type: str,
        shooting_intent: str | None,
    ) -> PlannerResult:
        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        image_url = f"data:{media_type};base64,{image_base64}"

        input_tokens: int | None = None
        output_tokens: int | None = None
        total_tokens: int | None = None
        last_output_error: Exception | None = None

        for attempt in range(1, MAX_PLAN_ATTEMPTS + 1):
            completion = await self._request_completion(
                image_url,
                shooting_intent,
                is_output_retry=attempt > 1,
            )
            usage = getattr(completion, "usage", None)
            input_tokens = _sum_optional(
                input_tokens,
                getattr(usage, "prompt_tokens", None),
            )
            output_tokens = _sum_optional(
                output_tokens,
                getattr(usage, "completion_tokens", None),
            )
            total_tokens = _sum_optional(
                total_tokens,
                getattr(usage, "total_tokens", None),
            )

            try:
                plan = self._parse_plan(completion, shooting_intent)
            except (
                AttributeError,
                IndexError,
                TypeError,
                ValidationError,
                ValueError,
            ) as exc:
                last_output_error = exc
                continue

            return PlannerResult(
                plan=plan,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                attempts=attempt,
            )

        raise ModelOutputError(
            "The model returned an invalid retrieval plan after one retry."
        ) from last_output_error

    async def _request_completion(
        self,
        image_url: str,
        shooting_intent: str | None,
        *,
        is_output_retry: bool,
    ) -> Any:
        user_text = build_retrieval_user_prompt(shooting_intent)
        if is_output_retry:
            user_text = f"{user_text}\n\n{RETRIEVAL_OUTPUT_RETRY_INSTRUCTION}"

        try:
            return await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._build_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
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
            raise ModelTimeoutError("Retrieval planning timed out.") from exc
        except RateLimitError as exc:
            raise ModelRateLimitError("Retrieval planning was rate limited.") from exc
        except (AuthenticationError, APIConnectionError) as exc:
            raise ModelUnavailableError("Retrieval planning is unavailable.") from exc
        except APIStatusError as exc:
            raise ModelUnavailableError(
                "DashScope retrieval planning returned an API error."
            ) from exc
        except OpenAIError as exc:
            raise ModelUnavailableError("Retrieval planning is unavailable.") from exc

    @staticmethod
    def _parse_plan(completion: Any, shooting_intent: str | None) -> RetrievalPlan:
        content = completion.choices[0].message.content
        if not isinstance(content, str):
            raise ValueError("retrieval plan content must be text")
        model_plan = RetrievalPlan.model_validate_json(content)
        normalized_intent = shooting_intent.strip() if shooting_intent else None
        plan = RetrievalPlan.model_validate(
            {
                **model_plan.model_dump(),
                "user_intent": normalized_intent,
            }
        )
        return require_full_report_dimension_coverage(plan)

    @staticmethod
    def _build_system_prompt() -> str:
        plan_schema = json.dumps(
            RetrievalPlan.model_json_schema(),
            ensure_ascii=False,
        )
        return (
            f"{RETRIEVAL_SYSTEM_PROMPT}\n"
            "Return only one valid JSON object matching this JSON Schema. "
            "Do not wrap it in Markdown code fences.\n"
            f"{plan_schema}"
        )


def _sum_optional(left: int | None, right: int | None) -> int | None:
    values = [value for value in (left, right) if value is not None]
    return sum(values) if values else None
