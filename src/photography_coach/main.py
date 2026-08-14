"""FastAPI application entry point."""

import logging
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from photography_coach.api.routes import rag_router, router
from photography_coach.config import get_settings
from photography_coach.errors import AppError
from photography_coach.logging_config import configure_logging
from photography_coach.schemas.analysis import ErrorDetail, ErrorResponse


logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Response returned when the web application is running."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


def health_check() -> HealthResponse:
    """Report process health without contacting external services."""
    return HealthResponse(status="ok")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging(get_settings().log_level)
    application = FastAPI(
        title="AI Photography Coach API",
        version="0.1.0",
        description="Structured, evidence-based coaching for one uploaded photo.",
    )
    application.include_router(router)
    application.include_router(rag_router)
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
