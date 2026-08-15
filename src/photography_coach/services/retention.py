"""Daily retention cleanup for the control-plane database.

Sensitive content (shooting intent and full reports) is cleared after 30
days, analysis metrics are deleted after 180 days, expired reservations and
admin sessions are released or revoked, stuck running records are closed,
and reservations whose reports succeeded but whose commit failed are
reconciled. Counts are logged and audited; cleared content is never logged.
"""

from dataclasses import dataclass
from datetime import timedelta
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.persistence.admin_service import SqlAdminService
from photography_coach.persistence.models import (
    AdminSession,
    AnalysisRun,
    UsageReservation as UsageReservationRow,
    utc_now,
)
from photography_coach.persistence.usage import SqlUsageAuthorizer

logger = logging.getLogger(__name__)

REPORT_RETENTION_DAYS = 30
METRICS_RETENTION_DAYS = 180
STUCK_RUN_HOURS = 24


@dataclass(frozen=True, slots=True)
class RetentionCounts:
    """Number of rows changed per cleanup action, for logs and audit."""

    intents_cleared: int
    reports_cleared: int
    metrics_deleted: int
    reservations_released: int
    sessions_revoked: int
    stuck_runs_closed: int
    reservations_reconciled: int

    def as_dict(self) -> dict[str, int]:
        return {
            "intents_cleared": self.intents_cleared,
            "reports_cleared": self.reports_cleared,
            "metrics_deleted": self.metrics_deleted,
            "reservations_released": self.reservations_released,
            "sessions_revoked": self.sessions_revoked,
            "stuck_runs_closed": self.stuck_runs_closed,
            "reservations_reconciled": self.reservations_reconciled,
        }


class RetentionService:
    """Run one full retention pass over the control-plane database."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        authorizer: SqlUsageAuthorizer,
    ) -> None:
        self._session = session
        self._authorizer = authorizer

    async def run_cleanup(self) -> RetentionCounts:
        """Execute every cleanup step and audit the resulting counts."""
        now = utc_now()
        counts = RetentionCounts(
            intents_cleared=0,
            reports_cleared=0,
            metrics_deleted=0,
            reservations_released=0,
            sessions_revoked=0,
            stuck_runs_closed=0,
            reservations_reconciled=0,
        )
        counts = await self._clear_report_content(now, counts)
        counts = await self._delete_old_metrics(now, counts)
        counts = await self._close_stuck_runs(now, counts)
        counts = await self._release_expired_reservations(now, counts)
        counts = await self._revoke_expired_sessions(now, counts)
        counts = await self._reconcile_succeeded_reservations(counts)

        logger.info(
            "retention_completed",
            extra={"event_data": counts.as_dict()},
        )
        await self._session.commit()
        async with self._session.begin():
            SqlAdminService(self._session).add_audit(
                "system",
                "retention.cleanup",
                "system",
                None,
                counts.as_dict(),
            )
        return counts

    async def _clear_report_content(
        self,
        now,
        counts: RetentionCounts,
    ) -> RetentionCounts:
        deadline = now - timedelta(days=REPORT_RETENTION_DAYS)
        result = await self._session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.started_at < deadline)
            .values(
                shooting_intent=None,
                report_json=None,
                report_retained_until=None,
            )
        )
        await self._session.commit()
        cleared = result.rowcount or 0
        return RetentionCounts(
            intents_cleared=counts.intents_cleared + cleared,
            reports_cleared=counts.reports_cleared + cleared,
            metrics_deleted=counts.metrics_deleted,
            reservations_released=counts.reservations_released,
            sessions_revoked=counts.sessions_revoked,
            stuck_runs_closed=counts.stuck_runs_closed,
            reservations_reconciled=counts.reservations_reconciled,
        )

    async def _delete_old_metrics(
        self,
        now,
        counts: RetentionCounts,
    ) -> RetentionCounts:
        deadline = now - timedelta(days=METRICS_RETENTION_DAYS)
        rows = (
            await self._session.scalars(
                select(AnalysisRun).where(AnalysisRun.started_at < deadline)
            )
        ).all()
        for row in rows:
            await self._session.delete(row)
        await self._session.commit()
        return RetentionCounts(
            intents_cleared=counts.intents_cleared,
            reports_cleared=counts.reports_cleared,
            metrics_deleted=counts.metrics_deleted + len(rows),
            reservations_released=counts.reservations_released,
            sessions_revoked=counts.sessions_revoked,
            stuck_runs_closed=counts.stuck_runs_closed,
            reservations_reconciled=counts.reservations_reconciled,
        )

    async def _close_stuck_runs(
        self,
        now,
        counts: RetentionCounts,
    ) -> RetentionCounts:
        deadline = now - timedelta(hours=STUCK_RUN_HOURS)
        result = await self._session.execute(
            update(AnalysisRun)
            .where(
                AnalysisRun.status == "running",
                AnalysisRun.started_at < deadline,
            )
            .values(
                status="failed",
                completed_at=now,
                error_code="internal_error",
                sanitized_diagnostic="Closed by retention cleanup.",
            )
        )
        await self._session.commit()
        closed = result.rowcount or 0
        return RetentionCounts(
            intents_cleared=counts.intents_cleared,
            reports_cleared=counts.reports_cleared,
            metrics_deleted=counts.metrics_deleted,
            reservations_released=counts.reservations_released,
            sessions_revoked=counts.sessions_revoked,
            stuck_runs_closed=counts.stuck_runs_closed + closed,
            reservations_reconciled=counts.reservations_reconciled,
        )

    async def _release_expired_reservations(
        self,
        now,
        counts: RetentionCounts,
    ) -> RetentionCounts:
        rows = (
            await self._session.scalars(
                select(UsageReservationRow).where(
                    UsageReservationRow.status == "reserved",
                    UsageReservationRow.expires_at <= now,
                )
            )
        ).all()
        released = 0
        for row in rows:
            try:
                await self._authorizer.release(
                    row.id,
                    analysis_id=row.analysis_id,
                    reason="reservation_expired",
                )
                released += 1
            except Exception:
                logger.exception(
                    "retention_release_failed",
                    extra={
                        "event_data": {
                            "reservation_id": str(row.id),
                        }
                    },
                )
        return RetentionCounts(
            intents_cleared=counts.intents_cleared,
            reports_cleared=counts.reports_cleared,
            metrics_deleted=counts.metrics_deleted,
            reservations_released=counts.reservations_released + released,
            sessions_revoked=counts.sessions_revoked,
            stuck_runs_closed=counts.stuck_runs_closed,
            reservations_reconciled=counts.reservations_reconciled,
        )

    async def _revoke_expired_sessions(
        self,
        now,
        counts: RetentionCounts,
    ) -> RetentionCounts:
        result = await self._session.execute(
            update(AdminSession)
            .where(
                AdminSession.revoked_at.is_(None),
                AdminSession.expires_at <= now,
            )
            .values(revoked_at=now)
        )
        await self._session.commit()
        revoked = result.rowcount or 0
        return RetentionCounts(
            intents_cleared=counts.intents_cleared,
            reports_cleared=counts.reports_cleared,
            metrics_deleted=counts.metrics_deleted,
            reservations_released=counts.reservations_released,
            sessions_revoked=counts.sessions_revoked + revoked,
            stuck_runs_closed=counts.stuck_runs_closed,
            reservations_reconciled=counts.reservations_reconciled,
        )

    async def _reconcile_succeeded_reservations(
        self,
        counts: RetentionCounts,
    ) -> RetentionCounts:
        """Commit reservations whose analysis succeeded but confirm failed.

        This is the recovery path for "report generated but the quota
        confirmation failed": the reservation is still reserved and the run
        is terminal, so the commit is idempotent and safe to retry.
        """
        rows = (
            await self._session.scalars(
                select(UsageReservationRow)
                .join(
                    AnalysisRun,
                    AnalysisRun.analysis_id == UsageReservationRow.analysis_id,
                )
                .where(
                    UsageReservationRow.status == "reserved",
                    AnalysisRun.status == "succeeded",
                )
            )
        ).all()
        reconciled = 0
        for row in rows:
            try:
                await self._authorizer.commit(
                    row.id,
                    analysis_id=row.analysis_id,
                )
                reconciled += 1
            except Exception:
                logger.exception(
                    "retention_reconcile_failed",
                    extra={
                        "event_data": {
                            "reservation_id": str(row.id),
                        }
                    },
                )
        return RetentionCounts(
            intents_cleared=counts.intents_cleared,
            reports_cleared=counts.reports_cleared,
            metrics_deleted=counts.metrics_deleted,
            reservations_released=counts.reservations_released,
            sessions_revoked=counts.sessions_revoked,
            stuck_runs_closed=counts.stuck_runs_closed,
            reservations_reconciled=counts.reservations_reconciled + reconciled,
        )
