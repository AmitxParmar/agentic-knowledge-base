"""
scripts/backfill_embeddings.py
------------------------------
Re-embed all chunks whose pgvector `embedding` column is NULL.

Background: the migration to store embeddings in Postgres (ADR-002 addendum)
left pre-existing chunks with NULL embeddings. Dense search skips those rows,
so a document ingested before the migration is keyword-searchable but not
vector-searchable until this runs.

Run after setting COHERE_API_KEY:
    uv run python scripts/backfill_embeddings.py

Idempotent: only touches rows where embedding IS NULL, and batches so a large
corpus doesn't exceed the embedding provider's batch limit in one call.
"""
from __future__ import annotations

import asyncio
import logging

import logfire
from sqlalchemy import select

import src.shared.models  # noqa: F401 — register ORM models
from app.settings import settings
from src.ingestion.models import Chunk
from src.retrieval.embedder import embed_texts
from src.shared.database import SessionLocal

logger = logging.getLogger(__name__)

_BATCH = 64


async def backfill() -> int:
    if not settings.COHERE_API_KEY:
        # The embedder silently falls back to hash vectors without a key.
        # Writing those to the vector index would corrupt retrieval quality,
        # so refuse to run rather than persist meaningless embeddings.
        raise SystemExit(
            "COHERE_API_KEY is not set. Backfill would write hash-fallback "
            "embeddings, not real vectors. Set COHERE_API_KEY in .env first."
        )

    updated = 0
    async with SessionLocal() as session:
        while True:
            result = await session.execute(
                select(Chunk).where(Chunk.embedding.is_(None)).order_by(Chunk.created_at).limit(_BATCH)
            )
            chunks = list(result.scalars().all())
            if not chunks:
                break

            texts = [chunk.text for chunk in chunks]
            vectors = await embed_texts(texts)
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.embedding = vector
            await session.commit()
            updated += len(chunks)
            logger.info("backfill: embedded %d chunks (running total %d)", len(chunks), updated)

    logfire.info("backfill.done", chunks=updated)
    return updated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    total = asyncio.run(backfill())
    print(f"Backfilled {total} chunk embeddings.")
