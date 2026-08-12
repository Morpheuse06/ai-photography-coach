"""Structured contract for an AI-generated photography coaching report."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]
DetailedText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
]


class DimensionAssessment(BaseModel):
    """Coaching feedback for one photographic dimension."""

    model_config = ConfigDict(extra="forbid")

    rating: int = Field(ge=1, le=5, description="A rating from 1 to 5.")
    summary: ShortText = Field(description="A concise judgment of this dimension.")
    visual_evidence: list[DetailedText] = Field(
        min_length=1,
        max_length=5,
        description="Visible details in the image that support the judgment.",
    )
    strengths: list[DetailedText] = Field(min_length=1, max_length=5)
    main_issue: DetailedText
    improvement_suggestions: list[DetailedText] = Field(min_length=1, max_length=5)


class PhotographyDimensions(BaseModel):
    """The five required dimensions of a photography coaching report."""

    model_config = ConfigDict(extra="forbid")

    composition: DimensionAssessment
    lighting: DimensionAssessment
    color: DimensionAssessment
    subject_expression: DimensionAssessment
    visual_storytelling: DimensionAssessment


class PriorityAction(BaseModel):
    """One improvement action, where priority 1 is the most important."""

    model_config = ConfigDict(extra="forbid")

    priority: Literal[1, 2, 3]
    action: DetailedText
    reason: ShortText


class ShootingExercise(BaseModel):
    """A focused exercise for the user's next photo session."""

    model_config = ConfigDict(extra="forbid")

    title: ShortText
    objective: DetailedText
    steps: list[DetailedText] = Field(min_length=1, max_length=5)
    success_criteria: list[DetailedText] = Field(min_length=1, max_length=5)


class PhotographyReport(BaseModel):
    """Complete response returned after a single photo is analyzed."""

    model_config = ConfigDict(extra="forbid")

    dimensions: PhotographyDimensions
    priority_actions: list[PriorityAction] = Field(min_length=3, max_length=3)
    next_shooting_exercise: ShootingExercise

    @field_validator("priority_actions")
    @classmethod
    def priorities_must_be_ordered(cls, actions: list[PriorityAction]) -> list[PriorityAction]:
        """Keep the API response deterministic for clients that render it in order."""
        priorities = [action.priority for action in actions]
        if priorities != [1, 2, 3]:
            raise ValueError("priority_actions must be ordered with priorities 1, 2, and 3")
        return actions
