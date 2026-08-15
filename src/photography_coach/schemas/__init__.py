"""Request and response contracts used by the application."""

from photography_coach.schemas.analysis import AnalysisResponse, ErrorResponse
from photography_coach.schemas.interaction import (
    AnalysisInteraction,
    ProblemReportCreate,
    RatingUpsertRequest,
)
from photography_coach.schemas.report import PhotographyReport

__all__ = [
    "AnalysisInteraction",
    "AnalysisResponse",
    "ErrorResponse",
    "PhotographyReport",
    "ProblemReportCreate",
    "RatingUpsertRequest",
]
