"""Validated manifests for repeatable local photography evaluations."""

from hashlib import sha256
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


DatasetId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9-]{0,49}$"),
]
CaseId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9-]{0,99}$"),
]
RelativeImagePath = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^Photos/[A-Za-z0-9._/-]+$"),
]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Tag = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9-]{0,49}$"),
]
Intent = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]

PhotoCategory = Literal[
    "portrait",
    "environmental_portrait",
    "landscape",
    "urban",
    "architecture",
    "nature",
    "still_life",
    "abstract",
    "other",
]


class EvaluationCase(BaseModel):
    """One stable photo input in an evaluation dataset."""

    model_config = ConfigDict(extra="forbid")

    case_id: CaseId
    image_path: RelativeImagePath
    sha256: Sha256Digest
    category: PhotoCategory
    intent: Intent | None = None
    tags: list[Tag] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def tags_must_be_unique(self) -> "EvaluationCase":
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("tags must be unique within a case")
        return self


class EvaluationDataset(BaseModel):
    """A versioned list of photo inputs that can be run repeatedly."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: DatasetId
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    cases: list[EvaluationCase] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def identifiers_and_paths_must_be_unique(self) -> "EvaluationDataset":
        case_ids = [case.case_id for case in self.cases]
        image_paths = [case.image_path for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case_id values must be unique")
        if len(image_paths) != len(set(image_paths)):
            raise ValueError("image_path values must be unique")
        return self


def load_dataset(manifest_path: Path, project_root: Path) -> EvaluationDataset:
    """Load a manifest and verify every referenced photo and content digest."""
    dataset = EvaluationDataset.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    resolved_root = project_root.resolve()

    for case in dataset.cases:
        image_path = (resolved_root / case.image_path).resolve()
        if not image_path.is_relative_to(resolved_root):
            raise ValueError(f"{case.case_id}: image path leaves the project directory")
        if not image_path.is_file():
            raise ValueError(f"{case.case_id}: image file does not exist: {case.image_path}")

        actual_digest = sha256(image_path.read_bytes()).hexdigest()
        if actual_digest != case.sha256:
            raise ValueError(f"{case.case_id}: image SHA-256 does not match the manifest")

    return dataset


def load_dataset_json(data: str) -> EvaluationDataset:
    """Parse manifest JSON without touching the file system."""
    return EvaluationDataset.model_validate(json.loads(data))
