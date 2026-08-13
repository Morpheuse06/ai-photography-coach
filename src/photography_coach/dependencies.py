"""FastAPI dependency factories for configured application services."""

from functools import lru_cache

from photography_coach.config import get_settings
from photography_coach.errors import ModelUnavailableError
from photography_coach.providers.base import PhotographyProvider
from photography_coach.providers.dashscope import (
    DEFAULT_DASHSCOPE_BASE_URL,
    DashScopePhotographyProvider,
)
from photography_coach.providers.mock import MockPhotographyProvider
from photography_coach.providers.responses_compatible import (
    ResponsesCompatiblePhotographyProvider,
)
from photography_coach.services.analysis import AnalysisService


@lru_cache
def get_analysis_service() -> AnalysisService:
    """Build one analysis service from validated environment settings."""
    settings = get_settings()
    provider: PhotographyProvider

    if settings.model_provider == "mock":
        provider = MockPhotographyProvider()
    elif settings.model_provider == "dashscope":
        if settings.model_api_key is None:
            raise ModelUnavailableError(
                "MODEL_API_KEY is required when MODEL_PROVIDER=dashscope."
            )
        provider = DashScopePhotographyProvider(
            api_key=settings.model_api_key.get_secret_value(),
            model=settings.model_name,
            base_url=settings.model_base_url or DEFAULT_DASHSCOPE_BASE_URL,
            timeout_seconds=settings.model_timeout_seconds,
            max_retries=settings.model_max_retries,
        )
    else:
        if settings.model_api_key is None:
            raise ModelUnavailableError(
                "MODEL_API_KEY is required when MODEL_PROVIDER=responses_compatible."
            )
        provider = ResponsesCompatiblePhotographyProvider(
            api_key=settings.model_api_key.get_secret_value(),
            model=settings.model_name,
            base_url=settings.model_base_url,
            timeout_seconds=settings.model_timeout_seconds,
            max_retries=settings.model_max_retries,
        )

    return AnalysisService(
        provider,
        timeout_seconds=settings.model_timeout_seconds,
    )
