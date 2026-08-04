"""
settings.py
-----------
Single source of truth for every configurable value.
All env vars use SCREAMING_SNAKE_CASE prefixed by domain (conventions.md).

Load order: .env file → environment → defaults below.
Never import os.getenv anywhere else in the codebase — import `settings` instead.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    # LiteLLM routes to providers by "provider/model" string prefix
    # (e.g. "groq/llama-3.3-70b-versatile", "openrouter/mistralai/...").
    MODEL_GATEWAY_PROVIDER: str = Field(
        default="groq",
        description="Primary provider prefix: 'groq' | 'openrouter'",
    )
    MODEL_GATEWAY_MODEL: str = Field(
        default="llama-3.3-70b-versatile",
        description="Model name on the active provider",
    )

    # Groq
    MODEL_GATEWAY_GROQ_API_KEY: str = Field(default="", description="Groq API key")

    # OpenRouter (fallback)
    MODEL_GATEWAY_OPENROUTER_API_KEY: str = Field(default="", description="OpenRouter API key")
    MODEL_GATEWAY_OPENROUTER_MODEL: str = Field(
        default="mistralai/mistral-7b-instruct",
        description="Fallback model on OpenRouter",
    )

    # ── Cohere (embeddings + rerank) ──────────────────────────────────────
    # Embeddings use embed-v3 (1024 dims, matches EMBEDDING_DIM); rerank uses
    # rerank-v3. Cohere has a generous free trial tier. See ADR-003 addendum.
    COHERE_API_KEY: str = Field(default="", description="Cohere API key")
    COHERE_EMBED_MODEL: str = Field(
        default="embed-english-v3.0",
        description="Cohere embedding model (1024 dims)",
    )
    COHERE_RERANK_MODEL: str = Field(
        default="rerank-multilingual-v3.0",
        description="Cohere rerank model",
    )

    # Embedding vector dimensionality — must match chunks.embedding column
    # (migration uses vector(EMBEDDING_DIM)). Cohere embed-v3 produces 1024 dims.
    EMBEDDING_DIM: int = Field(
        default=1024,
        description="Dimension of embedding vectors stored in Postgres",
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
    UPLOAD_DIR: str = Field(
        default=str(Path.cwd() / ".data" / "uploads"),
        description="Writable directory for raw uploaded source files (local fallback)",
    )

    # ── Object storage (Cloudflare R2) ────────────────────────────────────
    # S3-compatible durable storage for uploads. When R2_BUCKET is empty the
    # app falls back to the local UPLOAD_DIR (dev-only — lost on redeploy).
    R2_ENDPOINT: str = Field(
        default="",
        description="R2 S3 endpoint (e.g. https://<account>.r2.cloudflarestorage.com)",
    )
    R2_ACCESS_KEY_ID: str = Field(default="", description="R2 access key id")
    R2_SECRET_ACCESS_KEY: str = Field(default="", description="R2 secret access key")
    R2_BUCKET: str = Field(default="", description="R2 bucket name; empty = local fallback")

    @property
    def r2_enabled(self) -> bool:
        return bool(self.R2_ENDPOINT and self.R2_ACCESS_KEY_ID and self.R2_BUCKET)

    APP_ENV: str = Field(default="development", description="development | production")
    APP_DEBUG: bool = Field(default=False)

    # ── CORS ───────────────────────────────────────────────────────────────
    # Comma-separated list of allowed browser origins. In production this is
    # the deployed frontend (Vercel/static), in dev the Next.js dev server.
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000",
        description="Comma-separated allowed CORS origins",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton — import this, not Settings() directly."""
    return Settings()


# Convenience alias used throughout the codebase
settings = get_settings()
