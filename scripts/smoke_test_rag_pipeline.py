"""Run one authorized end-to-end RAG analysis and save local evidence."""

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter

from photography_coach.config import Settings
from photography_coach.dependencies import build_rag_analysis_service
from photography_coach.image_validation import validate_image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHOTO_PATH = PROJECT_ROOT / "Photos/0813/04-old-alley-highrise.jpg"
RESULT_PATH = (
    PROJECT_ROOT
    / "evals/results/rag-smoke-04-old-alley-highrise-reranker.json"
)


async def main() -> None:
    """Execute the real RAG pipeline without changing the saved .env switch."""

    settings = Settings().model_copy(update={"rag_enabled": True})
    image_bytes = PHOTO_PATH.read_bytes()
    image = validate_image(image_bytes)
    service = await build_rag_analysis_service(settings)

    started_at = perf_counter()
    result = await service.analyze(image_bytes, image, None)
    elapsed_ms = round((perf_counter() - started_at) * 1_000)
    prepared = result.prepared_knowledge

    payload = {
        "test": {
            "created_at": datetime.now(UTC).isoformat(),
            "photo_path": str(PHOTO_PATH.relative_to(PROJECT_ROOT)),
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
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result_path": str(RESULT_PATH.relative_to(PROJECT_ROOT)),
                "elapsed_ms": elapsed_ms,
                "planner_attempts": prepared.planner_attempts,
                "retrieved_chunk_ids": [
                    match.chunk.chunk_id
                    for match in prepared.retrieval.chunks
                ],
                "reranker_provider": prepared.retrieval.reranker_provider,
                "reranker_model": prepared.retrieval.reranker_model,
                "reranker_input_tokens": (
                    prepared.retrieval.reranker_input_tokens
                ),
                "report_metadata": result.response.metadata.model_dump(
                    mode="json"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
