"""Management API routes for the photography coach.

Every route except session creation requires a valid admin bearer token.
Management writes append audit events; raw access codes appear only in the
batch-creation response.
"""

import csv
from datetime import UTC, datetime
import io
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.dependencies import get_db_session
from photography_coach.errors import (
    AdminAuthenticationFailedError,
    AdminAuthenticationRequiredError,
)
from photography_coach.persistence.admin_auth import (
    AdminSubject,
    SqlAdminAuthService,
)
from photography_coach.persistence.admin_service import SqlAdminService
from photography_coach.prompts import RAG_PROMPT_VERSION
from photography_coach.retrieval_prompts import RETRIEVAL_PROMPT_VERSION
from photography_coach.schemas.admin import (
    AccessCodeBatchCreate,
    AccessCodeBatchCreated,
    AccessCodeGrant,
    AccessCodePage,
    AccessCodeRecord,
    AccessCodeRevoke,
    AccessCodeUpdate,
    AccessCodeUsageEventPage,
    AccessPolicyUpdate,
    AccessPolicyView,
    AdminSessionCreate,
    AdminSessionCreated,
    AnalysisRunDetail,
    AnalysisRunPage,
    AuditEventPage,
    OverviewResponse,
    ProblemReportPage,
    ProblemReportRecord,
    ProblemReportUpdate,
    RatingPage,
    RatingSummary,
    SystemStatus,
    SystemVersions,
)

admin_router = APIRouter(prefix="/api/admin/v1", tags=["admin"])

LOGIN_ATTEMPTS_PER_SOURCE_MINUTE = 5
DEFAULT_PAGE_SIZE = 20


async def get_admin_subject(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> AdminSubject:
    """Require one valid, unexpired admin session token."""
    token = _bearer_token(authorization)
    if token is None:
        raise AdminAuthenticationRequiredError()
    settings = request.app.state.settings
    auth = SqlAdminAuthService(
        session, session_ttl_hours=settings.admin_session_ttl_hours
    )
    return await auth.authenticate(token)


async def get_admin_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SqlAdminService:
    """Build the management service over one request-scoped session."""
    return SqlAdminService(session)


# --------------------------------------------------------------- sessions


@admin_router.post(
    "/sessions",
    response_model=AdminSessionCreated,
    status_code=201,
)
async def create_admin_session(
    body: AdminSessionCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminSessionCreated:
    """Exchange credentials for a short-lived bearer token."""
    source = request.client.host if request.client else "unknown"
    limiter = getattr(request.app.state, "source_rate_limiter", None)
    if limiter is not None and not limiter.allow(
        f"admin-login:{source}", limit=LOGIN_ATTEMPTS_PER_SOURCE_MINUTE
    ):
        # Rate-limited attempts keep the uniform 401 response.
        raise AdminAuthenticationFailedError()
    settings = request.app.state.settings
    auth = SqlAdminAuthService(
        session, session_ttl_hours=settings.admin_session_ttl_hours
    )
    try:
        created = await auth.create_session(body.username, body.password)
    except AdminAuthenticationFailedError:
        raise

    service = SqlAdminService(session)
    async with session.begin():
        service.add_audit(
            body.username, "admin.login", "admin_session", None, {}
        )
    return created


@admin_router.delete("/sessions/current", status_code=204)
async def revoke_current_session(
    request: Request,
    subject: Annotated[AdminSubject, Depends(get_admin_subject)],
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> None:
    """Revoke the token used for this request."""
    token = _bearer_token(authorization)
    settings = request.app.state.settings
    auth = SqlAdminAuthService(
        session, session_ttl_hours=settings.admin_session_ttl_hours
    )
    await auth.revoke_session(token)
    service = SqlAdminService(session)
    async with session.begin():
        service.add_audit(
            subject.username, "admin.logout", "admin_session", None, {}
        )


# -------------------------------------------------------------- overview


@admin_router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
    from_time: Annotated[datetime | None, Query(alias="from")] = None,
    to_time: Annotated[datetime | None, Query(alias="to")] = None,
    bucket: Annotated[
        str, Query(pattern="^(day|hour)$")
    ] = "day",
) -> OverviewResponse:
    """Dashboard totals and one trend series for the requested window."""
    window = service.validate_overview_window(from_time, to_time)
    return await service.overview(window, bucket=bucket)


# --------------------------------------------------------- access policy


@admin_router.get("/access-policy", response_model=AccessPolicyView)
async def get_access_policy(
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
) -> AccessPolicyView:
    """Current public access and cost-protection policy."""
    return await service.get_policy_view()


@admin_router.patch("/access-policy", response_model=AccessPolicyView)
async def patch_access_policy(
    body: AccessPolicyUpdate,
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    subject: Annotated[AdminSubject, Depends(get_admin_subject)],
) -> AccessPolicyView:
    """Update policy fields; every change is audited."""
    return await service.update_policy(body, subject.username)


# ---------------------------------------------------------- access codes


@admin_router.post(
    "/access-code-batches",
    response_model=AccessCodeBatchCreated,
    status_code=201,
)
async def create_access_code_batch(
    body: AccessCodeBatchCreate,
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    subject: Annotated[AdminSubject, Depends(get_admin_subject)],
) -> AccessCodeBatchCreated:
    """Generate codes; this is the only response that returns raw codes."""
    return await service.create_batch(body, subject.username)


@admin_router.get("/access-codes", response_model=AccessCodePage)
async def list_access_codes(
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = DEFAULT_PAGE_SIZE,
    status: Annotated[str | None, Query()] = None,
    batch_id: Annotated[UUID | None, Query()] = None,
) -> AccessCodePage:
    """Page of safe code records; raw codes are never returned here."""
    return await service.list_codes(
        page=page,
        page_size=page_size,
        status=status,
        batch_id=batch_id,
    )


@admin_router.get(
    "/access-codes/{code_id}", response_model=AccessCodeRecord
)
async def get_access_code(
    code_id: UUID,
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
) -> AccessCodeRecord:
    return await service.get_code(code_id)


@admin_router.patch(
    "/access-codes/{code_id}", response_model=AccessCodeRecord
)
async def patch_access_code(
    code_id: UUID,
    body: AccessCodeUpdate,
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    subject: Annotated[AdminSubject, Depends(get_admin_subject)],
) -> AccessCodeRecord:
    return await service.update_code(code_id, body, subject.username)


@admin_router.post(
    "/access-codes/{code_id}/grants", response_model=AccessCodeRecord
)
async def grant_access_code_uses(
    code_id: UUID,
    body: AccessCodeGrant,
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    subject: Annotated[AdminSubject, Depends(get_admin_subject)],
) -> AccessCodeRecord:
    return await service.grant_uses(code_id, body, subject.username)


@admin_router.post(
    "/access-codes/{code_id}/revoke", response_model=AccessCodeRecord
)
async def revoke_access_code(
    code_id: UUID,
    body: AccessCodeRevoke,
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    subject: Annotated[AdminSubject, Depends(get_admin_subject)],
) -> AccessCodeRecord:
    return await service.revoke_code(code_id, body, subject.username)


@admin_router.get(
    "/access-codes/{code_id}/usage-events",
    response_model=AccessCodeUsageEventPage,
)
async def list_access_code_usage_events(
    code_id: UUID,
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = DEFAULT_PAGE_SIZE,
) -> AccessCodeUsageEventPage:
    return await service.usage_events(
        code_id, page=page, page_size=page_size
    )


# -------------------------------------------------------- analysis runs


@admin_router.get("/analysis-runs", response_model=AnalysisRunPage)
async def list_analysis_runs(
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = DEFAULT_PAGE_SIZE,
    status: Annotated[str | None, Query()] = None,
    provider: Annotated[str | None, Query()] = None,
    model: Annotated[str | None, Query()] = None,
    prompt_version: Annotated[str | None, Query()] = None,
    access_code_prefix: Annotated[str | None, Query()] = None,
    error_code: Annotated[str | None, Query()] = None,
    started_from: Annotated[datetime | None, Query()] = None,
    started_to: Annotated[datetime | None, Query()] = None,
    has_down_vote: Annotated[bool | None, Query()] = None,
) -> AnalysisRunPage:
    """Filtered page of analysis runs with vote counts."""
    return await service.list_runs(
        page=page,
        page_size=page_size,
        status=status,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        access_code_prefix_filter=access_code_prefix,
        error_code=error_code,
        started_from=started_from,
        started_to=started_to,
        has_down_vote=has_down_vote,
    )


@admin_router.get(
    "/analysis-runs/{analysis_id}", response_model=AnalysisRunDetail
)
async def get_analysis_run(
    analysis_id: UUID,
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
) -> AnalysisRunDetail:
    return await service.get_run(analysis_id)


# -------------------------------------------------------------- ratings


@admin_router.get("/ratings/summary", response_model=RatingSummary)
async def get_rating_summary(
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
) -> RatingSummary:
    return await service.rating_summary()


@admin_router.get("/ratings", response_model=RatingPage)
async def list_ratings(
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = DEFAULT_PAGE_SIZE,
    target: Annotated[str | None, Query()] = None,
    vote: Annotated[str | None, Query()] = None,
    reason_code: Annotated[str | None, Query()] = None,
    model: Annotated[str | None, Query()] = None,
    prompt_version: Annotated[str | None, Query()] = None,
    from_time: Annotated[datetime | None, Query(alias="from")] = None,
    to_time: Annotated[datetime | None, Query(alias="to")] = None,
) -> RatingPage:
    return await service.list_ratings(
        page=page,
        page_size=page_size,
        target=target,
        vote=vote,
        reason_code=reason_code,
        model=model,
        prompt_version=prompt_version,
        from_time=from_time,
        to_time=to_time,
    )


# ------------------------------------------------------- problem reports


@admin_router.get("/problem-reports", response_model=ProblemReportPage)
async def list_problem_reports(
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = DEFAULT_PAGE_SIZE,
    status: Annotated[str | None, Query()] = None,
    priority: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
) -> ProblemReportPage:
    return await service.list_problem_reports(
        page=page,
        page_size=page_size,
        status=status,
        priority=priority,
        category=category,
    )


@admin_router.get(
    "/problem-reports/{problem_report_id}",
    response_model=ProblemReportRecord,
)
async def get_problem_report(
    problem_report_id: UUID,
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
) -> ProblemReportRecord:
    return await service.get_problem_report(problem_report_id)


@admin_router.patch(
    "/problem-reports/{problem_report_id}",
    response_model=ProblemReportRecord,
)
async def patch_problem_report(
    problem_report_id: UUID,
    body: ProblemReportUpdate,
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    subject: Annotated[AdminSubject, Depends(get_admin_subject)],
) -> ProblemReportRecord:
    """Update triage fields; the user's original message stays untouched."""
    return await service.update_problem_report(
        problem_report_id, body, subject.username
    )


# --------------------------------------------------------------- system


@admin_router.get("/system/status", response_model=SystemStatus)
async def get_system_status(
    request: Request,
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
) -> SystemStatus:
    settings = request.app.state.settings
    policy = await service.get_policy_view()
    return SystemStatus(
        status="ok",
        application_version=request.app.version,
        started_at=request.app.state.started_at,
        access_mode=policy.mode,
        rag_enabled=settings.rag_enabled,
        knowledge_index_ready=(
            getattr(request.app.state, "rag_analysis_service", None)
            is not None
        ),
        recent_error_rate=await service.recent_error_rate(),
    )


@admin_router.get("/system/versions", response_model=SystemVersions)
async def get_system_versions(
    request: Request,
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
) -> SystemVersions:
    settings = request.app.state.settings
    source_id, source_version = await service.latest_knowledge_versions()
    return SystemVersions(
        provider=settings.model_provider,
        model=settings.model_name,
        report_prompt_version=RAG_PROMPT_VERSION,
        retrieval_prompt_version=RETRIEVAL_PROMPT_VERSION,
        knowledge_source_id=source_id,
        knowledge_source_version=source_version,
        embedding_model=settings.embedding_model,
        reranker_model=settings.rerank_model,
    )


# ---------------------------------------------------------------- audit


@admin_router.get("/audit-events", response_model=AuditEventPage)
async def list_audit_events(
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    _: Annotated[AdminSubject, Depends(get_admin_subject)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = DEFAULT_PAGE_SIZE,
    action: Annotated[str | None, Query()] = None,
    admin_subject: Annotated[str | None, Query()] = None,
) -> AuditEventPage:
    return await service.list_audit_events(
        page=page,
        page_size=page_size,
        action=action,
        admin_subject=admin_subject,
    )


# -------------------------------------------------------------- exports


@admin_router.get("/exports/analysis-runs.csv")
async def export_analysis_runs(
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    subject: Annotated[AdminSubject, Depends(get_admin_subject)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    rows = await service.export_analysis_runs()
    await _write_export_audit(
        session, service, subject, "analysis_runs", len(rows)
    )
    return _csv_response(
        "analysis-runs.csv",
        [
            "analysis_id", "api_version", "status", "started_at",
            "completed_at", "provider", "model", "prompt_version",
            "knowledge_source_id", "knowledge_source_version",
            "embedding_model", "reranker_model", "error_code",
            "latency_ms", "input_tokens", "output_tokens", "total_tokens",
            "media_type", "width", "height", "size_bytes",
            "up_votes", "down_votes",
        ],
        rows,
    )


@admin_router.get("/exports/ratings.csv")
async def export_ratings(
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    subject: Annotated[AdminSubject, Depends(get_admin_subject)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    rows = await service.export_ratings()
    await _write_export_audit(
        session, service, subject, "ratings", len(rows)
    )
    return _csv_response(
        "ratings.csv",
        [
            "rating_id", "analysis_id", "target", "vote", "reason_codes",
            "comment", "created_at", "updated_at",
        ],
        rows,
    )


@admin_router.get("/exports/problem-reports.csv")
async def export_problem_reports(
    service: Annotated[SqlAdminService, Depends(get_admin_service)],
    subject: Annotated[AdminSubject, Depends(get_admin_subject)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    rows = await service.export_problem_reports()
    await _write_export_audit(
        session, service, subject, "problem_reports", len(rows)
    )
    return _csv_response(
        "problem-reports.csv",
        [
            "problem_report_id", "analysis_id", "category", "status",
            "priority", "tags", "message", "admin_note",
            "created_at", "updated_at",
        ],
        rows,
    )


# ------------------------------------------------------------- internals


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[len("Bearer ") :].strip()
    return token or None


async def _write_export_audit(
    session: AsyncSession,
    service: SqlAdminService,
    subject: AdminSubject,
    resource: str,
    row_count: int,
) -> None:
    await session.commit()
    async with session.begin():
        service.add_audit(
            subject.username,
            "export.csv",
            resource,
            None,
            {"rows": row_count},
        )


_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _escape_csv_cell(value) -> str:
    text = "" if value is None else str(value)
    if text.startswith(_CSV_INJECTION_PREFIXES):
        return "'" + text
    return text


def _csv_response(
    filename: str,
    columns: list[str],
    rows: list[dict],
) -> StreamingResponse:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {key: _escape_csv_cell(row.get(key)) for key in columns}
        )
    date_stamp = datetime.now(UTC).date().isoformat()
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{date_stamp}-{filename}"'
            )
        },
    )
