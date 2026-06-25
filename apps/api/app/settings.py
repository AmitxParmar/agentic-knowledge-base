"""
settings.py
-----------
Single source of truth for every configurable value.
All env vars use SCREAMING_SNAKE_CASE prefixed by domain (conventions.md).

Load order: .env file → environment → defaults below.
Never import os.getenv anywhere else in the codebase — import `settings` instead.
"""

from functools import lru_cache

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/research_workspace",
        description="Async SQLAlchemy URL for Postgres",
    )

    # ── Model Gateway (ADR-003) ───────────────────────────────────────────
    # Primary: Groq — fast inference, generous free tier
    MODEL_GATEWAY_PROVIDER: str = Field(
        default="groq",
        description="Active LLM backend: 'groq' | 'openrouter'",
    )
    MODEL_GATEWAY_MODEL: str = Field(
        default="llama-3.3-70b-versatile",
        description="Model name on the active provider",
    )

    # Groq
    MODEL_GATEWAY_GROQ_API_KEY: str = Field(default="", description="Groq API key")
    MODEL_GATEWAY_GROQ_BASE_URL: HttpUrl = Field(
        default="https://api.groq.com/openai/v1",  # type: ignore[assignment]
        description="Groq OpenAI-compatible endpoint",
    )

    # OpenRouter (fallback)
    MODEL_GATEWAY_OPENROUTER_API_KEY: str = Field(default="", description="OpenRouter API key")
    MODEL_GATEWAY_OPENROUTER_BASE_URL: HttpUrl = Field(
        default="https://openrouter.ai/api/v1",  # type: ignore[assignment]
        description="OpenRouter OpenAI-compatible endpoint",
    )
    MODEL_GATEWAY_OPENROUTER_MODEL: str = Field(
        default="mistralai/mistral-7b-instruct",
        description="Fallback model on OpenRouter",
    )

    # ── BGE models (self-hosted HTTP endpoints) ───────────────────────────
    BGE_EMBEDDER_URL: str = Field(
        default="http://localhost:8001/embed",
        description="BGE-M3 embedding endpoint (self-hosted)",
    )
    BGE_RERANKER_URL: str = Field(
        default="http://localhost:8002/rerank",
        description="BGE-Reranker-v2-m3 rerank endpoint (self-hosted)",
    )

    # ── Observability ─────────────────────────────────────────────────────
    LOGFIRE_TOKEN: str = Field(default="", description="Logfire ingest token")
    LANGFUSE_PUBLIC_KEY: str = Field(default="", description="Langfuse public key (N3)")
    LANGFUSE_SECRET_KEY: str = Field(default="", description="Langfuse secret key (N3)")
    LANGFUSE_HOST: str = Field(default="https://cloud.langfuse.com")

    # ── Async worker (arq) ────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://localhost:6379",
        description="Redis DSN for arq job queue",
    )

    # ── App ───────────────────────────────────────────────────────────────
    APP_ENV: str = Field(default="development", description="development | production")
    APP_DEBUG: bool = Field(default=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton — import this, not Settings() directly."""
    return Settings()


# Convenience alias used throughout the codebase
settings = get_settings()
