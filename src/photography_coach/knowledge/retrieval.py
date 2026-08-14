"""Structured contracts for planning knowledge retrieval from a photo."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from photography_coach.knowledge.schemas import Identifier, KnowledgeDimension, ShortText


ObservationText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=10, max_length=500),
]
RetrievalText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=20, max_length=500),
]
UserIntentText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
]
PhotoDimension = Literal[
    "composition",
    "lighting",
    "color",
    "subject_expression",
    "visual_storytelling",
]
REPORT_DIMENSIONS: tuple[PhotoDimension, ...] = (
    "composition",
    "lighting",
    "color",
    "subject_expression",
    "visual_storytelling",
)


class VisibleEvidence(BaseModel):
    """One neutral, image-grounded observation used to plan retrieval."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: Identifier
    dimension: PhotoDimension
    description: ObservationText
    location: ShortText


class PhotoObservation(BaseModel):
    """Visible facts from the photo, before photography advice is generated."""

    model_config = ConfigDict(extra="forbid")

    scene_summary: ObservationText
    evidence: list[VisibleEvidence] = Field(min_length=1, max_length=20)
    unknowns: list[ShortText] = Field(
        min_length=1,
        max_length=10,
        description="Facts the image alone cannot establish reliably.",
    )

    @model_validator(mode="after")
    def evidence_and_unknowns_must_be_unique(self) -> "PhotoObservation":
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence_id values must be unique")
        if len(self.unknowns) != len(set(self.unknowns)):
            raise ValueError("unknowns values must be unique")
        return self


class RetrievalQuery(BaseModel):
    """A standalone text question that will be converted into an embedding."""

    model_config = ConfigDict(extra="forbid")

    query_id: Identifier
    dimension: KnowledgeDimension
    evidence_ids: list[Identifier] = Field(min_length=1, max_length=5)
    query_text: RetrievalText
    teaching_goal: ShortText
    top_k: int = Field(default=2, ge=1, le=3)

    @model_validator(mode="after")
    def evidence_references_must_be_unique(self) -> "RetrievalQuery":
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids values must be unique")
        return self


class RetrievalPlan(BaseModel):
    """All bounded knowledge searches planned for one photo analysis."""

    model_config = ConfigDict(extra="forbid")

    user_intent: UserIntentText | None = None
    observation: PhotoObservation
    queries: list[RetrievalQuery] = Field(min_length=1, max_length=5)
    max_total_chunks: int = Field(default=6, ge=1, le=10)

    @model_validator(mode="after")
    def queries_must_reference_the_observation(self) -> "RetrievalPlan":
        query_ids = [query.query_id for query in self.queries]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("query_id values must be unique")

        normalized_queries = [query.query_text.casefold() for query in self.queries]
        if len(normalized_queries) != len(set(normalized_queries)):
            raise ValueError("query_text values must be unique")

        evidence_by_id = {
            evidence.evidence_id: evidence for evidence in self.observation.evidence
        }
        for query in self.queries:
            missing_ids = [
                evidence_id
                for evidence_id in query.evidence_ids
                if evidence_id not in evidence_by_id
            ]
            if missing_ids:
                raise ValueError(
                    f"query '{query.query_id}' references unknown evidence_ids: "
                    f"{', '.join(missing_ids)}"
                )

            if query.dimension != "general" and not any(
                evidence_by_id[evidence_id].dimension == query.dimension
                for evidence_id in query.evidence_ids
            ):
                raise ValueError(
                    f"query '{query.query_id}' must reference evidence from its dimension"
                )
        return self


def require_full_report_dimension_coverage(plan: RetrievalPlan) -> RetrievalPlan:
    """Require one query for every dimension in the fixed final report."""

    actual_dimensions = [query.dimension for query in plan.queries]
    missing_dimensions = [
        dimension
        for dimension in REPORT_DIMENSIONS
        if dimension not in actual_dimensions
    ]
    repeated_dimensions = [
        dimension
        for dimension in REPORT_DIMENSIONS
        if actual_dimensions.count(dimension) > 1
    ]
    unexpected_dimensions = [
        dimension
        for dimension in actual_dimensions
        if dimension not in REPORT_DIMENSIONS
    ]
    if missing_dimensions or repeated_dimensions or unexpected_dimensions:
        details = []
        if missing_dimensions:
            details.append(f"missing: {', '.join(missing_dimensions)}")
        if repeated_dimensions:
            details.append(f"repeated: {', '.join(repeated_dimensions)}")
        if unexpected_dimensions:
            details.append(f"unexpected: {', '.join(unexpected_dimensions)}")
        raise ValueError(
            "retrieval plan must contain exactly one query for every report "
            f"dimension ({'; '.join(details)})"
        )
    return plan
