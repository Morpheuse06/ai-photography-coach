"""Run authorized end-to-end RAG analyses and save local evidence."""

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter

from photography_coach.config import Settings
from photography_coach.dependencies import build_rag_analysis_service
from photography_coach.image_validation import validate_image
from photography_coach.services.rag_analysis import RagAnalysisService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PHOTO = Path("Photos/0813/04-old-alley-highrise.jpg")
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evals/results"


def resolve_photo_path(photo_path: Path) -> Path:
    """Resolve one project-local photo without allowing path traversal."""

    resolved_root = PROJECT_ROOT.resolve()
    resolved_photo = (
        photo_path.resolve()
        if photo_path.is_absolute()
        else (resolved_root / photo_path).resolve()
    )
    if not resolved_photo.is_relative_to(resolved_root):
        raise ValueError(f"photo path leaves the project: {photo_path}")
    if not resolved_photo.is_file():
        raise ValueError(f"photo does not exist: {photo_path}")
    return resolved_photo


async def run_photos(
    photo_paths: list[Path],
    *,
    output_dir: Path,
    service: RagAnalysisService,
) -> list[dict[str, object]]:
    """Analyze photos sequentially while keeping earlier results recoverable."""

    records: list[dict[str, object]] = []
    for index, photo_path in enumerate(photo_paths, start=1):
        print(f"[{index}/{len(photo_paths)}] analyzing {photo_path.name}", flush=True)
        try:
            output_path = output_dir / f"rag-v2-{photo_path.stem}.json"
            summary = await analyze_photo(service, photo_path, output_path)
            records.append({"status": "succeeded", **summary})
            print(
                f"[{index}/{len(photo_paths)}] succeeded in "
                f"{summary['elapsed_ms']} ms",
                flush=True,
            )
        except Exception as exc:
            records.append(
                {
                    "status": "failed",
                    "photo_path": _display_path(photo_path),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:2_000],
                }
            )
            print(
                f"[{index}/{len(photo_paths)}] failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
    return records


async def analyze_photo(
    service: RagAnalysisService,
    photo_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """Run one analysis and atomically save its report and retrieval evidence."""

    image_bytes = photo_path.read_bytes()
    image = validate_image(image_bytes)
    started_at = perf_counter()
    result = await service.analyze(image_bytes, image, None)
    elapsed_ms = round((perf_counter() - started_at) * 1_000)
    prepared = result.prepared_knowledge

    payload = {
        "test": {
            "created_at": datetime.now(UTC).isoformat(),
            "photo_path": _display_path(photo_path),
            "shooting_intent": None,
            "authorized_provider": "Alibaba Cloud Model Studio",
            "elapsed_ms": elapsed_ms,
        },
        "retrieval": {
            "plan": prepared.plan.model_dump(mode="json"),
            "planner_provider": prepared.planner_provider,
            "planner_model": prepared.planner_model,
            "planner_prompt_version": prepared.planner_prompt_version,
            "planner_attempts": prepared.planner_attempts,
            "latency_ms": prepared.latency_ms,
            "embedding_provider": prepared.retrieval.embedding_provider,
            "embedding_model": prepared.retrieval.embedding_model,
            "embedding_dimensions": prepared.retrieval.embedding_dimensions,
            "reranker_provider": prepared.retrieval.reranker_provider,
            "reranker_model": prepared.retrieval.reranker_model,
            "reranker_input_tokens": prepared.retrieval.reranker_input_tokens,
            "matches": [
                {
                    "chunk_id": match.chunk.chunk_id,
                    "dimension": match.chunk.dimension,
                    "matched_query_ids": match.matched_query_ids,
                    "embedding_score": match.score,
                    "rerank_score": match.rerank_score,
                }
                for match in prepared.retrieval.chunks
            ],
        },
        "response": result.response.model_dump(mode="json"),
    }
    _write_json(output_path, payload)
    return {
        "photo_path": _display_path(photo_path),
        "result_path": _display_path(output_path),
        "elapsed_ms": elapsed_ms,
        "planner_attempts": prepared.planner_attempts,
        "retrieved_chunk_ids": [
            match.chunk.chunk_id
            for match in prepared.retrieval.chunks
        ],
        "reranker_input_tokens": prepared.retrieval.reranker_input_tokens,
        "total_tokens": result.response.metadata.usage.total_tokens,
    }


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return path.name


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run authorized photos through the real V2 RAG pipeline."
    )
    parser.add_argument(
        "photos",
        nargs="*",
        type=Path,
        default=[DEFAULT_PHOTO],
        help="Project-local photo paths. Defaults to the original smoke photo.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Ignored local directory for reports and the run summary.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    photo_paths = [resolve_photo_path(path) for path in args.photos]
    output_dir = (
        args.output_dir
        if args.output_dir.is_absolute()
        else PROJECT_ROOT / args.output_dir
    )
    settings = Settings().model_copy(update={"rag_enabled": True})
    service = await build_rag_analysis_service(settings)
    started_at = datetime.now(UTC)
    records = await run_photos(
        photo_paths,
        output_dir=output_dir,
        service=service,
    )
    summary_path = output_dir / (
        f"rag-v2-regression-{started_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    _write_json(
        summary_path,
        {
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "records": records,
        },
    )
    succeeded = sum(record["status"] == "succeeded" for record in records)
    print(
        f"completed: {succeeded}/{len(records)} succeeded; "
        f"summary={_display_path(summary_path)}",
        flush=True,
    )
    return 0 if succeeded == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
