"""Business orchestration for one photography analysis request."""

import asyncio
import logging
from time import perf_counter

from photography_coach.errors import ModelTimeoutError
from photography_coach.image_validation import ValidatedImage
from photography_coach.prompts import PROMPT_VERSION
from photography_coach.providers.base import PhotographyProvider
from photography_coach.schemas.analysis import (
    AnalysisMetadata,
    AnalysisResponse,
    ImageMetadata,
    ModelUsage,
)


logger = logging.getLogger(__name__)


class AnalysisService:
    """Apply a total timeout and build provider-independent response metadata."""

    def __init__(
        self,
        provider: PhotographyProvider,
        *,
        timeout_seconds: float,
    ) -> None:
        self._provider = provider
        self._timeout_seconds = timeout_seconds

    async def analyze(
        self,
        image_bytes: bytes,
        image: ValidatedImage,
        shooting_intent: str | None,
    ) -> AnalysisResponse:
        started_at = perf_counter()
        try:
            result = await asyncio.wait_for(
                self._provider.analyze(
                    image_bytes,
                    image.media_type,
                    shooting_intent,
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            raise ModelTimeoutError() from exc

        latency_ms = round((perf_counter() - started_at) * 1_000)
        response = AnalysisResponse(
            report=result.report,
            metadata=AnalysisMetadata(
                provider=self._provider.name,
                model=self._provider.model,
                prompt_version=PROMPT_VERSION,
                latency_ms=latency_ms,
                image=ImageMetadata(
                    media_type=image.media_type,
                    width=image.width,
                    height=image.height,
                    size_bytes=image.size_bytes,
                ),
                usage=ModelUsage(
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    total_tokens=result.total_tokens,
                ),
            ),
        )
        logger.info(
            "analysis_completed",
            extra={
                "event_data": {
                    "provider": response.metadata.provider,
                    "model": response.metadata.model,
                    "prompt_version": response.metadata.prompt_version,
                    "latency_ms": response.metadata.latency_ms,
                    "image_media_type": image.media_type,
                    "image_width": image.width,
                    "image_height": image.height,
                    "image_size_bytes": image.size_bytes,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                }
            },
        )
        return response
