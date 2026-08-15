"""Public anonymous feedback endpoints for the photography coach."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.dependencies import get_db_session
from photography_coach.errors import (
    FeedbackForbiddenError,
    FeedbackRateLimitedError,
)
from photography_coach.persistence.feedback import SqlFeedbackRepository
from photography_coach.schemas.interaction import (
    ProblemReportCreate,
    ProblemReportReceipt,
    RatingReceipt,
    RatingTarget,
    RatingUpsertRequest,
)
from photography_coach.security import hash_secret

feedback_router = APIRouter(prefix="/api/v2", tags=["feedback"])

RATINGS_PER_TOKEN_HOUR = 60
PROBLEM_REPORTS_PER_SOURCE_HOUR = 10


async def get_feedback_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SqlFeedbackRepository:
    """Build the feedback store for one request-scoped session."""
    return SqlFeedbackRepository(session)


@feedback_router.put(
    "/analyses/{analysis_id}/ratings/{target}",
    response_model=RatingReceipt,
)
async def upsert_rating(
    analysis_id: UUID,
    target: RatingTarget,
    request: Request,
    body: RatingUpsertRequest,
    authorization: Annotated[str | None, Header()] = None,
    repository: Annotated[
        SqlFeedbackRepository, Depends(get_feedback_repository)
    ] = None,
) -> RatingReceipt:
    """Create or replace one anonymous rating for a report section."""
    token = _require_feedback_token(authorization)
    _enforce_feedback_rate_limit(
        request, f"rating:{hash_secret(token)}", RATINGS_PER_TOKEN_HOUR
    )
    return await repository.upsert_rating(
        analysis_id=analysis_id,
        feedback_token=token,
        target=target,
        rating=body,
    )


@feedback_router.delete(
    "/analyses/{analysis_id}/ratings/{target}",
    status_code=204,
)
async def delete_rating(
    analysis_id: UUID,
    target: RatingTarget,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    repository: Annotated[
        SqlFeedbackRepository, Depends(get_feedback_repository)
    ] = None,
) -> None:
    """Delete one rating; always 204 to avoid revealing internal state."""
    token = _require_feedback_token(authorization)
    _enforce_feedback_rate_limit(
        request, f"rating:{hash_secret(token)}", RATINGS_PER_TOKEN_HOUR
    )
    await repository.delete_rating(
        analysis_id=analysis_id,
        feedback_token=token,
        target=target,
    )


@feedback_router.post(
    "/problem-reports",
    response_model=ProblemReportReceipt,
    status_code=202,
)
async def create_problem_report(
    body: ProblemReportCreate,
    request: Request,
    repository: Annotated[
        SqlFeedbackRepository, Depends(get_feedback_repository)
    ] = None,
) -> ProblemReportReceipt:
    """Store one anonymous issue from the bottom of the public page."""
    source = request.client.host if request.client else "unknown"
    _enforce_feedback_rate_limit(
        request,
        f"problem:{source}",
        PROBLEM_REPORTS_PER_SOURCE_HOUR,
    )
    return await repository.create_problem_report(body)


def _require_feedback_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise FeedbackForbiddenError()
    token = authorization[len("Bearer ") :].strip()
    if not token:
        raise FeedbackForbiddenError()
    return token


def _enforce_feedback_rate_limit(
    request: Request,
    key: str,
    limit: int,
) -> None:
    limiter = getattr(request.app.state, "source_rate_limiter", None)
    if limiter is not None and not limiter.allow(key, limit=limit):
        raise FeedbackRateLimitedError()
