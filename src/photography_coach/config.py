"""Environment-backed application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated settings loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    model_provider: Literal["mock", "responses_compatible", "dashscope"] = "mock"
    model_api_key: SecretStr | None = None
    model_name: str = "gpt-5.6-terra"
    model_base_url: str | None = None
    model_timeout_seconds: float = Field(default=45.0, gt=0, le=120)
    model_max_retries: int = Field(default=2, ge=0, le=3)
    rag_enabled: bool = False
    rag_planner_model: str | None = None
    rag_context_timeout_seconds: float = Field(default=90.0, gt=0, le=240)
    embedding_model: str = "qwen3.7-text-embedding"
    embedding_dimensions: int = Field(default=1_024, ge=64, le=2_560)
    embedding_max_batch_size: int = Field(default=20, ge=1, le=100)
    rerank_model: str = "qwen3-rerank"
    rerank_base_url: str | None = None
    rerank_candidate_k: int = Field(default=8, ge=1, le=100)
    rerank_final_max_chunks: int = Field(default=6, ge=5, le=10)
    chroma_path: Path = Path("data/chroma")
    knowledge_corpus_path: Path = Path(
        "knowledge/chunks/ai-photography-coach-handbook.json"
    )
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return one settings instance for the lifetime of the process."""
    return Settings()
