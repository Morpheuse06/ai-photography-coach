"""HTTP response contracts for photo analysis."""

from pydantic import BaseModel, ConfigDict, Field

from photography_coach.schemas.report import PhotographyReport


class ImageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_type: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    size_bytes: int = Field(gt=0)


class ModelUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class AnalysisMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    prompt_version: str
    latency_ms: int = Field(ge=0)
    image: ImageMetadata
    usage: ModelUsage


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: PhotographyReport
    metadata: AnalysisMetadata


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
