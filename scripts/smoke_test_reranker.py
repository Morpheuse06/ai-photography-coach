"""Run one small, text-only smoke test against the configured reranker."""

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path

import httpx

from photography_coach.config import Settings
from photography_coach.knowledge.reranking import RerankDocument
from photography_coach.providers.dashscope_reranker import (
    DashScopeRerankingProvider,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = (
    PROJECT_ROOT / "knowledge/chunks/ai-photography-coach-handbook.json"
)
RESULT_PATH = PROJECT_ROOT / "evals/results/rerank-smoke.json"
QUERY = "主体靠近画面边缘，背景高亮杂物抢眼，怎样改善构图？"
CANDIDATE_IDS = (
    "ai-photography-coach-handbook-composition-frame-edges",
    "ai-photography-coach-handbook-composition-visual-weight",
    "ai-photography-coach-handbook-lighting-direction-quality",
    "ai-photography-coach-handbook-color-relationships",
)


def load_documents() -> tuple[RerankDocument, ...]:
    """Load only the four public handbook chunks used by this smoke test."""

    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    chunks_by_id = {
        chunk["chunk_id"]: chunk
        for chunk in payload["chunks"]
    }
    return tuple(
        RerankDocument(
            document_id=chunk_id,
            text=chunks_by_id[chunk_id]["content"],
        )
        for chunk_id in CANDIDATE_IDS
    )


async def main() -> None:
    """Call the real reranker once and save a credential-free summary."""

    settings = Settings()
    if settings.model_api_key is None:
        raise RuntimeError("MODEL_API_KEY is required for the smoke test.")
    if settings.rerank_base_url is None:
        raise RuntimeError("RERANK_BASE_URL is required for the smoke test.")

    documents = load_documents()
    async with httpx.AsyncClient(
        timeout=settings.rag_context_timeout_seconds,
        headers={
            "Authorization": (
                f"Bearer {settings.model_api_key.get_secret_value()}"
            ),
            "Content-Type": "application/json",
        },
    ) as client:
        provider = DashScopeRerankingProvider(
            api_key="handled-by-injected-client",
            base_url=settings.rerank_base_url,
            model=settings.rerank_model,
            timeout_seconds=settings.rag_context_timeout_seconds,
            max_retries=settings.model_max_retries,
            client=client,
        )
        result = await provider.rerank(QUERY, documents, top_n=3)

    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "provider": provider.name,
        "model": provider.model,
        "query": QUERY,
        "candidate_count": len(documents),
        "top_n": 3,
        "input_tokens": result.input_tokens,
        "ranked_results": [
            {
                "rank": rank,
                "document_id": documents[item.document_index].document_id,
                "relevance_score": item.relevance_score,
            }
            for rank, item in enumerate(result.items, start=1)
        ],
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
