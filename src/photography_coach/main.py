"""FastAPI application entry point."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import logging
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from photography_coach.api.admin_routes import admin_router
from photography_coach.api.public_routes import feedback_router
from photography_coach.api.routes import rag_router, router
from photography_coach.config import Settings, get_settings
from photography_coach.dependencies import (
    build_rag_analysis_service,
    policy_defaults_from_settings,
)
from photography_coach.errors import AppError
from photography_coach.logging_config import configure_logging
from photography_coach.persistence.engine import (
    create_db_engine,
    create_schema,
    session_factory_for,
)
from photography_coach.persistence.usage import SqlUsageAuthorizer
from photography_coach.schemas.analysis import ErrorDetail, ErrorResponse
from photography_coach.services.in_flight import AnalysisResponseRegistry
from photography_coach.services.rate_limiting import SourceRateLimiter
from photography_coach.services.retention import RetentionService


logger = logging.getLogger(__name__)

RETENTION_FIRST_RUN_DELAY_SECONDS = 60


class HealthResponse(BaseModel):
    """Response returned when the web application is running."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


def health_check() -> HealthResponse:
    """Report process health without contacting external services."""
    return HealthResponse(status="ok")


@asynccontextmanager
async def application_lifespan(
    application: FastAPI,
) -> AsyncIterator[None]:
    """Prepare expensive shared services once for this server process."""

    settings = application.state.settings
    application.state.rag_analysis_service = None
    application.state.control_plane_enabled = settings.control_plane_enabled
    application.state.db_engine = None
    application.state.db_session_factory = None
    application.state.source_rate_limiter = None
    application.state.login_rate_limiter = None
    application.state.analysis_registry = None
    application.state.retention_task = None
    application.state.started_at = datetime.now(UTC)
    if settings.rag_enabled:
        application.state.rag_analysis_service = (
            await build_rag_analysis_service(settings)
        )
    if settings.control_plane_enabled:
        db_engine = create_db_engine(settings.database_url)
        await create_schema(db_engine)
        application.state.db_engine = db_engine
        application.state.db_session_factory = session_factory_for(db_engine)
        application.state.source_rate_limiter = SourceRateLimiter()
        application.state.login_rate_limiter = SourceRateLimiter(
            window_seconds=60
        )
        application.state.analysis_registry = AnalysisResponseRegistry()
        application.state.retention_task = asyncio.create_task(
            _retention_loop(application),
            name="retention-cleanup",
        )
    try:
        yield
    finally:
        if application.state.retention_task is not None:
            application.state.retention_task.cancel()
            try:
                await application.state.retention_task
            except asyncio.CancelledError:
                pass
        application.state.retention_task = None
        application.state.rag_analysis_service = None
        if application.state.db_engine is not None:
            await application.state.db_engine.dispose()
        application.state.db_engine = None
        application.state.db_session_factory = None
        application.state.source_rate_limiter = None
        application.state.login_rate_limiter = None
        application.state.analysis_registry = None


async def _retention_loop(application: FastAPI) -> None:
    """Run one retention pass shortly after startup and then per interval."""
    interval_seconds = (
        application.state.settings.retention_interval_hours * 3_600
    )
    await asyncio.sleep(RETENTION_FIRST_RUN_DELAY_SECONDS)
    while True:
        await _run_retention_pass(application)
        await asyncio.sleep(interval_seconds)


async def _run_retention_pass(application: FastAPI) -> None:
    settings = application.state.settings
    session_factory = application.state.db_session_factory
    try:
        async with session_factory() as session:
            authorizer = SqlUsageAuthorizer(
                session,
                reservation_ttl_minutes=settings.reservation_ttl_minutes,
                policy_defaults=policy_defaults_from_settings(settings),
            )
            await RetentionService(session, authorizer=authorizer).run_cleanup()
    except Exception:
        logger.exception("retention_pass_failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    application_settings = settings or get_settings()
    configure_logging(application_settings.log_level)
    application = FastAPI(
        title="AI Photography Coach API",
        version="0.2.0",
        description="Structured, evidence-based coaching for one uploaded photo.",
        lifespan=application_lifespan,
    )
    application.state.settings = application_settings
    application.include_router(router)
    application.include_router(rag_router)
    application.include_router(feedback_router)
    application.include_router(admin_router)
    application.add_api_route(
        "/health",
        health_check,
        methods=["GET"],
        response_model=HealthResponse,
        tags=["system"],
    )

    @application.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        del request
        return _error_response(exc.status_code, exc.code, exc.message)

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request, exc
        return _error_response(422, "invalid_request", "The request data is invalid.")

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        del request
        logger.exception("unexpected_error", exc_info=exc)
        return _error_response(500, "internal_error", "An unexpected error occurred.")

    return application


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    payload = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=payload.model_dump())


app = create_app()
