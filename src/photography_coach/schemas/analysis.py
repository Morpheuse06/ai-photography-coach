"""HTTP response contracts for photo analysis."""

from pydantic import BaseModel, ConfigDict, Field

from photography_coach.schemas.interaction import AnalysisInteraction
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


class RetrievalMetadata(BaseModel):
    """Traceable, non-secret information about one RAG retrieval run."""

    model_config = ConfigDict(extra="forbid")

    knowledge_source_id: str
    knowledge_source_version: str
    planner_model: str
    planner_prompt_version: str
    planner_attempts: int = Field(ge=1)
    embedding_model: str
    reranker_model: str
    latency_ms: int = Field(ge=0)
    retrieved_chunk_ids: list[str] = Field(min_length=1, max_length=10)


class AnalysisMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    prompt_version: str
    latency_ms: int = Field(ge=0)
    image: ImageMetadata
    usage: ModelUsage
    retrieval: RetrievalMetadata | None = None


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: PhotographyReport
    metadata: AnalysisMetadata
    interaction: AnalysisInteraction | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Identifiers and quota state populated when the control plane is enabled."
        ),
    )


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
