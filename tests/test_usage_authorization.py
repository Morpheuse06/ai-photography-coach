"""Tests for atomic access-code quota reservations and the usage ledger."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.errors import (
    AccessCodeRequiredError,
    AccessDeniedError,
    AccessQuotaExhaustedError,
    AnalysisClosedError,
    ConcurrencyLimitReachedError,
    GlobalQuotaExhaustedError,
    IdempotencyConflictError,
)
from photography_coach.persistence.engine import (
    create_db_engine,
    create_schema,
    session_factory_for,
)
from photography_coach.persistence.models import (
    AccessCode,
    AccessCodeBatch,
    AccessCodeUsageEvent,
)
from photography_coach.persistence.usage import PolicyDefaults, SqlUsageAuthorizer
from photography_coach.schemas.interaction import AccessMode
from photography_coach.security import hash_secret

RAW_CODE = "PXC-AAAA-BBBB-CCCC-DDDD"


class UsageAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        url = f"sqlite+aiosqlite:///{Path(self._tmp.name) / 'usage.db'}"
        self.engine = create_db_engine(url)
        self.session_factory = session_factory_for(self.engine)
        await create_schema(self.engine)
        self._sessions: list[AsyncSession] = []

    async def asyncTearDown(self) -> None:
        for session in self._sessions:
            await session.close()
        await self.engine.dispose()
        self._tmp.cleanup()

    def new_session(self) -> AsyncSession:
        session = self.session_factory()
        self._sessions.append(session)
        return session

    def authorizer(
        self,
        session: AsyncSession,
        *,
        mode: AccessMode = AccessMode.OPEN,
        global_daily_limit: int | None = None,
        concurrent_limit: int = 100,
    ) -> SqlUsageAuthorizer:
        return SqlUsageAuthorizer(
            session,
            reservation_ttl_minutes=30,
            policy_defaults=PolicyDefaults(
                mode=mode,
                per_source_hour_limit=1000,
                global_daily_limit=global_daily_limit,
                concurrent_analysis_limit=concurrent_limit,
            ),
        )

    async def seed_policy(
        self,
        session: AsyncSession,
        *,
        mode: AccessMode = AccessMode.OPEN,
        global_daily_limit: int | None = None,
        concurrent_limit: int = 100,
    ) -> None:
        authorizer = self.authorizer(
            session,
            mode=mode,
            global_daily_limit=global_daily_limit,
            concurrent_limit=concurrent_limit,
        )
        await authorizer.get_or_create_policy()

    async def create_code(
        self,
        session: AsyncSession,
        *,
        uses_total: int = 1,
        status: str = "active",
        expires_at: datetime | None = None,
        revoked_at: datetime | None = None,
        raw_code: str = RAW_CODE,
    ) -> UUID:
        batch = AccessCodeBatch(
            label="test-batch",
            quantity=1,
            uses_per_code=uses_total,
            created_by="test",
        )
        session.add(batch)
        await session.flush()
        code = AccessCode(
            batch_id=batch.id,
            code_hash=hash_secret(raw_code),
            prefix=raw_code[:8],
            uses_total=uses_total,
            status=status,
            expires_at=(
                expires_at.replace(tzinfo=None) if expires_at else None
            ),
            revoked_at=revoked_at.replace(tzinfo=None) if revoked_at else None,
        )
        session.add(code)
        await session.commit()
        return code.id

    async def ledger_sum(
        self,
        session: AsyncSession,
        code_id: UUID,
        event_types: tuple[str, ...],
    ) -> int:
        return await session.scalar(
            select(func.coalesce(func.sum(AccessCodeUsageEvent.delta), 0)).where(
                AccessCodeUsageEvent.code_id == code_id,
                AccessCodeUsageEvent.event_type.in_(event_types),
            )
        )

    async def ledger_reserved(self, session: AsyncSession, code_id: UUID) -> int:
        """Rebuild the reserved balance from ledger event deltas.

        A reserved event claims one use (+1), a released event returns it
        (-1), and a consumed event moves the claim out of reserved (+1 on the
        consumed side), so the reserved balance is
        sum(reserved) + sum(released) - sum(consumed).
        """
        reserved = await self.ledger_sum(session, code_id, ("reserved",))
        released = await self.ledger_sum(session, code_id, ("released",))
        consumed = await self.ledger_sum(session, code_id, ("consumed",))
        return reserved + released - consumed

    async def test_open_mode_reservation_needs_no_code(self) -> None:
        session = self.new_session()
        await self.seed_policy(session)
        reservation = await self.authorizer(session).reserve(
            analysis_id=uuid4(),
            access_code=None,
            idempotency_key="key-1",
            request_fingerprint="fp-1",
        )

        self.assertEqual(reservation.mode, AccessMode.OPEN)
        self.assertIsNone(reservation.access_code_id)
        self.assertIsNone(reservation.remaining_uses_after_reservation)

    async def test_code_required_without_code_is_401(self) -> None:
        session = self.new_session()
        await self.seed_policy(session, mode=AccessMode.CODE_REQUIRED)

        with self.assertRaises(AccessCodeRequiredError):
            await self.authorizer(
                session, mode=AccessMode.CODE_REQUIRED
            ).reserve(
                analysis_id=uuid4(),
                access_code=None,
                idempotency_key="key-2",
                request_fingerprint="fp-2",
            )

    async def test_unknown_revoked_and_expired_codes_are_denied(self) -> None:
        session = self.new_session()
        await self.seed_policy(session, mode=AccessMode.CODE_REQUIRED)
        authorizer = self.authorizer(session, mode=AccessMode.CODE_REQUIRED)

        with self.assertRaises(AccessDeniedError):
            await authorizer.reserve(
                analysis_id=uuid4(),
                access_code="PXC-UNKNOWN-CODE-0000",
                idempotency_key="key-3",
                request_fingerprint="fp-3",
            )

        revoked_raw = "PXC-RVKD-2222-3333-4444"
        await self.create_code(
            session, revoked_at=datetime.now(UTC), raw_code=revoked_raw
        )
        with self.assertRaises(AccessDeniedError):
            await authorizer.reserve(
                analysis_id=uuid4(),
                access_code=revoked_raw,
                idempotency_key="key-4",
                request_fingerprint="fp-4",
            )

        expired_raw = "PXC-EXPD-5555-6666-7777"
        await self.create_code(
            session,
            expires_at=datetime.now(UTC) - timedelta(hours=1),
            raw_code=expired_raw,
        )
        with self.assertRaises(AccessDeniedError):
            await authorizer.reserve(
                analysis_id=uuid4(),
                access_code=expired_raw,
                idempotency_key="key-5",
                request_fingerprint="fp-5",
            )

    async def test_reserve_then_commit_consumes_exactly_one_use(self) -> None:
        session = self.new_session()
        await self.seed_policy(session, mode=AccessMode.CODE_REQUIRED)
        authorizer = self.authorizer(session, mode=AccessMode.CODE_REQUIRED)
        code_id = await self.create_code(session, uses_total=2)
        analysis_id = uuid4()

        reservation = await authorizer.reserve(
            analysis_id=analysis_id,
            access_code=RAW_CODE,
            idempotency_key="key-6",
            request_fingerprint="fp-6",
        )
        self.assertEqual(reservation.remaining_uses_after_reservation, 1)

        access = await authorizer.commit(
            reservation.reservation_id,
            analysis_id=analysis_id,
        )
        self.assertEqual(access.remaining_uses, 1)

        code = await session.get(AccessCode, code_id)
        self.assertEqual(code.uses_consumed, 1)
        self.assertEqual(code.uses_reserved, 0)
        self.assertEqual(
            await self.ledger_sum(session, code_id, ("consumed",)), 1
        )
        self.assertEqual(await self.ledger_reserved(session, code_id), 0)

    async def test_repeated_commit_does_not_change_balance(self) -> None:
        session = self.new_session()
        await self.seed_policy(session, mode=AccessMode.CODE_REQUIRED)
        authorizer = self.authorizer(session, mode=AccessMode.CODE_REQUIRED)
        code_id = await self.create_code(session, uses_total=2)
        analysis_id = uuid4()
        reservation = await authorizer.reserve(
            analysis_id=analysis_id,
            access_code=RAW_CODE,
            idempotency_key="key-7",
            request_fingerprint="fp-7",
        )

        first = await authorizer.commit(
            reservation.reservation_id, analysis_id=analysis_id
        )
        second = await authorizer.commit(
            reservation.reservation_id, analysis_id=analysis_id
        )

        self.assertEqual(first, second)
        code = await session.get(AccessCode, code_id)
        self.assertEqual(code.uses_consumed, 1)
        self.assertEqual(
            await self.ledger_sum(session, code_id, ("consumed",)), 1
        )

    async def test_release_restores_reserved_use_and_repeats_are_no_ops(self) -> None:
        session = self.new_session()
        await self.seed_policy(session, mode=AccessMode.CODE_REQUIRED)
        authorizer = self.authorizer(session, mode=AccessMode.CODE_REQUIRED)
        code_id = await self.create_code(session, uses_total=1)
        analysis_id = uuid4()
        reservation = await authorizer.reserve(
            analysis_id=analysis_id,
            access_code=RAW_CODE,
            idempotency_key="key-8",
            request_fingerprint="fp-8",
        )

        await authorizer.release(
            reservation.reservation_id,
            analysis_id=analysis_id,
            reason="model_timeout",
        )
        await authorizer.release(
            reservation.reservation_id,
            analysis_id=analysis_id,
            reason="model_timeout",
        )

        code = await session.get(AccessCode, code_id)
        self.assertEqual(code.uses_reserved, 0)
        self.assertEqual(code.uses_consumed, 0)
        self.assertEqual(code.status, "active")
        self.assertEqual(await self.ledger_reserved(session, code_id), 0)

    async def test_exhausted_code_cannot_reserve(self) -> None:
        session = self.new_session()
        await self.seed_policy(session, mode=AccessMode.CODE_REQUIRED)
        authorizer = self.authorizer(session, mode=AccessMode.CODE_REQUIRED)
        code_id = await self.create_code(session, uses_total=1)
        analysis_id = uuid4()
        reservation = await authorizer.reserve(
            analysis_id=analysis_id,
            access_code=RAW_CODE,
            idempotency_key="key-9",
            request_fingerprint="fp-9",
        )
        await authorizer.commit(reservation.reservation_id, analysis_id=analysis_id)

        with self.assertRaises(AccessQuotaExhaustedError):
            await authorizer.reserve(
                analysis_id=uuid4(),
                access_code=RAW_CODE,
                idempotency_key="key-10",
                request_fingerprint="fp-10",
            )
        code = await session.get(AccessCode, code_id)
        self.assertEqual(code.status, "exhausted")

    async def test_two_concurrent_reservations_cannot_split_the_last_use(self) -> None:
        session = self.new_session()
        await self.seed_policy(
            session, mode=AccessMode.CODE_REQUIRED, concurrent_limit=10
        )
        await self.create_code(session, uses_total=1)

        first_session = self.new_session()
        second_session = self.new_session()
        first = self.authorizer(
            first_session, mode=AccessMode.CODE_REQUIRED, concurrent_limit=10
        )
        second = self.authorizer(
            second_session, mode=AccessMode.CODE_REQUIRED, concurrent_limit=10
        )

        results = await asyncio.gather(
            first.reserve(
                analysis_id=uuid4(),
                access_code=RAW_CODE,
                idempotency_key="key-11",
                request_fingerprint="fp-11",
            ),
            second.reserve(
                analysis_id=uuid4(),
                access_code=RAW_CODE,
                idempotency_key="key-12",
                request_fingerprint="fp-12",
            ),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], AccessQuotaExhaustedError)
        code = await session.get(
            AccessCode, await self._code_id(session)
        )
        self.assertEqual(code.uses_reserved, 1)
        self.assertEqual(code.uses_consumed, 0)

    async def test_duplicate_idempotency_key_replays_and_conflicts(self) -> None:
        session = self.new_session()
        await self.seed_policy(session, mode=AccessMode.CODE_REQUIRED)
        authorizer = self.authorizer(session, mode=AccessMode.CODE_REQUIRED)
        await self.create_code(session, uses_total=2)
        first = await authorizer.reserve(
            analysis_id=uuid4(),
            access_code=RAW_CODE,
            idempotency_key="key-13",
            request_fingerprint="fp-13",
        )

        # A retry of the same request while reserved replays the reservation.
        replay = await authorizer.reserve(
            analysis_id=uuid4(),
            access_code=RAW_CODE,
            idempotency_key="key-13",
            request_fingerprint="fp-13",
        )
        self.assertEqual(replay.reservation_id, first.reservation_id)
        self.assertEqual(replay.analysis_id, first.analysis_id)

        # A different request reusing the key is a conflict.
        with self.assertRaises(IdempotencyConflictError):
            await authorizer.reserve(
                analysis_id=uuid4(),
                access_code=RAW_CODE,
                idempotency_key="key-13",
                request_fingerprint="fp-13-other",
            )

        # The authorizer replays the terminal reservation too; the service
        # layer decides whether to rebuild a stored response.
        await authorizer.commit(first.reservation_id, analysis_id=first.analysis_id)
        terminal_replay = await authorizer.reserve(
            analysis_id=uuid4(),
            access_code=RAW_CODE,
            idempotency_key="key-13",
            request_fingerprint="fp-13",
        )
        self.assertEqual(terminal_replay.reservation_id, first.reservation_id)

    async def test_same_key_with_different_code_is_a_conflict(self) -> None:
        session = self.new_session()
        await self.seed_policy(session, mode=AccessMode.CODE_REQUIRED)
        authorizer = self.authorizer(session, mode=AccessMode.CODE_REQUIRED)
        code_a = await self.create_code(session, uses_total=2)
        code_b = await self.create_code(
            session, uses_total=2, raw_code="PXC-EEEE-FFFF-GGGG-HHHH"
        )
        del code_a, code_b

        await authorizer.reserve(
            analysis_id=uuid4(),
            access_code=RAW_CODE,
            idempotency_key="key-14",
            request_fingerprint="fp-14-a",
        )
        with self.assertRaises(IdempotencyConflictError):
            await authorizer.reserve(
                analysis_id=uuid4(),
                access_code="PXC-EEEE-FFFF-GGGG-HHHH",
                idempotency_key="key-14",
                request_fingerprint="fp-14-b",
            )

    async def test_closed_mode_rejects_every_analysis(self) -> None:
        session = self.new_session()
        await self.seed_policy(session, mode=AccessMode.CLOSED)

        with self.assertRaises(AnalysisClosedError):
            await self.authorizer(session, mode=AccessMode.CLOSED).reserve(
                analysis_id=uuid4(),
                access_code=None,
                idempotency_key="key-15",
                request_fingerprint="fp-15",
            )

    async def test_global_daily_and_concurrency_limits_apply_in_open_mode(self) -> None:
        session = self.new_session()
        await self.seed_policy(
            session, global_daily_limit=1, concurrent_limit=1
        )
        authorizer = self.authorizer(
            session, global_daily_limit=1, concurrent_limit=1
        )
        first = await authorizer.reserve(
            analysis_id=uuid4(),
            access_code=None,
            idempotency_key="key-16",
            request_fingerprint="fp-16",
        )

        with self.assertRaises(ConcurrencyLimitReachedError):
            await authorizer.reserve(
                analysis_id=uuid4(),
                access_code=None,
                idempotency_key="key-17",
                request_fingerprint="fp-17",
            )

        await authorizer.commit(first.reservation_id, analysis_id=first.analysis_id)
        with self.assertRaises(GlobalQuotaExhaustedError):
            await authorizer.reserve(
                analysis_id=uuid4(),
                access_code=None,
                idempotency_key="key-18",
                request_fingerprint="fp-18",
            )

    async def test_ledger_balances_reconstruct_usage(self) -> None:
        session = self.new_session()
        await self.seed_policy(session, mode=AccessMode.CODE_REQUIRED)
        authorizer = self.authorizer(session, mode=AccessMode.CODE_REQUIRED)
        code_id = await self.create_code(session, uses_total=3)

        for index in range(2):
            reservation = await authorizer.reserve(
                analysis_id=uuid4(),
                access_code=RAW_CODE,
                idempotency_key=f"key-ledger-{index}",
                request_fingerprint=f"fp-ledger-{index}",
            )
            await authorizer.commit(
                reservation.reservation_id, analysis_id=reservation.analysis_id
            )

        released = await authorizer.reserve(
            analysis_id=uuid4(),
            access_code=RAW_CODE,
            idempotency_key="key-ledger-3",
            request_fingerprint="fp-ledger-3",
        )
        await authorizer.release(
            released.reservation_id,
            analysis_id=released.analysis_id,
            reason="model_timeout",
        )

        code = await session.get(AccessCode, code_id)
        self.assertEqual(code.uses_consumed, 2)
        self.assertEqual(
            await self.ledger_sum(session, code_id, ("consumed",)), 2
        )
        self.assertEqual(await self.ledger_reserved(session, code_id), 0)
        events = (
            await session.scalars(
                select(AccessCodeUsageEvent)
                .where(AccessCodeUsageEvent.code_id == code_id)
                .order_by(AccessCodeUsageEvent.occurred_at)
            )
        ).all()
        self.assertEqual(
            [event.event_type for event in events],
            ["reserved", "consumed", "reserved", "consumed", "reserved", "released"],
        )
        self.assertEqual(events[-1].reason, "model_timeout")

    async def _code_id(self, session: AsyncSession) -> UUID:
        return await session.scalar(select(AccessCode.id))


if __name__ == "__main__":
    unittest.main()
