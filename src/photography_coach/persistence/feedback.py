"""SQL implementation of the anonymous feedback repository port."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.persistence.models import AnalysisRun
from photography_coach.security import hash_secret


async def register_feedback_token(
    session: AsyncSession,
    analysis_id,
    feedback_token: str,
) -> None:
    """Store the feedback capability token hash for one analysis.

    The raw token is returned to the browser exactly once and is never
    persisted or logged.
    """
    run = await session.scalar(
        select(AnalysisRun).where(AnalysisRun.analysis_id == analysis_id)
    )
    if run is None:
        raise FeedbackRegistrationError(
            f"No analysis run found for {analysis_id}."
        )
    run.feedback_token_hash = hash_secret(feedback_token)
    await session.commit()


class FeedbackRegistrationError(RuntimeError):
    """Raised when a feedback token arrives for an unknown analysis."""
