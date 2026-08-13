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

    # ── Object storage (Backblaze B2 S3-compatible) ─────────────────────
    # S3-compatible durable storage for uploads. When R2_BUCKET is empty the
    # app falls back to the local UPLOAD_DIR (dev-only — lost on redeploy).
    R2_ENDPOINT: str = Field(
        default="",
        description="S3 endpoint (e.g. https://s3.us-west-004.backblazeb2.com)",
    )
    R2_ACCESS_KEY_ID: str = Field(default="", description="S3 access key id")
    R2_SECRET_ACCESS_KEY: str = Field(default="", description="S3 secret access key")
    R2_BUCKET: str = Field(default="", description="Bucket name; empty = local fallback")
    R2_REGION: str = Field(default="auto", description="S3 region (auto for R2, us-east-1 for B2)")

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

    # ── Hardening / Reliability ──────────────────────────────────────────────
    # Timeouts (seconds)
    MODEL_GATEWAY_TIMEOUT: int = Field(default=30, description="Model gateway total timeout")
    MODEL_GATEWAY_CONNECT_TIMEOUT: int = Field(default=10, description="Model gateway connect timeout")
    RETRIEVAL_EMBED_TIMEOUT: int = Field(default=20, description="Embedding request timeout")
    RETRIEVAL_RERANK_TIMEOUT: int = Field(default=15, description="Rerank request timeout")
    RETRIEVAL_VECTOR_SEARCH_TIMEOUT: int = Field(default=5, description="Vector search timeout")
    AGENT_RUN_TIMEOUT: int = Field(default=60, description="Agent run total timeout")
    AGENT_ITERATION_TIMEOUT: int = Field(default=30, description="Agent iteration timeout")
    PDF_PARSE_TIMEOUT: int = Field(default=10, description="PDF parsing timeout")

    # Upload limits
    MAX_UPLOAD_SIZE: int = Field(default=100 * 1024 * 1024, description="Max upload size in bytes (100 MB)")
    MAX_PDF_PAGES: int = Field(default=100, description="Maximum PDF pages allowed")

    # Concurrency
    EMBED_BATCH_SIZE: int = Field(default=64, description="Embedding batch size (Cohere limit: 96)")
    MAX_CONCURRENT_INDEXING: int = Field(default=2, description="Max concurrent indexing jobs per user")
    MAX_CONCURRENT_PDF_PARSES: int = Field(default=2, description="Max concurrent PDF parses")

    # Rate limits
    UPLOAD_RATE_LIMIT: int = Field(default=5, description="Uploads per minute per IP")
    CHAT_RATE_LIMIT: int = Field(default=20, description="Chat requests per minute per IP")

    # Retries
    RETRY_MAX_ATTEMPTS: int = Field(default=3, description="Max retry attempts")
    RETRY_BASE_DELAY: float = Field(default=0.5, description="Base retry delay in seconds")
    RETRY_MAX_DELAY: float = Field(default=4.0, description="Max retry delay in seconds")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton — import this, not Settings() directly."""
    return Settings()


# Convenience alias used throughout the codebase
settings = get_settings()
