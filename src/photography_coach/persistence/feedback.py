"""SQL implementation of the anonymous feedback repository port.

Feedback tokens are hashed immediately on entry and compared in constant
time; the raw token is never persisted. Ratings are keyed by
``(analysis_id, target)`` so one token can hold only one current rating per
target, and problem report text is stored as untrusted data.
"""

from datetime import UTC, datetime
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.errors import (
    AnalysisNotFoundError,
    FeedbackForbiddenError,
)
from photography_coach.persistence.json_text import dumps
from photography_coach.persistence.models import (
    AnalysisRun,
    DimensionRating,
    ProblemReport,
    as_aware_utc,
    utc_now,
)
from photography_coach.ports.control_plane import (
    FeedbackRepository,
    RuntimeMetadata,
)
from photography_coach.schemas.interaction import (
    ProblemReportCreate,
    ProblemReportReceipt,
    RatingReceipt,
    RatingTarget,
    RatingUpsertRequest,
)
from photography_coach.security import constant_time_equals, hash_secret


logger = logging.getLogger(__name__)


class SqlFeedbackRepository:
    """Validate feedback tokens and persist anonymous public feedback."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register_feedback_token(
        self,
        *,
        analysis_id: UUID,
        feedback_token: str,
    ) -> None:
        """Store the feedback capability token hash for one analysis.

        The raw token is returned to the browser exactly once and is never
        persisted or logged.
        """
        run = await self._session.get(AnalysisRun, analysis_id)
        if run is None:
            raise FeedbackRegistrationError(
                f"No analysis run found for {analysis_id}."
            )
        run.feedback_token_hash = hash_secret(feedback_token)
        await self._session.commit()

    async def upsert_rating(
        self,
        *,
        analysis_id: UUID,
        feedback_token: str,
        target: RatingTarget,
        rating: RatingUpsertRequest,
    ) -> RatingReceipt:
        """Create or replace the token's single rating for one target."""
        run = await self._require_authorized_run(analysis_id, feedback_token)

        row = await self._session.scalar(
            select(DimensionRating).where(
                DimensionRating.analysis_id == analysis_id,
                DimensionRating.target == target.value,
            )
        )
        now = utc_now()
        if row is None:
            row = DimensionRating(
                analysis_id=analysis_id,
                target=target.value,
                vote=rating.vote.value,
                reason_codes_json=dumps(
                    [code.value for code in rating.reason_codes]
                ),
                comment=rating.comment,
            )
            self._session.add(row)
        else:
            row.vote = rating.vote.value
            row.reason_codes_json = dumps(
                [code.value for code in rating.reason_codes]
            )
            row.comment = rating.comment
            row.updated_at = now
        await self._session.commit()
        logger.info(
            "rating_upserted",
            extra={
                "event_data": {
                    "analysis_id": str(analysis_id),
                    "target": target.value,
                    "vote": rating.vote.value,
                }
            },
        )
        return RatingReceipt(
            rating_id=row.id,
            analysis_id=analysis_id,
            target=target,
            vote=rating.vote,
            created_at=as_aware_utc(row.created_at),
            updated_at=as_aware_utc(row.updated_at),
        )

    async def delete_rating(
        self,
        *,
        analysis_id: UUID,
        feedback_token: str,
        target: RatingTarget,
    ) -> bool:
        """Delete a rating and report whether a stored rating existed."""
        await self._require_authorized_run(analysis_id, feedback_token)

        row = await self._session.scalar(
            select(DimensionRating).where(
                DimensionRating.analysis_id == analysis_id,
                DimensionRating.target == target.value,
            )
        )
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.commit()
        logger.info(
            "rating_deleted",
            extra={
                "event_data": {
                    "analysis_id": str(analysis_id),
                    "target": target.value,
                }
            },
        )
        return True

    async def create_problem_report(
        self,
        report: ProblemReportCreate,
        *,
        runtime_metadata: RuntimeMetadata | None = None,
    ) -> ProblemReportReceipt:
        """Store a public issue with only approved runtime metadata."""
        if report.analysis_id is not None:
            run = await self._session.get(AnalysisRun, report.analysis_id)
            if run is None:
                raise AnalysisNotFoundError()
            if report.include_runtime_metadata:
                runtime_metadata = runtime_metadata_for(run)

        row = ProblemReport(
            analysis_id=report.analysis_id,
            category=report.category.value,
            message=report.message,
            status="new",
            priority="normal",
            runtime_metadata_json=(
                dumps(runtime_metadata) if runtime_metadata else None
            ),
        )
        self._session.add(row)
        await self._session.commit()
        logger.info(
            "problem_report_created",
            extra={
                "event_data": {
                    "problem_report_id": str(row.id),
                    "category": report.category.value,
                }
            },
        )
        return ProblemReportReceipt(
            problem_report_id=row.id,
            status="new",
            created_at=as_aware_utc(row.created_at),
        )

    async def _require_authorized_run(
        self,
        analysis_id: UUID,
        feedback_token: str,
    ) -> AnalysisRun:
        run = await self._session.get(AnalysisRun, analysis_id)
        if run is None:
            raise AnalysisNotFoundError()
        if run.feedback_token_hash is None or not constant_time_equals(
            run.feedback_token_hash,
            hash_secret(feedback_token),
        ):
            raise FeedbackForbiddenError()
        return run


class FeedbackRegistrationError(RuntimeError):
    """Raised when a feedback token arrives for an unknown analysis."""


async def register_feedback_token(
    session: AsyncSession,
    analysis_id: UUID,
    feedback_token: str,
) -> None:
    """Convenience wrapper shared by the control-plane analysis service."""
    await SqlFeedbackRepository(session).register_feedback_token(
        analysis_id=analysis_id,
        feedback_token=feedback_token,
    )


def runtime_metadata_for(run: AnalysisRun) -> RuntimeMetadata:
    """Server-side non-secret metadata approved for problem reports.

    Client-supplied model, token, IP, or diagnostic fields are never trusted;
    only these stored run fields are attached.
    """
    values: RuntimeMetadata = {
        "api_version": run.api_version,
        "status": run.status,
        "provider": run.provider,
        "model": run.model,
        "prompt_version": run.prompt_version,
        "planner_prompt_version": run.planner_prompt_version,
        "knowledge_source_id": run.knowledge_source_id,
        "knowledge_source_version": run.knowledge_source_version,
        "embedding_model": run.embedding_model,
        "reranker_model": run.reranker_model,
        "latency_ms": run.latency_ms,
        "total_tokens": run.total_tokens,
        "error_code": run.error_code,
        "completed_at": (
            as_aware_utc(run.completed_at).isoformat()
            if run.completed_at
            else None
        ),
    }
    return {
        key: value for key, value in values.items() if value is not None
    }
