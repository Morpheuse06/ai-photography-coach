"""Photography model provider implementations."""

from photography_coach.providers.base import PhotographyProvider, ProviderResult
from photography_coach.providers.dashscope import DashScopePhotographyProvider
from photography_coach.providers.mock import MockPhotographyProvider
from photography_coach.providers.responses_compatible import (
    ResponsesCompatiblePhotographyProvider,
)

__all__ = [
    "DashScopePhotographyProvider",
    "MockPhotographyProvider",
    "PhotographyProvider",
    "ProviderResult",
    "ResponsesCompatiblePhotographyProvider",
]
