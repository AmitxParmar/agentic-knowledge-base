"""
retrieval/vector_index.py
--------------------------
Dense vector search over chunk embeddings stored in Postgres (pgvector).

Replaces the in-memory Turbovec index: embeddings are persisted on the
`chunks.embedding` column at ingestion time, so no index rebuild is needed on
startup — vectors survive cold starts (critical for serverless/container
platforms where process memory is ephemeral).

ADR-002 follow-up: Postgres remains authoritative. The vector index IS the
Postgres column now; there is no second store to keep in sync.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import logfire
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings
from src.ingestion.models import Chunk

logger = logging.getLogger(__name__)


@dataclass
class VectorSearchResult:
    """One result from a dense vector search."""
    id: str            # turbovec_id — joins to chunks.turbovec_id in Postgres
    score: float       # cosine similarity (higher = more relevant)


async def vector_search(
    query_vector: list[float],
    *,
    id_allowlist: list[str],
    top_k: int,
    session: AsyncSession,
) -> list[VectorSearchResult]:
    """
    Cosine search over persisted chunk embeddings, scoped to id_allowlist.

    pgvector's `<=>` operator returns cosine *distance*; we invert it to a
    similarity score so higher means more relevant, matching the old Turbovec
    convention. The metadata pre-filter (workspace/document) is applied in SQL
    via turbovec_id IN (allowlist), so only allowed chunks are scored.
    """
    with logfire.span("vector_index.search", candidates=len(id_allowlist), top_k=top_k):
        if not id_allowlist:
            return []

        # Cosine distance: embedding <=> :query. NULL embeddings (rows ingested
        # before this migration) are excluded via IS NOT NULL.
        # pgvector's distance is in [0, 2]; invert to similarity so higher = better.
        distance = Chunk.embedding.cosine_distance(query_vector)
        similarity = (1 - distance).label("similarity")

        query = (
            select(Chunk.turbovec_id, similarity)
            .where(Chunk.turbovec_id.in_(id_allowlist))
            .where(Chunk.embedding.is_not(None))
            .order_by(similarity.desc())
            .limit(top_k)
        )
        try:
            result = await asyncio.wait_for(
                session.execute(query),
                timeout=settings.RETRIEVAL_VECTOR_SEARCH_TIMEOUT,
            )
        except TimeoutError:
            logfire.warning(
                "vector_index.search.timeout",
                candidates=len(id_allowlist),
                timeout=settings.RETRIEVAL_VECTOR_SEARCH_TIMEOUT,
            )
            # Import here to avoid circular import (vector_index ← pipeline)
            from src.retrieval.pipeline import RetrievalError
            raise RetrievalError(
                f"Vector search timed out after {settings.RETRIEVAL_VECTOR_SEARCH_TIMEOUT}s"
            ) from None
        return [VectorSearchResult(id=row[0], score=float(row[1])) for row in result.all()]


# Backward-compatible module-level helper for call sites that don't need a session
# (e.g. tests). Keeps the file's public surface small.
async def rebuild_index_from_postgres() -> int:
    """
    No-op retained for call-site compatibility.

    Embeddings live in Postgres permanently, so there is nothing to rebuild.
    This function exists so old callers (e.g. lifespan startup) can be removed
    without an import error in transit.
    """
    return 0
