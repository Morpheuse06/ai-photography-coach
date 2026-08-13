"""Sequential runner for repeatable, locally stored model evaluations."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from photography_coach.dependencies import get_analysis_service
from photography_coach.evals.dataset import EvaluationDataset, load_dataset
from photography_coach.image_validation import validate_image
from photography_coach.schemas.analysis import AnalysisResponse
from photography_coach.services.analysis import AnalysisService


class EvaluationCaseResult(BaseModel):
    """Stored outcome for one dataset case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    image_path: str
    intent: str | None
    status: Literal["succeeded", "failed"]
    response: AnalysisResponse | None = None
    error_type: str | None = None
    error_message: str | None = None


class EvaluationRun(BaseModel):
    """A resumable snapshot of one complete dataset run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    dataset_id: str
    started_at: datetime
    completed_at: datetime | None = None
    cases: list[EvaluationCaseResult] = Field(default_factory=list)


def _write_run(run: EvaluationRun, output_path: Path) -> None:
    """Atomically replace the snapshot so interrupted writes do not corrupt it."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(output_path)


def _diagnostic_message(exc: Exception) -> str:
    """Return a bounded local diagnostic without storing raw model output."""
    parts = [str(exc)]
    cause = exc.__cause__
    if cause is not None:
        parts.append(f"cause={type(cause).__name__}: {cause}")
    return " | ".join(parts)[:2_000]


async def run_dataset(
    dataset: EvaluationDataset,
    *,
    project_root: Path,
    output_path: Path,
    service: AnalysisService,
    previous_run: EvaluationRun | None = None,
) -> EvaluationRun:
    """Run every case sequentially and persist progress after each response."""
    if previous_run is not None and previous_run.dataset_id != dataset.dataset_id:
        raise ValueError("saved run dataset_id does not match the manifest")

    started_at = previous_run.started_at if previous_run else datetime.now(timezone.utc)
    run = EvaluationRun(
        run_id=(
            previous_run.run_id
            if previous_run
            else f"{dataset.dataset_id}-{started_at.strftime('%Y%m%dT%H%M%SZ')}"
        ),
        dataset_id=dataset.dataset_id,
        started_at=started_at,
    )
    previous_results = {
        result.case_id: result for result in previous_run.cases
    } if previous_run else {}
    _write_run(run, output_path)

    for index, case in enumerate(dataset.cases, start=1):
        previous_result = previous_results.get(case.case_id)
        if previous_result is not None and previous_result.status == "succeeded":
            run.cases.append(previous_result)
            _write_run(run, output_path)
            print(f"[{index}/{len(dataset.cases)}] skipping succeeded {case.case_id}", flush=True)
            continue

        print(f"[{index}/{len(dataset.cases)}] analyzing {case.case_id}", flush=True)
        image_path = project_root / case.image_path
        try:
            image_bytes = image_path.read_bytes()
            image = validate_image(image_bytes)
            response = await service.analyze(image_bytes, image, case.intent)
            result = EvaluationCaseResult(
                case_id=case.case_id,
                image_path=case.image_path,
                intent=case.intent,
                status="succeeded",
                response=response,
            )
            print(
                f"[{index}/{len(dataset.cases)}] succeeded in "
                f"{response.metadata.latency_ms} ms",
                flush=True,
            )
        except Exception as exc:  # Keep later cases runnable after one provider failure.
            result = EvaluationCaseResult(
                case_id=case.case_id,
                image_path=case.image_path,
                intent=case.intent,
                status="failed",
                error_type=type(exc).__name__,
                error_message=_diagnostic_message(exc),
            )
            print(
                f"[{index}/{len(dataset.cases)}] failed: {type(exc).__name__}: {exc}",
                flush=True,
            )

        run.cases.append(result)
        _write_run(run, output_path)

    run.completed_at = datetime.now(timezone.utc)
    _write_run(run, output_path)
    return run


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local photography evaluation dataset.")
    parser.add_argument("manifest", type=Path, help="Path to the dataset JSON manifest.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path. Defaults to evals/results/<dataset>-<timestamp>.json.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Keep successful cases in an existing output file and retry failures.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    project_root = Path.cwd()
    dataset = load_dataset(args.manifest, project_root)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.output or Path(
        f"evals/results/{dataset.dataset_id}-{timestamp}.json"
    )
    previous_run = None
    if args.resume:
        if not output_path.is_file():
            raise ValueError("--resume requires an existing output file")
        previous_run = EvaluationRun.model_validate_json(
            output_path.read_text(encoding="utf-8")
        )
    run = await run_dataset(
        dataset,
        project_root=project_root,
        output_path=output_path,
        service=get_analysis_service(),
        previous_run=previous_run,
    )
    succeeded = sum(case.status == "succeeded" for case in run.cases)
    print(
        f"completed: {succeeded}/{len(run.cases)} succeeded; result={output_path}",
        flush=True,
    )
    return 0 if succeeded == len(run.cases) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
