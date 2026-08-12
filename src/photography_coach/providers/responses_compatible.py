"""Responses-compatible API adapter using the official OpenAI Python transport."""

import base64
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


class ResponsesCompatiblePhotographyProvider:
    """Analyze images through a configurable Responses-compatible endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.name = "responses_compatible"
        self.model = model
        if client is not None:
            self._client = client
        else:
            client_options: dict[str, Any] = {
                "api_key": api_key,
                "timeout": timeout_seconds,
                "max_retries": max_retries,
            }
            if base_url:
                client_options["base_url"] = base_url
            self._client = AsyncOpenAI(**client_options)

    async def analyze(
        self,
        image_bytes: bytes,
        media_type: str,
        shooting_intent: str | None,
    ) -> ProviderResult:
        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        image_url = f"data:{media_type};base64,{image_base64}"

        try:
            response = await self._client.responses.parse(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": build_user_prompt(shooting_intent),
                            },
                            {
                                "type": "input_image",
                                "image_url": image_url,
                                "detail": "high",
                            },
                        ],
                    }
                ],
                text_format=PhotographyReport,
                reasoning={"effort": "low"},
                store=False,
            )
        except APITimeoutError as exc:
            raise ModelTimeoutError() from exc
        except RateLimitError as exc:
            raise ModelRateLimitError() from exc
        except (AuthenticationError, APIConnectionError) as exc:
            raise ModelUnavailableError() from exc
        except APIStatusError as exc:
            raise ModelUnavailableError("The model provider returned an API error.") from exc
        except ValidationError as exc:
            raise ModelOutputError() from exc
        except OpenAIError as exc:
            raise ModelUnavailableError() from exc

        report = response.output_parsed
        if not isinstance(report, PhotographyReport):
            raise ModelOutputError()

        usage = getattr(response, "usage", None)
        return ProviderResult(
            report=report,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )
