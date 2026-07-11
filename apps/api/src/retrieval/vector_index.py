"""
retrieval/vector_index.py
--------------------------
Purpose:    Thin wrapper around Turbovec for dense vector search.
            Implements the ADR-002 pattern: Postgres produces an ID allowlist,
            Turbovec applies it inside its scoring kernel (not a post-filter).
Dependencies: turbovec (install separately: pip install turbovec)
Scope:      Index operations only — upsert, search. No metadata here;
            metadata lives in Postgres (schema.md invariant).

ADR-002: Postgres is authoritative. If Turbovec and Postgres disagree,
rebuild Turbovec from Postgres. VectorIndex must never be the source of truth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import logfire

logger = logging.getLogger(__name__)


# ponytail: minimal protocol for untyped turbovec library
class _TurbovecResult(Protocol):
    id: str
    score: float


class _TurbovecIndex(Protocol):
    def upsert(self, id: str, vector: list[float]) -> None: ...
    def search(self, query: list[float], *, allowlist: list[str], top_k: int) -> list[_TurbovecResult]: ...
    def delete(self, id: str) -> None: ...


@dataclass
class VectorSearchResult:
    """One result from a Turbovec dense search."""
    id: str            # turbovec_id — joins to chunks.turbovec_id in Postgres
    score: float       # cosine similarity (higher = more relevant)


class VectorIndex:
    """
    Wrapper around Turbovec's in-process vector index.
    One instance per application process; backed by Turbovec's SIMD engine.

    ponytail: Turbovec is a library, not a service — no connection management needed.
    The index is loaded into memory on first use. For persistence across restarts,
    Turbovec must be rebuilt from Postgres (schema.md: Postgres is authoritative).
    """

    def __init__(self) -> None:
        try:
            import turbovec  # type: ignore[import-untyped]
            self._index: _TurbovecIndex | None = turbovec.Index()
            self._turbovec: Any = turbovec
            logger.info("vector_index: Turbovec loaded")
        except ImportError:
            # Dev fallback — numpy cosine similarity
            # ponytail: remove this once turbovec is installed everywhere; it's slow at scale
            logger.warning(
                "vector_index: turbovec not installed — using numpy fallback. "
                "Run `pip install turbovec` for production use."
            )
            self._index = None
            self._turbovec = None
            self._fallback_store: dict[str, list[float]] = {}

    def upsert(self, id: str, vector: list[float]) -> None:
        """Insert or update a vector. Called once per chunk during ingestion stage 6."""
        if self._turbovec:
            self._index.upsert(id, vector)
        else:
            self._fallback_store[id] = vector

    def search(
        self,
        query_vector: list[float],
        *,
        id_allowlist: list[str],
        top_k: int = 20,
    ) -> list[VectorSearchResult]:
        """
        Dense vector search filtered to id_allowlist.
        The allowlist comes from Postgres metadata pre-filter (retrieval.md stage 2).
        Filtering happens inside Turbovec's scoring kernel — not as a post-filter pass.
        """
        with logfire.span("vector_index.search", candidates=len(id_allowlist), top_k=top_k):
            if self._turbovec:
                # Turbovec native: allowlist filters inside the SIMD scoring kernel
                raw = self._index.search(query_vector, allowlist=id_allowlist, top_k=top_k)
                return [VectorSearchResult(id=r.id, score=r.score) for r in raw]
            else:
                return self._numpy_search(query_vector, id_allowlist=id_allowlist, top_k=top_k)

    def delete(self, id: str) -> None:
        """Remove a vector. Called if a chunk is deleted from Postgres."""
        if self._turbovec:
            self._index.delete(id)
        else:
            _ = self._fallback_store.pop(id, None)

    # ── Numpy fallback (dev only) ─────────────────────────────────────────
    def _numpy_search(
        self, query: list[float], *, id_allowlist: list[str], top_k: int
    ) -> list[VectorSearchResult]:
        import numpy as np

        if not self._fallback_store:
            return []

        allowed = {k: v for k, v in self._fallback_store.items() if k in set(id_allowlist)}
        if not allowed:
            return []

        q = np.array(query)
        q = q / (np.linalg.norm(q) + 1e-9)

        scores: list[tuple[str, float]] = []
        for id_, vec in allowed.items():
            v = np.array(vec)
            v = v / (np.linalg.norm(v) + 1e-9)
            scores.append((id_, float(np.dot(q, v))))

        scores.sort(key=lambda x: x[1], reverse=True)
        return [VectorSearchResult(id=id_, score=s) for id_, s in scores[:top_k]]


# Module-level singleton — one index per process
# ponytail: for multi-process deployments, ensure turbovec supports shared memory
#           or use a separate vector service. For MVP single-process this is fine.
_index: VectorIndex | None = None


def get_vector_index() -> VectorIndex:
    global _index
    if _index is None:
        _index = VectorIndex()
    return _index


async def rebuild_index_from_postgres() -> int:
    """
    Rebuild the vector index from Postgres chunks.
    Call this on startup or when the index is empty.
    
    Returns the number of vectors rebuilt.
    
    ponytail: simple async rebuild — loads all chunks and their embeddings.
    For large datasets, this should be done in batches or in the background.
    """
    from sqlalchemy import select
    from src.shared.database import SessionLocal
    from src.ingestion.models import Chunk
    from src.retrieval.embedder import embed_texts
    
    index = get_vector_index()
    
    # Always rebuild - ensures embeddings match current model
    logger.info("vector_index: rebuilding from Postgres...")
    
    async with SessionLocal() as session:
        result = await session.execute(select(Chunk))
        chunks = result.scalars().all()
        
        if not chunks:
            logger.warning("vector_index: no chunks found in Postgres")
            return 0
        
        # Clear existing index to avoid dimension mismatches
        if index._turbovec is None and index._fallback_store:
            index._fallback_store.clear()
        
        # Re-embed all chunks
        # ponytail: could store embeddings in Postgres to avoid re-embedding
        # but that's a schema change. For now, re-embed on startup.
        texts = [chunk.text for chunk in chunks]
        vectors = await embed_texts(texts)
        
        for chunk, vector in zip(chunks, vectors, strict=True):
            index.upsert(chunk.turbovec_id, vector)
        
        logger.info(f"vector_index: rebuilt {len(chunks)} vectors from Postgres")
        return len(chunks)