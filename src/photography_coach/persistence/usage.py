"""SQL implementation of the usage authorizer port.

Every quota mutation runs in one short transaction. The conditional UPDATE
on the code row is atomic under both SQLite (WAL write lock with busy
timeout) and PostgreSQL (row lock), so two concurrent reservations can never
overspend the last remaining use. Balance columns answer fast queries; the
append-only ledger stays in the same transaction for audit and rebuilds.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.errors import (
    AccessCodeRequiredError,
    AccessDeniedError,
    AccessQuotaExhaustedError,
    AnalysisClosedError,
    AppError,
    ConcurrencyLimitReachedError,
    ControlPlaneUnavailableError,
    GlobalQuotaExhaustedError,
    IdempotencyConflictError,
)
from photography_coach.persistence.models import (
    AccessCode,
    AccessCodeUsageEvent,
    AccessPolicyRow,
    UsageReservation as UsageReservationRow,
    as_aware_utc,
    utc_now,
)
from photography_coach.ports.control_plane import (
    UsageReservation,
)
from photography_coach.schemas.interaction import AccessMode, AnalysisAccess
from photography_coach.security import hash_secret


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PolicyDefaults:
    """Seed values used when the access policy row does not exist yet."""

    mode: AccessMode
    per_source_hour_limit: int | None
    global_daily_limit: int | None
    concurrent_analysis_limit: int


class SqlUsageAuthorizer:
    """Atomically reserve, consume, or release one analysis use."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        reservation_ttl_minutes: int,
        policy_defaults: PolicyDefaults,
    ) -> None:
        self._session = session
        self._reservation_ttl_minutes = reservation_ttl_minutes
        self._policy_defaults = policy_defaults

    async def reserve(
        self,
        *,
        analysis_id,
        access_code: str | None,
        idempotency_key: str,
    ) -> UsageReservation:
        """Reserve one use or raise a public access/quota application error."""
        now = utc_now()
        policy = await self.get_or_create_policy()
        mode = AccessMode(policy.mode)
        if mode is AccessMode.CLOSED:
            raise AnalysisClosedError()

        code_row = await self._require_code(access_code, mode, now)
        idempotency_hash = hash_secret(idempotency_key)
        # Advisory replay check; the unique constraint below still catches a
        # concurrent request that used the same key.
        existing = await self._session.scalar(
            select(UsageReservationRow).where(
                UsageReservationRow.idempotency_hash == idempotency_hash
            )
        )
        if existing is not None:
            return self._replay_or_conflict(existing, code_row, mode)

        await self._enforce_global_limits(policy, now)

        reservation_id = uuid4()
        expires_at = now + timedelta(minutes=self._reservation_ttl_minutes)
        remaining: int | None = None
        try:
            await self._session.commit()
            async with self._session.begin():
                if code_row is not None:
                    result = await self._session.execute(
                        update(AccessCode)
                        .where(
                            AccessCode.id == code_row.id,
                            AccessCode.status == "active",
                            or_(
                                AccessCode.expires_at.is_(None),
                                AccessCode.expires_at > now,
                            ),
                            AccessCode.uses_consumed
                            + AccessCode.uses_reserved
                            + 1
                            <= AccessCode.uses_total,
                        )
                        .values(
                            uses_reserved=AccessCode.uses_reserved + 1,
                            updated_at=now,
                        )
                    )
                    if result.rowcount != 1:
                        # Re-read outside the identity map: the cached row
                        # predates a concurrent reservation's commit.
                        fresh = await self._session.scalar(
                            select(AccessCode)
                            .where(AccessCode.id == code_row.id)
                            .execution_options(populate_existing=True)
                        )
                        raise self._reservation_failure(fresh, now)
                    await self._session.refresh(code_row)
                    if _is_exhausted(code_row):
                        code_row.status = "exhausted"
                    remaining = _remaining_uses(code_row)

                self._session.add(
                    UsageReservationRow(
                        id=reservation_id,
                        analysis_id=analysis_id,
                        access_code_id=code_row.id if code_row else None,
                        idempotency_hash=idempotency_hash,
                        status="reserved",
                        expires_at=expires_at,
                    )
                )
                if code_row is not None:
                    self._session.add(
                        AccessCodeUsageEvent(
                            reservation_id=reservation_id,
                            code_id=code_row.id,
                            analysis_id=analysis_id,
                            event_type="reserved",
                            delta=1,
                        )
                    )
        except IntegrityError:
            # A concurrent request reserved with the same idempotency key.
            existing = await self._session.scalar(
                select(UsageReservationRow).where(
                    UsageReservationRow.idempotency_hash == idempotency_hash
                )
            )
            if existing is not None:
                return self._replay_or_conflict(existing, code_row, mode)
            raise

        logger.info(
            "usage_reserved",
            extra={
                "event_data": {
                    "analysis_id": str(analysis_id),
                    "mode": mode.value,
                    "code_prefix": code_row.prefix if code_row else None,
                }
            },
        )
        return UsageReservation(
            reservation_id=reservation_id,
            analysis_id=analysis_id,
            mode=mode,
            access_code_id=code_row.id if code_row else None,
            remaining_uses_after_reservation=remaining,
            expires_at=as_aware_utc(expires_at),
        )

    async def commit(
        self,
        reservation_id,
        *,
        analysis_id,
    ) -> AnalysisAccess:
        """Convert a successful reservation into one consumed use."""
        now = utc_now()
        await self._session.commit()
        async with self._session.begin():
            row = await self._session.scalar(
                select(UsageReservationRow).where(
                    UsageReservationRow.id == reservation_id
                )
            )
            if row is None:
                raise ControlPlaneUnavailableError(
                    "The reservation was not found."
                )
            if row.analysis_id != analysis_id:
                raise ControlPlaneUnavailableError(
                    "The reservation does not match this analysis."
                )
            if row.status == "released":
                raise ControlPlaneUnavailableError(
                    "The reservation was already released."
                )

            if row.status == "reserved":
                if row.access_code_id is not None:
                    code_row = await self._session.get(
                        AccessCode, row.access_code_id
                    )
                    result = await self._session.execute(
                        update(AccessCode)
                        .where(
                            AccessCode.id == code_row.id,
                            AccessCode.uses_reserved >= 1,
                        )
                        .values(
                            uses_reserved=AccessCode.uses_reserved - 1,
                            uses_consumed=AccessCode.uses_consumed + 1,
                            updated_at=now,
                        )
                    )
                    if result.rowcount != 1:
                        raise ControlPlaneUnavailableError(
                            "The code balance cannot be confirmed."
                        )
                    await self._session.refresh(code_row)
                    if _is_exhausted(code_row):
                        code_row.status = "exhausted"
                    self._session.add(
                        AccessCodeUsageEvent(
                            reservation_id=row.id,
                            code_id=code_row.id,
                            analysis_id=row.analysis_id,
                            event_type="consumed",
                            delta=1,
                        )
                    )
                row.status = "consumed"

        logger.info(
            "usage_consumed",
            extra={"event_data": {"analysis_id": str(analysis_id)}},
        )
        row = await self._load_reservation(reservation_id, analysis_id)
        code_row = await self._code_for(row)
        return await self._access_view(code_row)

    async def release(
        self,
        reservation_id,
        *,
        analysis_id,
        reason: str,
    ) -> None:
        """Return a reservation after a model or application failure."""
        now = utc_now()
        bounded_reason = reason[:200]
        await self._session.commit()
        async with self._session.begin():
            row = await self._session.scalar(
                select(UsageReservationRow).where(
                    UsageReservationRow.id == reservation_id
                )
            )
            if row is None:
                raise ControlPlaneUnavailableError(
                    "The reservation was not found."
                )
            if row.analysis_id != analysis_id:
                raise ControlPlaneUnavailableError(
                    "The reservation does not match this analysis."
                )
            if row.status != "reserved":
                # Repeated release or release after consumption is a no-op.
                logger.warning(
                    "usage_release_no_op",
                    extra={
                        "event_data": {
                            "analysis_id": str(analysis_id),
                            "status": row.status,
                        }
                    },
                )
                return

            if row.access_code_id is not None:
                code_row = await self._session.get(AccessCode, row.access_code_id)
                result = await self._session.execute(
                    update(AccessCode)
                    .where(
                        AccessCode.id == code_row.id,
                        AccessCode.uses_reserved >= 1,
                    )
                    .values(
                        uses_reserved=AccessCode.uses_reserved - 1,
                        updated_at=now,
                    )
                )
                if result.rowcount != 1:
                    raise ControlPlaneUnavailableError(
                        "The code balance cannot be released."
                    )
                await self._session.refresh(code_row)
                if code_row.status == "exhausted" and not _is_exhausted(code_row):
                    code_row.status = "active"
                self._session.add(
                    AccessCodeUsageEvent(
                        reservation_id=row.id,
                        code_id=code_row.id,
                        analysis_id=row.analysis_id,
                        event_type="released",
                        delta=-1,
                        reason=bounded_reason,
                    )
                )
            row.status = "released"
            row.release_reason = bounded_reason

        logger.info(
            "usage_released",
            extra={
                "event_data": {
                    "analysis_id": str(analysis_id),
                    "reason": bounded_reason,
                }
            },
        )

    async def get_or_create_policy(self) -> AccessPolicyRow:
        """Return the single policy row, seeding it from defaults if absent."""
        row = await self._session.scalar(select(AccessPolicyRow).limit(1))
        if row is not None:
            return row
        row = AccessPolicyRow(
            id=1,
            mode=self._policy_defaults.mode.value,
            per_source_hour_limit=self._policy_defaults.per_source_hour_limit,
            global_daily_limit=self._policy_defaults.global_daily_limit,
            concurrent_analysis_limit=self._policy_defaults.concurrent_analysis_limit,
            updated_by="system",
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            row = await self._session.scalar(select(AccessPolicyRow).limit(1))
            if row is None:
                raise
        return row

    async def _require_code(
        self,
        access_code: str | None,
        mode: AccessMode,
        now: datetime,
    ) -> AccessCode | None:
        if mode is not AccessMode.CODE_REQUIRED:
            return None
        if not access_code:
            raise AccessCodeRequiredError()
        code_row = await self._session.scalar(
            select(AccessCode).where(
                AccessCode.code_hash == hash_secret(access_code)
            )
        )
        if code_row is None:
            raise AccessDeniedError()
        if code_row.revoked_at is not None or code_row.status == "revoked":
            raise AccessDeniedError()
        if code_row.status == "expired" or (
            code_row.expires_at is not None and code_row.expires_at <= now
        ):
            raise AccessDeniedError()
        if _is_exhausted(code_row):
            raise AccessQuotaExhaustedError()
        if code_row.status != "active":
            raise AccessDeniedError()
        return code_row

    def _replay_or_conflict(
        self,
        existing: UsageReservationRow,
        code_row: AccessCode | None,
        mode: AccessMode,
    ) -> UsageReservation:
        """Handle a duplicate idempotency key without touching balances."""
        expected_code_id = code_row.id if code_row else None
        if (
            existing.status == "reserved"
            and existing.expires_at > utc_now()
            and existing.access_code_id == expected_code_id
        ):
            return UsageReservation(
                reservation_id=existing.id,
                analysis_id=existing.analysis_id,
                mode=mode,
                access_code_id=existing.access_code_id,
                remaining_uses_after_reservation=(
                    _remaining_uses(code_row) if code_row else None
                ),
                expires_at=as_aware_utc(existing.expires_at),
            )
        raise IdempotencyConflictError()

    async def _enforce_global_limits(
        self,
        policy: AccessPolicyRow,
        now: datetime,
    ) -> None:
        live_reservations = await self._session.scalar(
            select(func.count())
            .select_from(UsageReservationRow)
            .where(
                UsageReservationRow.status == "reserved",
                UsageReservationRow.expires_at > now,
            )
        )
        if live_reservations >= policy.concurrent_analysis_limit:
            raise ConcurrencyLimitReachedError()

        if policy.global_daily_limit is not None:
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            consumed_today = await self._session.scalar(
                select(func.count())
                .select_from(UsageReservationRow)
                .where(
                    UsageReservationRow.status == "consumed",
                    UsageReservationRow.updated_at >= day_start,
                )
            )
            if consumed_today >= policy.global_daily_limit:
                raise GlobalQuotaExhaustedError()

    async def _load_reservation(
        self,
        reservation_id,
        analysis_id,
    ) -> UsageReservationRow:
        row = await self._session.scalar(
            select(UsageReservationRow).where(
                UsageReservationRow.id == reservation_id
            )
        )
        if row is None:
            raise ControlPlaneUnavailableError("The reservation was not found.")
        if row.analysis_id != analysis_id:
            raise ControlPlaneUnavailableError(
                "The reservation does not match this analysis."
            )
        return row

    async def _code_for(self, row: UsageReservationRow) -> AccessCode | None:
        if row.access_code_id is None:
            return None
        return await self._session.get(AccessCode, row.access_code_id)

    async def _access_view(self, code_row: AccessCode | None) -> AnalysisAccess:
        policy = await self.get_or_create_policy()
        mode = AccessMode(policy.mode)
        if code_row is None:
            return AnalysisAccess(mode=mode)
        return AnalysisAccess(
            mode=mode,
            remaining_uses=_remaining_uses(code_row),
        )

    @staticmethod
    def _reservation_failure(
        fresh: AccessCode | None,
        now: datetime,
    ) -> AppError:
        if fresh is None or fresh.status in ("revoked", "expired"):
            return AccessDeniedError()
        if fresh.expires_at is not None and fresh.expires_at <= now:
            return AccessDeniedError()
        if _is_exhausted(fresh):
            return AccessQuotaExhaustedError()
        return AccessDeniedError()


def _is_exhausted(code: AccessCode) -> bool:
    return code.uses_consumed + code.uses_reserved >= code.uses_total


def _remaining_uses(code: AccessCode) -> int:
    return max(code.uses_total - code.uses_consumed - code.uses_reserved, 0)
