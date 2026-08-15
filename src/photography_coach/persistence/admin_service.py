"""SQL queries and mutations backing the management API.

All management writes append an audit event in the same transaction and
never store or return raw access codes, feedback tokens, or other secrets.
Datetimes crossing the boundary are converted to timezone-aware UTC.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from uuid import UUID, uuid4

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.errors import AnalysisNotFoundError, InvalidRequestError
from photography_coach.persistence.json_text import dumps, loads
from photography_coach.persistence.models import (
    AccessCode,
    AccessCodeBatch,
    AccessCodeUsageEvent as AccessCodeUsageEventRow,
    AccessPolicyRow,
    AdminAuditEvent,
    AnalysisRun,
    DimensionRating,
    ProblemReport,
    as_aware_utc,
    utc_now,
)
from photography_coach.persistence.recording import stored_run_metadata
from photography_coach.schemas.admin import (
    AccessCodeBatchCreated,
    AccessCodeGrant,
    AccessCodePage,
    AccessCodeRecord,
    AccessCodeRevoke,
    AccessCodeStatus,
    AccessCodeUpdate,
    AccessCodeUsageEvent,
    AccessCodeUsageEventPage,
    AccessPolicyUpdate,
    AccessPolicyView,
    AnalysisRunDetail,
    AnalysisRunPage,
    AnalysisRunStatus,
    AnalysisRunSummary,
    AuditEvent,
    AuditEventPage,
    GeneratedAccessCode,
    MetricBucket,
    OverviewMetrics,
    OverviewResponse,
    PageInfo,
    ProblemPriority,
    ProblemReportPage,
    ProblemReportRecord,
    ProblemReportUpdate,
    RatingPage,
    RatingRecord,
    RatingSummary,
    RatingTargetSummary,
    UsageEventStatus,
)
from photography_coach.schemas.interaction import (
    AccessMode,
    ProblemReportStatus,
    RatingReasonCode,
    RatingTarget,
    RatingVote,
)
from photography_coach.schemas.report import PhotographyReport
from photography_coach.security import (
    access_code_prefix,
    generate_access_code,
    hash_secret,
)

logger = logging.getLogger(__name__)

RATING_TARGETS = [target.value for target in RatingTarget]
MAX_TIME_RANGE_DAYS = 366
DEFAULT_OVERVIEW_DAYS = 30


@dataclass(frozen=True, slots=True)
class OverviewWindow:
    """Validated dashboard time window with UTC-naive bounds."""

    started_at: datetime
    ended_at: datetime

    @property
    def seconds(self) -> float:
        return (self.ended_at - self.started_at).total_seconds()


class SqlAdminService:
    """Every management API operation, shared by the admin routes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---------------------------------------------------------------- policy

    async def get_policy_view(self) -> AccessPolicyView:
        row = await self._policy_row()
        return AccessPolicyView(
            mode=AccessMode(row.mode),
            per_source_hour_limit=row.per_source_hour_limit,
            global_daily_limit=row.global_daily_limit,
            concurrent_analysis_limit=row.concurrent_analysis_limit,
            updated_at=as_aware_utc(row.updated_at),
        )

    async def update_policy(
        self,
        update_model: AccessPolicyUpdate,
        admin_subject: str,
    ) -> AccessPolicyView:
        row = await self._policy_row()
        now = utc_now()
        await self._session.commit()
        async with self._session.begin():
            changes: dict[str, str | int | None] = {}
            if "mode" in update_model.model_fields_set:
                row.mode = update_model.mode.value
                changes["mode"] = update_model.mode.value
            if "per_source_hour_limit" in update_model.model_fields_set:
                row.per_source_hour_limit = update_model.per_source_hour_limit
                changes["per_source_hour_limit"] = (
                    update_model.per_source_hour_limit
                )
            if "global_daily_limit" in update_model.model_fields_set:
                row.global_daily_limit = update_model.global_daily_limit
                changes["global_daily_limit"] = update_model.global_daily_limit
            if "concurrent_analysis_limit" in update_model.model_fields_set:
                row.concurrent_analysis_limit = (
                    update_model.concurrent_analysis_limit
                )
                changes["concurrent_analysis_limit"] = (
                    update_model.concurrent_analysis_limit
                )
            row.updated_by = admin_subject
            row.updated_at = now
            self._add_audit(
                admin_subject,
                "access_policy.updated",
                "access_policy",
                None,
                changes,
            )
        await self._session.refresh(row)
        return AccessPolicyView(
            mode=AccessMode(row.mode),
            per_source_hour_limit=row.per_source_hour_limit,
            global_daily_limit=row.global_daily_limit,
            concurrent_analysis_limit=row.concurrent_analysis_limit,
            updated_at=as_aware_utc(row.updated_at),
        )

    # --------------------------------------------------------- access codes

    async def create_batch(self, create_model, admin_subject: str):
        now = utc_now()
        if (
            create_model.expires_at is not None
            and _naive(create_model.expires_at) <= now
        ):
            raise InvalidRequestError(
                "The batch expiry must be in the future."
            )
        expires_at = (
            _naive(create_model.expires_at)
            if create_model.expires_at is not None
            else None
        )
        batch_id = uuid4()
        raw_codes: list[str] = []
        seen_hashes: set[str] = set()
        while len(raw_codes) < create_model.quantity:
            candidate = generate_access_code()
            digest = hash_secret(candidate)
            if digest in seen_hashes:
                continue
            existing = await self._session.scalar(
                select(AccessCode).where(AccessCode.code_hash == digest)
            )
            if existing is not None:
                continue
            seen_hashes.add(digest)
            raw_codes.append(candidate)

        await self._session.commit()
        async with self._session.begin():
            batch = AccessCodeBatch(
                id=batch_id,
                label=create_model.label,
                quantity=create_model.quantity,
                uses_per_code=create_model.uses_per_code,
                expires_at=expires_at,
                created_by=admin_subject,
            )
            self._session.add(batch)
            generated: list[tuple[UUID, str, str]] = []
            for raw in raw_codes:
                code = AccessCode(
                    batch_id=batch_id,
                    code_hash=hash_secret(raw),
                    prefix=access_code_prefix(raw),
                    uses_total=create_model.uses_per_code,
                    status="active",
                    expires_at=expires_at,
                )
                self._session.add(code)
                await self._session.flush()
                generated.append((code.id, raw, access_code_prefix(raw)))
                self._session.add(
                    AccessCodeUsageEventRow(
                        code_id=code.id,
                        event_type="granted",
                        delta=create_model.uses_per_code,
                        reason="batch_created",
                    )
                )
            self._add_audit(
                admin_subject,
                "access_codes.batch_created",
                "access_code_batch",
                str(batch_id),
                {
                    "quantity": create_model.quantity,
                    "uses_per_code": create_model.uses_per_code,
                },
            )
        return AccessCodeBatchCreated(
            batch_id=batch_id,
            created_at=as_aware_utc(now),
            codes=[
                GeneratedAccessCode(
                    code_id=code_id,
                    code=raw,
                    prefix=prefix,
                    uses_total=create_model.uses_per_code,
                    expires_at=(
                        as_aware_utc(expires_at) if expires_at else None
                    ),
                )
                for code_id, raw, prefix in generated
            ],
        )

    async def list_codes(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        batch_id: UUID | None,
    ):
        query = select(AccessCode)
        if status == AccessCodeStatus.EXPIRED.value:
            query = query.where(
                AccessCode.expires_at.is_not(None),
                AccessCode.expires_at <= utc_now(),
                AccessCode.revoked_at.is_(None),
            )
        elif status == AccessCodeStatus.REVOKED.value:
            query = query.where(AccessCode.revoked_at.is_not(None))
        elif status is not None:
            query = query.where(AccessCode.status == status)
        if batch_id is not None:
            query = query.where(AccessCode.batch_id == batch_id)
        total = await self._count(query)
        rows = (
            await self._session.scalars(
                query.order_by(AccessCode.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return AccessCodePage(
            items=[self._code_record(row) for row in rows],
            page=_page_info(page, page_size, total),
        )

    async def get_code(self, code_id: UUID) -> AccessCodeRecord:
        row = await self._require_code_row(code_id)
        return self._code_record(row)

    async def update_code(self, code_id: UUID, update_model: AccessCodeUpdate, admin_subject: str):
        row = await self._require_code_row(code_id)
        now = utc_now()
        if "expires_at" in update_model.model_fields_set:
            if (
                update_model.expires_at is not None
                and _naive(update_model.expires_at) <= now
            ):
                raise InvalidRequestError(
                    "The new expiry must be in the future."
                )
        await self._session.commit()
        async with self._session.begin():
            changes: dict[str, str | int | None] = {}
            if "label" in update_model.model_fields_set:
                row.label = update_model.label
                changes["label"] = update_model.label
            if "expires_at" in update_model.model_fields_set:
                row.expires_at = (
                    _naive(update_model.expires_at)
                    if update_model.expires_at is not None
                    else None
                )
                changes["expires_at"] = (
                    as_aware_utc(row.expires_at).isoformat()
                    if row.expires_at
                    else None
                )
            row.updated_at = now
            self._add_audit(
                admin_subject,
                "access_codes.updated",
                "access_code",
                str(code_id),
                changes,
            )
        await self._session.refresh(row)
        return self._code_record(row)

    async def grant_uses(self, code_id: UUID, grant: AccessCodeGrant, admin_subject: str):
        row = await self._require_code_row(code_id)
        if row.revoked_at is not None:
            raise InvalidRequestError(
                "Revoked codes cannot receive additional uses."
            )
        now = utc_now()
        await self._session.commit()
        async with self._session.begin():
            row.uses_total += grant.additional_uses
            if (
                row.status == "exhausted"
                and row.uses_consumed + row.uses_reserved < row.uses_total
            ):
                row.status = "active"
            row.updated_at = now
            self._session.add(
                AccessCodeUsageEventRow(
                    code_id=code_id,
                    event_type="granted",
                    delta=grant.additional_uses,
                    reason=grant.reason,
                )
            )
            self._add_audit(
                admin_subject,
                "access_codes.granted",
                "access_code",
                str(code_id),
                {"additional_uses": grant.additional_uses},
            )
        await self._session.refresh(row)
        return self._code_record(row)

    async def revoke_code(self, code_id: UUID, revoke: AccessCodeRevoke, admin_subject: str):
        row = await self._require_code_row(code_id)
        if row.revoked_at is not None:
            return self._code_record(row)
        now = utc_now()
        await self._session.commit()
        async with self._session.begin():
            remaining = max(
                row.uses_total - row.uses_consumed - row.uses_reserved, 0
            )
            row.status = "revoked"
            row.revoked_at = now
            row.updated_at = now
            self._session.add(
                AccessCodeUsageEventRow(
                    code_id=code_id,
                    event_type="revoked",
                    delta=-remaining,
                    reason=revoke.reason,
                )
            )
            self._add_audit(
                admin_subject,
                "access_codes.revoked",
                "access_code",
                str(code_id),
                {"remaining_uses": remaining},
            )
        await self._session.refresh(row)
        return self._code_record(row)

    async def usage_events(self, code_id: UUID, *, page: int, page_size: int):
        await self._require_code_row(code_id)
        base = select(AccessCodeUsageEventRow).where(
            AccessCodeUsageEventRow.code_id == code_id,
            AccessCodeUsageEventRow.event_type.in_(
                ("reserved", "consumed", "released")
            ),
            AccessCodeUsageEventRow.analysis_id.is_not(None),
        )
        total = await self._count(base)
        rows = (
            await self._session.scalars(
                base.order_by(AccessCodeUsageEventRow.occurred_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return AccessCodeUsageEventPage(
            items=[
                _usage_event_record(row) for row in rows
            ],
            page=_page_info(page, page_size, total),
        )

    # -------------------------------------------------------- analysis runs

    async def list_runs(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        provider: str | None,
        model: str | None,
        prompt_version: str | None,
        access_code_prefix_filter: str | None,
        error_code: str | None,
        started_from: datetime | None,
        started_to: datetime | None,
        has_down_vote: bool | None,
    ):
        query = select(AnalysisRun)
        if status is not None:
            query = query.where(AnalysisRun.status == status)
        if provider is not None:
            query = query.where(AnalysisRun.provider == provider)
        if model is not None:
            query = query.where(AnalysisRun.model == model)
        if prompt_version is not None:
            query = query.where(AnalysisRun.prompt_version == prompt_version)
        if error_code is not None:
            query = query.where(AnalysisRun.error_code == error_code)
        if started_from is not None:
            query = query.where(AnalysisRun.started_at >= _naive(started_from))
        if started_to is not None:
            query = query.where(AnalysisRun.started_at < _naive(started_to))
        if access_code_prefix_filter is not None:
            query = query.where(
                AnalysisRun.access_code_id.in_(
                    select(AccessCode.id).where(
                        AccessCode.prefix == access_code_prefix_filter
                    )
                )
            )
        if has_down_vote is True:
            query = query.where(
                AnalysisRun.analysis_id.in_(
                    select(DimensionRating.analysis_id).where(
                        DimensionRating.vote == RatingVote.DOWN.value
                    )
                )
            )

        total = await self._count(query)
        rows = (
            await self._session.scalars(
                query.order_by(AnalysisRun.started_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        items = []
        for row in rows:
            up, down = await self._vote_counts(row.analysis_id)
            items.append(await self._run_summary(row, up, down))
        return AnalysisRunPage(
            items=items,
            page=_page_info(page, page_size, total),
        )

    async def get_run(self, analysis_id: UUID) -> AnalysisRunDetail:
        row = await self._session.get(AnalysisRun, analysis_id)
        if row is None:
            raise AnalysisNotFoundError()
        up, down = await self._vote_counts(analysis_id)
        summary = await self._run_summary(row, up, down)
        return AnalysisRunDetail(
            **summary.model_dump(),
            shooting_intent=row.shooting_intent,
            metadata=stored_run_metadata(row),
            report=(
                PhotographyReport.model_validate_json(row.report_json)
                if row.report_json
                else None
            ),
            report_retained_until=(
                as_aware_utc(row.report_retained_until)
                if row.report_retained_until
                else None
            ),
            sanitized_diagnostic=row.sanitized_diagnostic,
        )

    async def _run_summary(
        self,
        row: AnalysisRun,
        up: int,
        down: int,
    ) -> AnalysisRunSummary:
        prefix = None
        if row.access_code_id is not None:
            code = await self._session.get(AccessCode, row.access_code_id)
            prefix = code.prefix if code is not None else None
        return AnalysisRunSummary(
            analysis_id=row.analysis_id,
            status=AnalysisRunStatus(row.status),
            api_version=row.api_version,
            started_at=as_aware_utc(row.started_at),
            completed_at=(
                as_aware_utc(row.completed_at) if row.completed_at else None
            ),
            access_code_prefix=prefix,
            provider=row.provider,
            model=row.model,
            prompt_version=row.prompt_version,
            latency_ms=row.latency_ms,
            total_tokens=row.total_tokens,
            error_code=row.error_code,
            up_votes=up,
            down_votes=down,
        )

    # -------------------------------------------------------------- ratings

    async def rating_summary(self) -> RatingSummary:
        rows = (
            await self._session.execute(
                select(
                    DimensionRating.target,
                    func.sum(
                        case((DimensionRating.vote == "up", 1), else_=0)
                    ),
                    func.sum(
                        case((DimensionRating.vote == "down", 1), else_=0)
                    ),
                ).group_by(DimensionRating.target)
            )
        ).all()
        counts = {target: (up or 0, down or 0) for target, up, down in rows}
        return RatingSummary(
            items=[
                RatingTargetSummary(
                    target=RatingTarget(target),
                    up_votes=counts.get(target, (0, 0))[0],
                    down_votes=counts.get(target, (0, 0))[1],
                )
                for target in RATING_TARGETS
            ]
        )

    async def list_ratings(
        self,
        *,
        page: int,
        page_size: int,
        target: str | None,
        vote: str | None,
        reason_code: str | None,
        model: str | None,
        prompt_version: str | None,
        from_time: datetime | None,
        to_time: datetime | None,
    ):
        query = select(DimensionRating)
        if target is not None:
            query = query.where(DimensionRating.target == target)
        if vote is not None:
            query = query.where(DimensionRating.vote == vote)
        if reason_code is not None:
            query = query.where(
                DimensionRating.reason_codes_json.like(f'%"{reason_code}"%')
            )
        if model is not None or prompt_version is not None:
            run_conditions = []
            if model is not None:
                run_conditions.append(AnalysisRun.model == model)
            if prompt_version is not None:
                run_conditions.append(AnalysisRun.prompt_version == prompt_version)
            query = query.where(
                DimensionRating.analysis_id.in_(
                    select(AnalysisRun.analysis_id).where(*run_conditions)
                )
            )
        if from_time is not None:
            query = query.where(DimensionRating.created_at >= _naive(from_time))
        if to_time is not None:
            query = query.where(DimensionRating.created_at < _naive(to_time))

        total = await self._count(query)
        rows = (
            await self._session.scalars(
                query.order_by(DimensionRating.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return RatingPage(
            items=[self._rating_record(row) for row in rows],
            page=_page_info(page, page_size, total),
        )

    def _rating_record(self, row: DimensionRating) -> RatingRecord:
        return RatingRecord(
            rating_id=row.id,
            analysis_id=row.analysis_id,
            target=RatingTarget(row.target),
            vote=RatingVote(row.vote),
            reason_codes=[
                RatingReasonCode(code)
                for code in loads(row.reason_codes_json, [])
            ],
            comment=row.comment,
            created_at=as_aware_utc(row.created_at),
            updated_at=as_aware_utc(row.updated_at),
        )

    # ------------------------------------------------------- problem reports

    async def list_problem_reports(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        priority: str | None,
        category: str | None,
    ):
        query = select(ProblemReport)
        if status is not None:
            query = query.where(ProblemReport.status == status)
        if priority is not None:
            query = query.where(ProblemReport.priority == priority)
        if category is not None:
            query = query.where(ProblemReport.category == category)
        total = await self._count(query)
        rows = (
            await self._session.scalars(
                query.order_by(ProblemReport.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return ProblemReportPage(
            items=[self._problem_record(row) for row in rows],
            page=_page_info(page, page_size, total),
        )

    async def get_problem_report(self, report_id: UUID):
        row = await self._session.get(ProblemReport, report_id)
        if row is None:
            raise AnalysisNotFoundError()
        return self._problem_record(row)

    async def update_problem_report(
        self,
        report_id: UUID,
        update_model: ProblemReportUpdate,
        admin_subject: str,
    ):
        row = await self._session.get(ProblemReport, report_id)
        if row is None:
            raise AnalysisNotFoundError()
        await self._session.commit()
        async with self._session.begin():
            changes: dict[str, str | int | None] = {}
            if "status" in update_model.model_fields_set:
                row.status = update_model.status.value
                changes["status"] = update_model.status.value
            if "priority" in update_model.model_fields_set:
                row.priority = update_model.priority.value
                changes["priority"] = update_model.priority.value
            if "tags" in update_model.model_fields_set:
                row.tags_json = dumps(update_model.tags or [])
                changes["tags"] = ",".join(update_model.tags or [])
            if "admin_note" in update_model.model_fields_set:
                row.admin_note = update_model.admin_note
                changes["admin_note_set"] = update_model.admin_note is not None
            row.updated_at = utc_now()
            self._add_audit(
                admin_subject,
                "problem_reports.updated",
                "problem_report",
                str(report_id),
                changes,
            )
        await self._session.refresh(row)
        return self._problem_record(row)

    def _problem_record(self, row: ProblemReport) -> ProblemReportRecord:
        return ProblemReportRecord(
            problem_report_id=row.id,
            analysis_id=row.analysis_id,
            category=row.category,
            message=row.message,
            status=ProblemReportStatus(row.status),
            priority=ProblemPriority(row.priority),
            tags=loads(row.tags_json, []),
            admin_note=row.admin_note,
            created_at=as_aware_utc(row.created_at),
            updated_at=as_aware_utc(row.updated_at),
        )

    # -------------------------------------------------------------- overview

    def validate_overview_window(
        self,
        from_time: datetime | None,
        to_time: datetime | None,
    ) -> OverviewWindow:
        ended = _naive(to_time) if to_time is not None else utc_now()
        if from_time is None:
            started = ended - timedelta(days=DEFAULT_OVERVIEW_DAYS)
        else:
            started = _naive(from_time)
        if started >= ended:
            raise InvalidRequestError(
                "The overview start must be before the end."
            )
        if (ended - started) > timedelta(days=MAX_TIME_RANGE_DAYS):
            raise InvalidRequestError(
                "The overview time range cannot exceed 366 days."
            )
        return OverviewWindow(started_at=started, ended_at=ended)

    async def overview(self, window: OverviewWindow, *, bucket: str):
        totals_row = (
            await self._session.execute(
                select(
                    func.count(),
                    func.coalesce(
                        func.sum(
                            case(
                                (AnalysisRun.status == "succeeded", 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (AnalysisRun.status == "failed", 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (AnalysisRun.error_code == "model_timeout", 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(func.sum(AnalysisRun.total_tokens), 0),
                    func.avg(AnalysisRun.latency_ms),
                ).where(
                    AnalysisRun.started_at >= window.started_at,
                    AnalysisRun.started_at < window.ended_at,
                )
            )
        ).one()
        (
            total,
            succeeded,
            failed,
            timeouts,
            tokens,
            average_latency,
        ) = totals_row

        vote_row = (
            await self._session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            case((DimensionRating.vote == "up", 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case((DimensionRating.vote == "down", 1), else_=0)
                        ),
                        0,
                    ),
                )
                .join(
                    AnalysisRun,
                    AnalysisRun.analysis_id == DimensionRating.analysis_id,
                )
                .where(
                    AnalysisRun.started_at >= window.started_at,
                    AnalysisRun.started_at < window.ended_at,
                )
            )
        ).one()
        up_votes, down_votes = vote_row

        open_reports = await self._session.scalar(
            select(func.count()).select_from(ProblemReport).where(
                ProblemReport.status.in_(("new", "in_progress"))
            )
        )

        series = await self._series(window, bucket)
        return OverviewResponse(
            totals=OverviewMetrics(
                period_started_at=as_aware_utc(window.started_at),
                period_ended_at=as_aware_utc(window.ended_at),
                analyses_total=total,
                analyses_succeeded=succeeded,
                analyses_failed=failed,
                model_timeouts=timeouts,
                total_tokens=tokens,
                average_latency_ms=(
                    round(average_latency, 2)
                    if average_latency is not None
                    else None
                ),
                up_votes=up_votes,
                down_votes=down_votes,
                open_problem_reports=open_reports,
            ),
            series=series,
        )

    async def _series(self, window: OverviewWindow, bucket: str) -> list[MetricBucket]:
        if bucket == "day":
            format_spec = "%Y-%m-%d"
            trunc_unit = "day"
            step = timedelta(days=1)
        elif bucket == "hour":
            format_spec = "%Y-%m-%d %H:00"
            trunc_unit = "hour"
            step = timedelta(hours=1)
        else:
            raise InvalidRequestError("bucket must be 'day' or 'hour'.")

        # Bucketing is dialect-specific: strftime on SQLite, date_trunc +
        # to_char on PostgreSQL. Both produce the same string labels.
        dialect = self._session.get_bind().dialect.name
        if dialect == "postgresql":
            expression = func.to_char(
                func.date_trunc(trunc_unit, AnalysisRun.started_at),
                format_spec.replace("%H:00", "HH24:00"),
            )
        else:
            expression = func.strftime(format_spec, AnalysisRun.started_at)
        rows = (
            await self._session.execute(
                select(
                    expression,
                    func.count(),
                    func.coalesce(
                        func.sum(
                            case(
                                (AnalysisRun.status == "succeeded", 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (AnalysisRun.status == "failed", 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(func.sum(AnalysisRun.total_tokens), 0),
                )
                .where(
                    AnalysisRun.started_at >= window.started_at,
                    AnalysisRun.started_at < window.ended_at,
                )
                .group_by(expression)
            )
        ).all()
        by_bucket = {
            key: (total, succeeded, failed, tokens)
            for key, total, succeeded, failed, tokens in rows
        }

        vote_rows = (
            await self._session.execute(
                select(
                    expression.label("bucket"),
                    func.coalesce(
                        func.sum(
                            case((DimensionRating.vote == "up", 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case((DimensionRating.vote == "down", 1), else_=0)
                        ),
                        0,
                    ),
                )
                .join(
                    AnalysisRun,
                    AnalysisRun.analysis_id == DimensionRating.analysis_id,
                )
                .where(
                    AnalysisRun.started_at >= window.started_at,
                    AnalysisRun.started_at < window.ended_at,
                )
                .group_by("bucket")
            )
        ).all()
        votes_by_bucket = {
            key: (up, down) for key, up, down in vote_rows
        }

        buckets: list[MetricBucket] = []
        current = window.started_at
        while current < window.ended_at:
            key = current.strftime(format_spec)
            total, succeeded, failed, tokens = by_bucket.get(
                key, (0, 0, 0, 0)
            )
            up, down = votes_by_bucket.get(key, (0, 0))
            buckets.append(
                MetricBucket(
                    bucket_started_at=as_aware_utc(current),
                    analyses_total=total,
                    analyses_succeeded=succeeded,
                    analyses_failed=failed,
                    total_tokens=tokens,
                    up_votes=up,
                    down_votes=down,
                )
            )
            current += step
        return buckets

    # -------------------------------------------------------------- audit

    async def list_audit_events(
        self,
        *,
        page: int,
        page_size: int,
        action: str | None,
        admin_subject: str | None,
    ):
        query = select(AdminAuditEvent)
        if action is not None:
            query = query.where(AdminAuditEvent.action == action)
        if admin_subject is not None:
            query = query.where(
                AdminAuditEvent.admin_subject == admin_subject
            )
        total = await self._count(query)
        rows = (
            await self._session.scalars(
                query.order_by(AdminAuditEvent.occurred_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return AuditEventPage(
            items=[
                AuditEvent(
                    audit_event_id=row.id,
                    admin_subject=row.admin_subject,
                    action=row.action,
                    resource_type=row.resource_type,
                    resource_id=row.resource_id,
                    occurred_at=as_aware_utc(row.occurred_at),
                    details=loads(row.details_json, {}),
                )
                for row in rows
            ],
            page=_page_info(page, page_size, total),
        )

    def add_audit(
        self,
        admin_subject: str,
        action: str,
        resource_type: str,
        resource_id: str | None,
        details: dict[str, str | int | bool | None] | None = None,
    ) -> None:
        """Append one audit event in the current transaction."""
        self._add_audit(
            admin_subject, action, resource_type, resource_id, details or {}
        )

    def _add_audit(
        self,
        admin_subject: str,
        action: str,
        resource_type: str,
        resource_id: str | None,
        details: dict[str, str | int | bool | None],
    ) -> None:
        self._session.add(
            AdminAuditEvent(
                admin_subject=admin_subject,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details_json=dumps(details),
            )
        )

    # --------------------------------------------------------------- system

    async def recent_error_rate(self, window_hours: int = 24) -> float:
        """Share of failed analyses over the recent window, 0..1."""
        started_after = utc_now() - timedelta(hours=window_hours)
        total = await self._session.scalar(
            select(func.count())
            .select_from(AnalysisRun)
            .where(AnalysisRun.started_at >= started_after)
        )
        if not total:
            return 0.0
        failed = await self._session.scalar(
            select(func.count())
            .select_from(AnalysisRun)
            .where(
                AnalysisRun.started_at >= started_after,
                AnalysisRun.status == "failed",
            )
        )
        return round((failed or 0) / total, 4)

    async def latest_knowledge_versions(self) -> tuple[str | None, str | None]:
        """Knowledge source identifiers from the most recent RAG run."""
        row = await self._session.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.knowledge_source_id.is_not(None))
            .order_by(AnalysisRun.started_at.desc())
            .limit(1)
        )
        if row is None:
            return None, None
        return row.knowledge_source_id, row.knowledge_source_version

    # -------------------------------------------------------------- exports

    async def export_analysis_runs(self) -> list[dict]:
        rows = (
            await self._session.scalars(
                select(AnalysisRun).order_by(AnalysisRun.started_at.asc())
            )
        ).all()
        exported = []
        for row in rows:
            up, down = await self._vote_counts(row.analysis_id)
            exported.append(
                {
                    "analysis_id": str(row.analysis_id),
                    "api_version": row.api_version,
                    "status": row.status,
                    "started_at": (
                        as_aware_utc(row.started_at).isoformat()
                    ),
                    "completed_at": (
                        as_aware_utc(row.completed_at).isoformat()
                        if row.completed_at
                        else ""
                    ),
                    "provider": row.provider or "",
                    "model": row.model or "",
                    "prompt_version": row.prompt_version or "",
                    "knowledge_source_id": row.knowledge_source_id or "",
                    "knowledge_source_version": (
                        row.knowledge_source_version or ""
                    ),
                    "embedding_model": row.embedding_model or "",
                    "reranker_model": row.reranker_model or "",
                    "error_code": row.error_code or "",
                    "latency_ms": row.latency_ms or "",
                    "input_tokens": row.input_tokens or "",
                    "output_tokens": row.output_tokens or "",
                    "total_tokens": row.total_tokens or "",
                    "media_type": row.media_type,
                    "width": row.width,
                    "height": row.height,
                    "size_bytes": row.size_bytes,
                    "up_votes": up,
                    "down_votes": down,
                }
            )
        return exported

    async def export_ratings(self) -> list[dict]:
        rows = (
            await self._session.scalars(
                select(DimensionRating).order_by(
                    DimensionRating.created_at.asc()
                )
            )
        ).all()
        return [
            {
                "rating_id": str(row.id),
                "analysis_id": str(row.analysis_id),
                "target": row.target,
                "vote": row.vote,
                "reason_codes": ",".join(
                    loads(row.reason_codes_json, [])
                ),
                "comment": row.comment or "",
                "created_at": as_aware_utc(row.created_at).isoformat(),
                "updated_at": as_aware_utc(row.updated_at).isoformat(),
            }
            for row in rows
        ]

    async def export_problem_reports(self) -> list[dict]:
        rows = (
            await self._session.scalars(
                select(ProblemReport).order_by(ProblemReport.created_at.asc())
            )
        ).all()
        return [
            {
                "problem_report_id": str(row.id),
                "analysis_id": str(row.analysis_id) if row.analysis_id else "",
                "category": row.category,
                "status": row.status,
                "priority": row.priority,
                "tags": ",".join(loads(row.tags_json, [])),
                "message": row.message,
                "admin_note": row.admin_note or "",
                "created_at": as_aware_utc(row.created_at).isoformat(),
                "updated_at": as_aware_utc(row.updated_at).isoformat(),
            }
            for row in rows
        ]

    # ------------------------------------------------------------- internal

    async def _policy_row(self) -> AccessPolicyRow:
        row = await self._session.scalar(select(AccessPolicyRow).limit(1))
        if row is None:
            from photography_coach.config import get_settings

            settings = get_settings()
            row = AccessPolicyRow(
                id=1,
                mode=settings.default_access_mode,
                per_source_hour_limit=settings.default_per_source_hour_limit,
                global_daily_limit=settings.default_global_daily_limit,
                concurrent_analysis_limit=(
                    settings.default_concurrent_analysis_limit
                ),
                updated_by="system",
            )
            self._session.add(row)
            try:
                await self._session.commit()
            except IntegrityError:
                await self._session.rollback()
                row = await self._session.scalar(
                    select(AccessPolicyRow).limit(1)
                )
                if row is None:
                    raise
        return row

    async def _require_code_row(self, code_id: UUID) -> AccessCode:
        row = await self._session.get(AccessCode, code_id)
        if row is None:
            raise AnalysisNotFoundError()
        return row

    async def _vote_counts(self, analysis_id: UUID) -> tuple[int, int]:
        rows = (
            await self._session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            case((DimensionRating.vote == "up", 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case((DimensionRating.vote == "down", 1), else_=0)
                        ),
                        0,
                    ),
                ).where(DimensionRating.analysis_id == analysis_id)
            )
        ).one()
        return rows[0], rows[1]

    async def _count(self, query) -> int:
        count_query = select(func.count()).select_from(
            query.order_by(None).subquery()
        )
        return await self._session.scalar(count_query) or 0

    def _code_record(self, row: AccessCode) -> AccessCodeRecord:
        status = _effective_code_status(row, utc_now())
        return AccessCodeRecord(
            code_id=row.id,
            batch_id=row.batch_id,
            prefix=row.prefix,
            label=row.label,
            status=AccessCodeStatus(status),
            uses_total=row.uses_total,
            uses_consumed=row.uses_consumed,
            uses_reserved=row.uses_reserved,
            expires_at=(
                as_aware_utc(row.expires_at) if row.expires_at else None
            ),
            created_at=as_aware_utc(row.created_at),
            updated_at=as_aware_utc(row.updated_at),
        )


def _effective_code_status(row: AccessCode, now: datetime) -> str:
    if row.revoked_at is not None or row.status == "revoked":
        return AccessCodeStatus.REVOKED.value
    if row.expires_at is not None and row.expires_at <= now:
        return AccessCodeStatus.EXPIRED.value
    if row.uses_consumed + row.uses_reserved >= row.uses_total:
        return AccessCodeStatus.EXHAUSTED.value
    return AccessCodeStatus.ACTIVE.value


def _usage_event_record(row: AccessCodeUsageEventRow) -> AccessCodeUsageEvent:
    return AccessCodeUsageEvent(
        usage_event_id=row.id,
        code_id=row.code_id,
        analysis_id=row.analysis_id,
        status=UsageEventStatus(row.event_type),
        occurred_at=as_aware_utc(row.occurred_at),
        release_reason=row.release_reason,
    )


def _page_info(page: int, page_size: int, total: int) -> PageInfo:
    return PageInfo(
        page=page,
        page_size=page_size,
        total_items=total,
        total_pages=(total + page_size - 1) // page_size,
    )


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value
