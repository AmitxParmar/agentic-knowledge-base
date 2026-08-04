"""
retrieval/embedder.py
---------------------
    Purpose:    Embedding and reranking clients backed by Cohere.
            Embeddings use Cohere embed-v3 (1024 dims). Reranking uses
            Cohere rerank-v3, a real cross-encoder — replacing the old
            LM Studio / similarity fallback stack.
Dependencies: cohere, settings
Scope:      embed_texts() → vectors, embed_query() → vector, rerank() → scores.
"""

from __future__ import annotations

import hashlib
import logging
import struct
from typing import Any

import logfire

from app.settings import settings

logger = logging.getLogger(__name__)

_EMBED_DIM = settings.EMBEDDING_DIM


def _cohere_client() -> Any:
    """Lazily build the async Cohere client. Uses the global API key."""
    from cohere import AsyncClientV2

    return AsyncClientV2(api_key=settings.COHERE_API_KEY)


# Module-level singleton — one client per process (connection pooling).
_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is None:
        _client = _cohere_client()
    return _client


def _local_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic hash-based embedding fallback. Not semantically meaningful
    but lets the pipeline complete end-to-end for testing without a Cohere key.

    Produces exactly EMBEDDING_DIM floats so vectors always match the
    chunks.embedding column dimensionality.
    """
    vectors: list[list[float]] = []
    for text in texts:
        h = hashlib.sha256(text.encode()).digest()
        needed = _EMBED_DIM * 4  # 4 bytes per float32
        buf = (h * (needed // len(h) + 1))[:needed]
        raw = struct.unpack(f"{_EMBED_DIM}f", buf)
        norm = sum(v * v for v in raw) ** 0.5 or 1.0
        vectors.append([v / norm for v in raw])
    return vectors


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def embed_texts(texts: list[str], *, input_type: str = "search_document") -> list[list[float]]:
    """Embed a batch of texts using Cohere embed-v3.

    input_type tunes how Cohere scales the vectors (search_document for
    stored text, search_query for a user question). Falls back to local
    hash-based embedding if Cohere is unavailable (dev / missing key).
    """
    with logfire.span("embedder.embed", batch_size=len(texts), input_type=input_type):
        try:
            resp = await _get_client().embed(
                model=settings.COHERE_EMBED_MODEL,
                input_type=input_type,
                texts=texts,
                embedding_types=["float"],
            )
            vectors = resp.embeddings.float_
            logfire.info(
                "embedder.ok",
                provider="cohere",
                vectors=len(vectors),
                dim=len(vectors[0]) if vectors else 0,
            )
            return [list(vector) for vector in vectors]
        except Exception:
            logger.warning("Cohere embedding unavailable, using local fallback")
            logfire.warning("embedder.fallback", provider="local_hash", reason="Cohere unreachable")
            return _local_embed(texts)


async def embed_query(query: str) -> list[float]:
    """Embed a single user query. Uses search_query input type for Cohere."""
    vectors = await embed_texts([query], input_type="search_query")
    return vectors[0]


async def rerank(query: str, passages: list[str], *, top_k: int | None = None) -> list[float]:
    """
    Rerank passages against a query using Cohere's cross-encoder reranker.

    Returns one relevance score per passage, same order as input. Higher is
    more relevant. Falls back to cosine-similarity between query and passage
    embeddings if Cohere is unavailable.
    """
    with logfire.span("embedder.rerank", passages=len(passages)):
        try:
            resp = await _get_client().rerank(
                model=settings.COHERE_RERANK_MODEL,
                query=query,
                documents=passages,
                top_n=top_k or len(passages),
            )

            # Cohere returns results sorted by relevance; map back to input order.
            scores = [0.0] * len(passages)
            for item in resp.results:
                scores[item.index] = item.relevance_score

            logfire.info("embedder.rerank.ok", provider="cohere", passages=len(passages))
            return scores
        except Exception:
            logger.warning("Cohere reranker unavailable, using cosine fallback")
            logfire.warning("embedder.rerank.fallback", provider="cosine", reason="Cohere unreachable")
            embeddings = await embed_texts([query, *passages], input_type="search_query")
            query_emb, passage_embs = embeddings[0], embeddings[1:]
            return [_cosine_similarity(query_emb, emb) for emb in passage_embs]
