"""Versioned HTTP endpoints for the photography coach."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile

from photography_coach.dependencies import (
    get_analysis_service,
    get_control_plane_analysis_service,
    get_rag_analysis_service,
)
from photography_coach.errors import (
    InvalidImageError,
    InvalidRequestError,
    PayloadTooLargeError,
)
from photography_coach.image_validation import (
    MAX_IMAGE_BYTES,
    ImageTooLargeError,
    ImageValidationError,
    ValidatedImage,
    validate_image,
)
from photography_coach.schemas.analysis import AnalysisResponse, ErrorResponse
from photography_coach.services.analysis import AnalysisService
from photography_coach.services.control_plane import ControlPlaneAnalysisService
from photography_coach.services.rag_analysis import RagAnalysisService


router = APIRouter(prefix="/api/v1", tags=["analysis"])
rag_router = APIRouter(prefix="/api/v2", tags=["rag-analysis"])

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
    image_bytes, image = await _read_validated_photo(photo)
    normalized_intent = intent.strip() if intent and intent.strip() else None
    return await service.analyze(image_bytes, image, normalized_intent)


@rag_router.post(
    "/analyze",
    response_model=AnalysisResponse,
    responses=ANALYSIS_ERROR_RESPONSES,
)
async def analyze_photo_with_rag(
    request: Request,
    photo: Annotated[
        UploadFile,
        File(description="One JPEG, PNG, or WebP photo, up to 10 MiB."),
    ],
    service: Annotated[RagAnalysisService, Depends(get_rag_analysis_service)],
    intent: Annotated[
        str | None,
        Form(max_length=1_000, description="Optional shooting intent."),
    ] = None,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Client retry key; required when the control plane is on.",
        ),
    ] = None,
    access_code: Annotated[
        str | None,
        Header(
            alias="X-Access-Code",
            description="Optional raw access code; required in code_required mode.",
        ),
    ] = None,
    control_plane: Annotated[
        ControlPlaneAnalysisService | None,
        Depends(get_control_plane_analysis_service),
    ] = None,
) -> AnalysisResponse:
    """Validate a photo and analyze it with retrieved photography knowledge."""

    image_bytes, image = await _read_validated_photo(photo)
    normalized_intent = intent.strip() if intent and intent.strip() else None
    if control_plane is not None:
        if not idempotency_key:
            raise InvalidRequestError(
                "The Idempotency-Key header is required."
            )
        source = request.client.host if request.client else "unknown"
        return await control_plane.analyze(
            image_bytes,
            image,
            normalized_intent,
            idempotency_key=idempotency_key,
            access_code=(
                access_code.strip() if access_code and access_code.strip() else None
            ),
            source=source,
        )
    result = await service.analyze(image_bytes, image, normalized_intent)
    return result.response


async def _read_validated_photo(photo: UploadFile) -> tuple[bytes, ValidatedImage]:
    """Read, close, and validate one FastAPI upload for either API version."""

    try:
        image_bytes = await photo.read(MAX_IMAGE_BYTES + 1)
        image = validate_image(image_bytes, photo.content_type)
    except ImageTooLargeError as exc:
        raise PayloadTooLargeError(str(exc)) from exc
    except ImageValidationError as exc:
        raise InvalidImageError(str(exc)) from exc
    finally:
        await photo.close()
    return image_bytes, image
