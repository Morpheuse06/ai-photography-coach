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

    # Control plane: quotas, analysis records, anonymous feedback, and the
    # management console. Disabled by default so local runs stay unchanged.
    control_plane_enabled: bool = False
    database_url: str = "sqlite+aiosqlite:///data/control_plane.db"
    admin_session_ttl_hours: float = Field(default=12.0, gt=0, le=168)
    reservation_ttl_minutes: int = Field(default=30, ge=1, le=120)
    in_flight_wait_seconds: float = Field(default=300.0, ge=30, le=600)
    default_access_mode: Literal["open", "code_required", "closed"] = "open"
    default_per_source_hour_limit: int | None = Field(default=60, ge=1)
    default_global_daily_limit: int | None = Field(default=500, ge=1)
    default_concurrent_analysis_limit: int = Field(default=4, ge=1)
    retention_interval_hours: float = Field(default=24.0, gt=0, le=168)


@lru_cache
def get_settings() -> Settings:
    """Return one settings instance for the lifetime of the process."""
    return Settings()
