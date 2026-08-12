"""Versioned HTTP endpoints for the photography coach."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from photography_coach.dependencies import get_analysis_service
from photography_coach.errors import InvalidImageError, PayloadTooLargeError
from photography_coach.image_validation import (
    MAX_IMAGE_BYTES,
    ImageTooLargeError,
    ImageValidationError,
    validate_image,
)
from photography_coach.schemas.analysis import AnalysisResponse, ErrorResponse
from photography_coach.services.analysis import AnalysisService


router = APIRouter(prefix="/api/v1", tags=["analysis"])

ANALYSIS_ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "Invalid image content."},
    413: {"model": ErrorResponse, "description": "Image byte limit exceeded."},
    422: {"model": ErrorResponse, "description": "Invalid multipart request."},
    429: {"model": ErrorResponse, "description": "Model provider rate limited."},
    502: {"model": ErrorResponse, "description": "Invalid model response."},
    503: {"model": ErrorResponse, "description": "Model provider unavailable."},
    504: {"model": ErrorResponse, "description": "Model analysis timed out."},
}


@router.post(
    "/analyze",
    response_model=AnalysisResponse,
    responses=ANALYSIS_ERROR_RESPONSES,
)
async def analyze_photo(
    photo: Annotated[
        UploadFile,
        File(description="One JPEG, PNG, or WebP photo, up to 10 MiB."),
    ],
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
    intent: Annotated[
        str | None,
        Form(max_length=1_000, description="Optional shooting intent."),
    ] = None,
) -> AnalysisResponse:
    """Validate one uploaded photo and return structured coaching feedback."""
    try:
        image_bytes = await photo.read(MAX_IMAGE_BYTES + 1)
        image = validate_image(image_bytes, photo.content_type)
    except ImageTooLargeError as exc:
        raise PayloadTooLargeError(str(exc)) from exc
    except ImageValidationError as exc:
        raise InvalidImageError(str(exc)) from exc
    finally:
        await photo.close()

    normalized_intent = intent.strip() if intent and intent.strip() else None
    return await service.analyze(image_bytes, image, normalized_intent)
