"""Structured contracts for RAG sources and retrievable knowledge chunks."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9-]{0,99}$"),
]
Version = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$"),
]
ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]
ChunkText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=20, max_length=4_000),
]
Tag = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9-]{0,49}$"),
]

SourceKind = Literal["project_authored", "book", "manual", "article", "course", "other"]
UsageRights = Literal["project_owned", "licensed", "public_domain", "permission_required"]
KnowledgeDimension = Literal[
    "composition",
    "lighting",
    "color",
    "subject_expression",
    "visual_storytelling",
    "general",
]
Difficulty = Literal["beginner", "intermediate", "advanced"]


class KnowledgeSource(BaseModel):
    """One complete source such as a manual, book, article, or authored guide."""

    model_config = ConfigDict(extra="forbid")

    source_id: Identifier
    title: ShortText
    kind: SourceKind
    version: Version
    authors: list[ShortText] = Field(min_length=1, max_length=20)
    usage_rights: UsageRights
    source_uri: str | None = Field(default=None, max_length=2_000)
    description: ShortText

    @model_validator(mode="after")
    def source_metadata_must_be_consistent(self) -> "KnowledgeSource":
        if len(self.authors) != len(set(self.authors)):
            raise ValueError("authors must be unique")
        if self.kind == "project_authored" and self.usage_rights != "project_owned":
            raise ValueError("project-authored sources must use project_owned rights")
        if self.kind != "project_authored" and not self.source_uri:
            raise ValueError("external sources must provide source_uri for traceability")
        return self


class KnowledgeChunk(BaseModel):
    """A self-contained source passage that can be embedded and retrieved."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: Identifier
    source_id: Identifier
    source_version: Version
    section_path: list[ShortText] = Field(min_length=1, max_length=10)
    chunk_index: int = Field(ge=0)
    source_locator: ShortText
    dimension: KnowledgeDimension
    difficulty: Difficulty
    content: ChunkText
    applicable_scenarios: list[ShortText] = Field(min_length=1, max_length=10)
    actionable_guidance: list[ShortText] = Field(min_length=1, max_length=10)
    limitations: list[ShortText] = Field(min_length=1, max_length=10)
    tags: list[Tag] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def repeated_metadata_must_be_unique(self) -> "KnowledgeChunk":
        fields = {
            "section_path": self.section_path,
            "applicable_scenarios": self.applicable_scenarios,
            "actionable_guidance": self.actionable_guidance,
            "limitations": self.limitations,
            "tags": self.tags,
        }
        for field_name, values in fields.items():
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} values must be unique")
        return self


class KnowledgeCorpus(BaseModel):
    """One source together with all chunks deterministically derived from it."""

    model_config = ConfigDict(extra="forbid")

    source: KnowledgeSource
    chunks: list[KnowledgeChunk] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def chunks_must_belong_to_the_source(self) -> "KnowledgeCorpus":
        chunk_ids = [chunk.chunk_id for chunk in self.chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("chunk_id values must be unique")

        expected_indexes = list(range(len(self.chunks)))
        actual_indexes = [chunk.chunk_index for chunk in self.chunks]
        if actual_indexes != expected_indexes:
            raise ValueError("chunk_index values must be continuous and ordered from zero")

        for chunk in self.chunks:
            if chunk.source_id != self.source.source_id:
                raise ValueError("every chunk must reference the corpus source_id")
            if chunk.source_version != self.source.version:
                raise ValueError("every chunk must reference the corpus source version")
        return self
