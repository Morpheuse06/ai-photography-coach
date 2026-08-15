"""Public contracts for access control and anonymous report feedback."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)


FeedbackToken = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=32, max_length=512),
]
FeedbackComment = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
ProblemMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=10, max_length=2_000),
]


class AccessMode(StrEnum):
    """Public analysis access policy selected by an administrator."""

    OPEN = "open"
    CODE_REQUIRED = "code_required"
    CLOSED = "closed"


class AnalysisAccess(BaseModel):
    """Non-secret quota information safe to return to the browser."""

    model_config = ConfigDict(extra="forbid")

    mode: AccessMode
    remaining_uses: int | None = Field(default=None, ge=0)


class AnalysisInteraction(BaseModel):
    """Identifiers required for quota display and anonymous feedback."""

    model_config = ConfigDict(extra="forbid")

    analysis_id: UUID
    feedback_token: FeedbackToken = Field(repr=False)
    access: AnalysisAccess


class RatingTarget(StrEnum):
    """One independently rateable section of a photography report."""

    COMPOSITION = "composition"
    LIGHTING = "lighting"
    COLOR = "color"
    SUBJECT_EXPRESSION = "subject_expression"
    VISUAL_STORYTELLING = "visual_storytelling"
    PRIORITY_ACTIONS = "priority_actions"
    SHOOTING_EXERCISE = "shooting_exercise"
    OVERALL = "overall"


class RatingVote(StrEnum):
    UP = "up"
    DOWN = "down"


class RatingReasonCode(StrEnum):
    NOT_GROUNDED = "not_grounded"
    GENERIC_ADVICE = "generic_advice"
    INACCURATE = "inaccurate"
    NOT_ACTIONABLE = "not_actionable"
    CONTRADICTORY = "contradictory"
    INVENTED_DETAIL = "invented_detail"
    HARD_TO_UNDERSTAND = "hard_to_understand"
    OTHER = "other"


class RatingUpsertRequest(BaseModel):
    """Create or replace one anonymous rating for a report section."""

    model_config = ConfigDict(extra="forbid")

    vote: RatingVote
    reason_codes: list[RatingReasonCode] = Field(default_factory=list, max_length=5)
    comment: FeedbackComment | None = None

    @field_validator("reason_codes")
    @classmethod
    def reason_codes_must_be_unique(
        cls,
        reasons: list[RatingReasonCode],
    ) -> list[RatingReasonCode]:
        if len(reasons) != len(set(reasons)):
            raise ValueError("reason_codes must be unique")
        return reasons


class RatingReceipt(BaseModel):
    """Public acknowledgement after a rating is stored."""

    model_config = ConfigDict(extra="forbid")

    rating_id: UUID
    analysis_id: UUID
    target: RatingTarget
    vote: RatingVote
    created_at: datetime
    updated_at: datetime


class ProblemCategory(StrEnum):
    BUG = "bug"
    REPORT_QUALITY = "report_quality"
    PERFORMANCE = "performance"
    USABILITY = "usability"
    PRIVACY = "privacy"
    OTHER = "other"


class ProblemReportStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class ProblemReportCreate(BaseModel):
    """Anonymous issue submitted from the bottom of the public page."""

    model_config = ConfigDict(extra="forbid")

    analysis_id: UUID | None = None
    category: ProblemCategory
    message: ProblemMessage
    include_runtime_metadata: bool = False


class ProblemReportReceipt(BaseModel):
    """Public acknowledgement that does not reveal internal triage details."""

    model_config = ConfigDict(extra="forbid")

    problem_report_id: UUID
    status: ProblemReportStatus
    created_at: datetime
