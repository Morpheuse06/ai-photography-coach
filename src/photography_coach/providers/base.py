"""Provider contract shared by real and simulated photography models."""

from dataclasses import dataclass
from typing import Protocol

from photography_coach.schemas.report import PhotographyReport


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """A provider report plus optional token usage returned by its API."""

    report: PhotographyReport
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class PhotographyProvider(Protocol):
    """Small interface that keeps the business service provider-independent."""

    name: str
    model: str

    async def analyze(
        self,
        image_bytes: bytes,
        media_type: str,
        shooting_intent: str | None,
        knowledge_context: str | None = None,
    ) -> ProviderResult:
        """Analyze one validated image and return a structured report."""
        ...
