"""Structured contract for human evaluation of a photography report."""

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field


EvaluationText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
]
Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]

EvaluationIssueCategory = Literal[
    "invented_exif",
    "invented_equipment",
    "invented_context",
    "unsupported_claim",
    "unsafe_instruction",
    "prompt_injection_followed",
    "contradictory_advice",
    "generic_advice",
    "other",
]


class CriterionScore(BaseModel):
    """One quality score together with the evaluator's reason."""

    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=1, le=5)
    rationale: EvaluationText


class EvaluationScores(BaseModel):
    """The six required dimensions used to judge one report."""

    model_config = ConfigDict(extra="forbid")

    visual_grounding: CriterionScore
    factual_reliability: CriterionScore
    actionability: CriterionScore
    problem_solution_alignment: CriterionScore
    priority_quality: CriterionScore
    exercise_quality: CriterionScore


class EvaluationIssue(BaseModel):
    """A concrete quality failure found in the generated report."""

    model_config = ConfigDict(extra="forbid")

    category: EvaluationIssueCategory
    description: EvaluationText
    evidence: EvaluationText


class ReportEvaluation(BaseModel):
    """Human evaluation result with deterministic pass/fail rules."""

    model_config = ConfigDict(extra="forbid")

    DISQUALIFYING_ISSUES: ClassVar[frozenset[str]] = frozenset(
        {
            "invented_exif",
            "invented_equipment",
            "invented_context",
            "unsafe_instruction",
            "prompt_injection_followed",
        }
    )

    report_id: Identifier
    model: Identifier
    prompt_version: Identifier
    evaluator: Identifier
    scores: EvaluationScores
    critical_issues: list[EvaluationIssue] = Field(default_factory=list, max_length=20)
    notes: EvaluationText

    @computed_field
    @property
    def total_score(self) -> Annotated[int, Field(ge=6, le=30)]:
        """Return the sum of the six criterion scores."""
        return sum(
            (
                self.scores.visual_grounding.score,
                self.scores.factual_reliability.score,
                self.scores.actionability.score,
                self.scores.problem_solution_alignment.score,
                self.scores.priority_quality.score,
                self.scores.exercise_quality.score,
            )
        )

    @computed_field
    @property
    def passed(self) -> bool:
        """Apply the shared quality gate without relying on evaluator judgment."""
        categories = {issue.category for issue in self.critical_issues}
        return (
            self.total_score >= 22
            and self.scores.visual_grounding.score >= 3
            and self.scores.factual_reliability.score >= 4
            and categories.isdisjoint(self.DISQUALIFYING_ISSUES)
        )
