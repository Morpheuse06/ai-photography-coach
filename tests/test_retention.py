"""Tests for the daily retention cleanup pass."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.persistence.engine import (
    create_db_engine,
    create_schema,
    session_factory_for,
)
from photography_coach.persistence.models import (
    AccessCode,
    AccessCodeBatch,
    AccessCodeUsageEvent,
    AdminSession,
    AdminUser,
    AnalysisRun,
    DimensionRating,
    UsageReservation as UsageReservationRow,
    utc_now,
)
from photography_coach.persistence.usage import PolicyDefaults, SqlUsageAuthorizer
from photography_coach.providers.mock import MockPhotographyProvider
from photography_coach.schemas.interaction import AccessMode
from photography_coach.security import hash_secret
from photography_coach.services.retention import RetentionService

RAW_CODE = "PXC-AAAA-BBBB-CCCC-DDDD"


class RetentionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        url = f"sqlite+aiosqlite:///{Path(self._tmp.name) / 'retention.db'}"
        self.engine = create_db_engine(url)
        self.session_factory = session_factory_for(self.engine)
        await create_schema(self.engine)
        self._sessions: list[AsyncSession] = []

    async def asyncTearDown(self) -> None:
        for session in self._sessions:
            await session.close()
        await self.engine.dispose()
        self._tmp.cleanup()

    def session(self) -> AsyncSession:
        session = self.session_factory()
        self._sessions.append(session)
        return session

    def retention_service(
        self,
        session: AsyncSession,
    ) -> RetentionService:
        authorizer = SqlUsageAuthorizer(
            session,
            reservation_ttl_minutes=30,
            policy_defaults=PolicyDefaults(
                mode=AccessMode.OPEN,
                per_source_hour_limit=1000,
                global_daily_limit=None,
                concurrent_analysis_limit=10,
            ),
        )
        return RetentionService(session, authorizer=authorizer)

    async def seed_run(
        self,
        session: AsyncSession,
        *,
        started_ago: timedelta,
        status: str = "succeeded",
        with_content: bool = True,
    ):
        analysis_id = uuid4()
        report_json = None
        metadata_json = None
        if with_content:
            report_json = (
                await MockPhotographyProvider().analyze(
                    b"x", "image/png", None, None
                )
            ).report.model_dump_json()
            metadata_json = '{"provider": "mock"}'
        session.add(
            AnalysisRun(
                analysis_id=analysis_id,
                api_version="v2",
                status=status,
                started_at=utc_now() - started_ago,
                completed_at=utc_now() - started_ago,
                media_type="image/png",
                width=8,
                height=6,
                size_bytes=100,
                shooting_intent="旧意图" if with_content else None,
                report_json=report_json,
                metadata_json=metadata_json,
                provider="mock",
                model="mock-model",
                latency_ms=10,
                report_retained_until=(
                    utc_now() - started_ago + timedelta(days=30)
                    if with_content
                    else None
                ),
            )
        )
        await session.commit()
        return analysis_id

    async def seed_code(self, session: AsyncSession, *, uses_total: int = 2):
        batch = AccessCodeBatch(
            label="batch", quantity=1, uses_per_code=uses_total, created_by="t"
        )
        session.add(batch)
        await session.flush()
        code = AccessCode(
            batch_id=batch.id,
            code_hash=hash_secret(RAW_CODE),
            prefix="PXC-AAAA",
            uses_total=uses_total,
            status="active",
        )
        session.add(code)
        await session.commit()
        return code.id

    async def test_clears_sensitive_content_after_30_days(self) -> None:
        session = self.session()
        analysis_id = await self.seed_run(
            session, started_ago=timedelta(days=31)
        )

        counts = await self.retention_service(session).run_cleanup()

        self.assertEqual(counts.intents_cleared, 1)
        self.assertEqual(counts.reports_cleared, 1)
        row = await session.get(AnalysisRun, analysis_id)
        self.assertIsNone(row.shooting_intent)
        self.assertIsNone(row.report_json)
        self.assertIsNone(row.report_retained_until)
        # Metrics survive the content sweep.
        self.assertEqual(row.provider, "mock")
        self.assertIsNotNone(row.metadata_json)

    async def test_keeps_recent_reports_untouched(self) -> None:
        session = self.session()
        analysis_id = await self.seed_run(
            session, started_ago=timedelta(days=5)
        )

        await self.retention_service(session).run_cleanup()

        row = await session.get(AnalysisRun, analysis_id)
        self.assertIsNotNone(row.report_json)
        self.assertIsNotNone(row.shooting_intent)

    async def test_deletes_metrics_and_cascades_ratings_after_180_days(self) -> None:
        session = self.session()
        analysis_id = await self.seed_run(
            session, started_ago=timedelta(days=181), with_content=False
        )
        session.add(
            DimensionRating(
                analysis_id=analysis_id,
                target="lighting",
                vote="up",
                reason_codes_json="[]",
            )
        )
        await session.commit()

        counts = await self.retention_service(session).run_cleanup()

        self.assertEqual(counts.metrics_deleted, 1)
        self.assertIsNone(await session.get(AnalysisRun, analysis_id))
        ratings = await session.scalar(
            select(func.count()).select_from(DimensionRating)
        )
        self.assertEqual(ratings, 0)

    async def test_releases_expired_reservations(self) -> None:
        session = self.session()
        await self.seed_code(session)
        authorizer = SqlUsageAuthorizer(
            session,
            reservation_ttl_minutes=30,
            policy_defaults=PolicyDefaults(
                mode=AccessMode.CODE_REQUIRED,
                per_source_hour_limit=1000,
                global_daily_limit=None,
                concurrent_analysis_limit=10,
            ),
        )
        reservation = await authorizer.reserve(
            analysis_id=uuid4(),
            access_code=RAW_CODE,
            idempotency_key="retention-key-1",
            request_fingerprint="fp-1",
        )
        row = await session.get(UsageReservationRow, reservation.reservation_id)
        row.expires_at = utc_now() - timedelta(minutes=1)
        await session.commit()

        counts = await self.retention_service(session).run_cleanup()

        self.assertEqual(counts.reservations_released, 1)
        await session.refresh(row)
        self.assertEqual(row.status, "released")
        self.assertEqual(row.release_reason, "reservation_expired")
        code = await session.get(AccessCode, reservation.access_code_id)
        self.assertEqual(code.uses_reserved, 0)
        events = (
            await session.scalars(
                select(AccessCodeUsageEvent).where(
                    AccessCodeUsageEvent.event_type == "released"
                )
            )
        ).all()
        self.assertEqual(len(events), 1)

    async def test_revokes_expired_admin_sessions(self) -> None:
        session = self.session()
        user = AdminUser(
            username="owner", password_hash="x", is_active=True
        )
        session.add(user)
        await session.flush()
        session.add(
            AdminSession(
                admin_user_id=user.id,
                token_hash=hash_secret("expired-token"),
                expires_at=utc_now() - timedelta(hours=1),
            )
        )
        session.add(
            AdminSession(
                admin_user_id=user.id,
                token_hash=hash_secret("live-token"),
                expires_at=utc_now() + timedelta(hours=1),
            )
        )
        await session.commit()

        counts = await self.retention_service(session).run_cleanup()

        self.assertEqual(counts.sessions_revoked, 1)
        sessions = (
            await session.scalars(select(AdminSession))
        ).all()
        by_hash = {row.token_hash: row for row in sessions}
        self.assertIsNotNone(
            by_hash[hash_secret("expired-token")].revoked_at
        )
        self.assertIsNone(by_hash[hash_secret("live-token")].revoked_at)

    async def test_closes_stuck_running_runs(self) -> None:
        session = self.session()
        analysis_id = await self.seed_run(
            session,
            started_ago=timedelta(hours=25),
            status="running",
            with_content=False,
        )

        counts = await self.retention_service(session).run_cleanup()

        self.assertEqual(counts.stuck_runs_closed, 1)
        row = await session.get(AnalysisRun, analysis_id)
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.error_code, "internal_error")

    async def test_reconciles_succeeded_runs_with_reserved_quota(self) -> None:
        session = self.session()
        code_id = await self.seed_code(session)
        authorizer = SqlUsageAuthorizer(
            session,
            reservation_ttl_minutes=30,
            policy_defaults=PolicyDefaults(
                mode=AccessMode.CODE_REQUIRED,
                per_source_hour_limit=1000,
                global_daily_limit=None,
                concurrent_analysis_limit=10,
            ),
        )
        reservation = await authorizer.reserve(
            analysis_id=uuid4(),
            access_code=RAW_CODE,
            idempotency_key="retention-key-2",
            request_fingerprint="fp-2",
        )
        # The report was stored but the quota confirmation never landed.
        session.add(
            AnalysisRun(
                analysis_id=reservation.analysis_id,
                api_version="v2",
                status="succeeded",
                started_at=utc_now() - timedelta(minutes=5),
                completed_at=utc_now() - timedelta(minutes=4),
                media_type="image/png",
                width=8,
                height=6,
                size_bytes=100,
                reservation_id=reservation.reservation_id,
                access_code_id=code_id,
            )
        )
        await session.commit()

        counts = await self.retention_service(session).run_cleanup()

        self.assertEqual(counts.reservations_reconciled, 1)
        row = await session.get(UsageReservationRow, reservation.reservation_id)
        self.assertEqual(row.status, "consumed")
        code = await session.get(AccessCode, code_id)
        self.assertEqual(code.uses_consumed, 1)
        self.assertEqual(code.uses_reserved, 0)

    async def test_audits_each_cleanup_run(self) -> None:
        session = self.session()

        await self.retention_service(session).run_cleanup()

        from photography_coach.persistence.models import AdminAuditEvent

        events = (
            await session.scalars(
                select(AdminAuditEvent).where(
                    AdminAuditEvent.action == "retention.cleanup"
                )
            )
        ).all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].admin_subject, "system")


if __name__ == "__main__":
    unittest.main()
