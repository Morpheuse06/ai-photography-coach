"""Environment-backed application configuration."""

from functools import lru_cache
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
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return one settings instance for the lifetime of the process."""
    return Settings()
