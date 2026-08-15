"""SQL implementation of the analysis run recorder port.

Rows only ever transition from ``running`` to one terminal state; repeated
success or failure calls after a terminal state are no-ops. Original photo
bytes never enter this module.
"""

from datetime import datetime, timedelta
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.persistence.json_text import dumps
from photography_coach.persistence.models import AnalysisRun
from photography_coach.ports.control_plane import (
    AnalysisRunFailure,
    AnalysisRunStart,
)
from photography_coach.schemas.analysis import AnalysisMetadata
from photography_coach.schemas.report import PhotographyReport

logger = logging.getLogger(__name__)

REPORT_RETENTION_DAYS = 30


class SqlAnalysisRecorder:
    """Persist analysis lifecycle data without receiving original photo bytes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start(self, run: AnalysisRunStart) -> None:
        """Create the running record before calling external model services.

        Replays of an idempotent operation may reach this method for an
        analysis that already exists; those are logged and skipped so the
        retried attempt joins the same record.
        """
        existing = await self._session.get(AnalysisRun, run.analysis_id)
        if existing is not None:
            logger.warning(
                "analysis_run_start_replayed",
                extra={"event_data": {"analysis_id": str(run.analysis_id)}},
            )
            return
        self._session.add(
            AnalysisRun(
                analysis_id=run.analysis_id,
                api_version=run.api_version,
                status="running",
                started_at=_naive(run.started_at),
                media_type=run.image.media_type,
                width=run.image.width,
                height=run.image.height,
                size_bytes=run.image.size_bytes,
                shooting_intent=run.shooting_intent,
                reservation_id=run.reservation_id,
            )
        )
        try:
            await self._session.commit()
        except IntegrityError:
            # A concurrent replay created the record first; join it.
            await self._session.rollback()
            logger.warning(
                "analysis_run_start_raced",
                extra={"event_data": {"analysis_id": str(run.analysis_id)}},
            )
        logger.info(
            "analysis_run_started",
            extra={"event_data": {"analysis_id": str(run.analysis_id)}},
        )

    async def succeed(
        self,
        analysis_id,
        *,
        completed_at: datetime,
        report: PhotographyReport,
        metadata: AnalysisMetadata,
    ) -> None:
        """Store report data without ever receiving the feedback token."""
        row = await self._require_running(analysis_id)
        if row is None:
            return

        retrieval = metadata.retrieval
        row.status = "succeeded"
        row.completed_at = _naive(completed_at)
        row.report_json = report.model_dump_json()
        row.metadata_json = metadata.model_dump_json()
        row.provider = metadata.provider
        row.model = metadata.model
        row.prompt_version = metadata.prompt_version
        row.planner_prompt_version = (
            retrieval.planner_prompt_version if retrieval else None
        )
        row.knowledge_source_id = retrieval.knowledge_source_id if retrieval else None
        row.knowledge_source_version = (
            retrieval.knowledge_source_version if retrieval else None
        )
        row.embedding_model = retrieval.embedding_model if retrieval else None
        row.reranker_model = retrieval.reranker_model if retrieval else None
        row.retrieved_chunk_ids_json = (
            dumps(retrieval.retrieved_chunk_ids) if retrieval else None
        )
        row.input_tokens = metadata.usage.input_tokens
        row.output_tokens = metadata.usage.output_tokens
        row.total_tokens = metadata.usage.total_tokens
        row.latency_ms = metadata.latency_ms
        row.report_retained_until = _naive(completed_at) + timedelta(
            days=REPORT_RETENTION_DAYS
        )
        await self._session.commit()
        logger.info(
            "analysis_run_succeeded",
            extra={"event_data": {"analysis_id": str(analysis_id)}},
        )

    async def fail(self, failure: AnalysisRunFailure) -> None:
        """Store one sanitized terminal failure for operational diagnosis."""
        row = await self._require_running(failure.analysis_id)
        if row is None:
            return

        row.status = "failed"
        row.completed_at = _naive(failure.completed_at)
        row.error_code = failure.error_code
        row.sanitized_diagnostic = failure.sanitized_diagnostic
        row.latency_ms = failure.latency_ms
        await self._session.commit()
        logger.info(
            "analysis_run_failed",
            extra={
                "event_data": {
                    "analysis_id": str(failure.analysis_id),
                    "error_code": failure.error_code,
                }
            },
        )

    async def _require_running(self, analysis_id) -> AnalysisRun | None:
        row = await self._session.get(AnalysisRun, analysis_id)
        if row is None:
            raise AnalysisRunMissingError(
                f"No analysis run found for {analysis_id}."
            )
        if row.status != "running":
            logger.warning(
                "analysis_run_already_terminal",
                extra={
                    "event_data": {
                        "analysis_id": str(analysis_id),
                        "status": row.status,
                    }
                },
            )
            return None
        return row


class AnalysisRunMissingError(RuntimeError):
    """Raised when lifecycle data arrives for an unknown analysis."""


def _naive(value: datetime) -> datetime:
    """Store datetimes as naive UTC for SQLite/PostgreSQL portability."""
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def stored_run_metadata(row: AnalysisRun) -> AnalysisMetadata | None:
    """Rebuild the public metadata model from a stored run row."""
    if row.metadata_json is None:
        return None
    return AnalysisMetadata.model_validate_json(row.metadata_json)
