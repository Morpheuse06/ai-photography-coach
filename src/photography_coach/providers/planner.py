"""Provider contract for the image-grounded retrieval-planning model."""

from dataclasses import dataclass
from typing import Protocol

from photography_coach.knowledge.retrieval import RetrievalPlan


@dataclass(frozen=True, slots=True)
class PlannerResult:
    """A retrieval plan plus optional usage returned by its model provider."""

    plan: RetrievalPlan
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    attempts: int = 1


class RetrievalPlanner(Protocol):
    """Small interface that keeps retrieval planning provider-independent."""

    name: str
    model: str

    async def create_plan(
        self,
        image_bytes: bytes,
        media_type: str,
        shooting_intent: str | None,
    ) -> PlannerResult:
        """Observe one validated image and return bounded retrieval queries."""
        ...
