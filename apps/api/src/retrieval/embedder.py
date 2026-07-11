"""
retrieval/embedder.py
---------------------
Purpose:    Embedding and reranking clients using LM Studio's OpenAI-compatible API.
            Embeddings use /v1/embeddings endpoint.
            Reranking uses embedding similarity as fallback (LM Studio lacks /v1/rerank).
Dependencies: httpx, settings
Scope:      Embed texts → vectors. Rerank (query, passages) → scores.
"""

from __future__ import annotations

import hashlib
import logging
import struct
from typing import Any

import httpx
import logfire

from app.settings import settings

logger = logging.getLogger(__name__)

# Shared async client — reused across calls (connection pooling)
_http = httpx.AsyncClient(timeout=60.0)

_EMBED_DIM = 768


def _local_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic hash-based embedding fallback. Not semantically meaningful
    but lets the pipeline complete end-to-end for testing without LM Studio."""
    vectors: list[list[float]] = []
    for text in texts:
        h = hashlib.sha256(text.encode()).digest()
        needed = _EMBED_DIM  # 768 bytes for 192 floats
        buf = (h * (needed // len(h) + 1))[:needed]
        raw = struct.unpack(f"{_EMBED_DIM // 4}f", buf)
        norm = sum(v * v for v in raw) ** 0.5 or 1.0
        vectors.append([v / norm for v in raw])
    return vectors


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using LM Studio's OpenAI-compatible /v1/embeddings.
    Falls back to local hash-based embedding if LM Studio is unavailable."""
    with logfire.span("embedder.embed", batch_size=len(texts)):
        try:
            resp = await _http.post(
                f"{settings.LM_STUDIO_BASE_URL}/v1/embeddings",
                json={
                    "input": texts,
                    "model": settings.LM_STUDIO_EMBEDDING_MODEL,
                },
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            # Sort by index to maintain order
            data.sort(key=lambda x: x["index"])
            logfire.info("embedder.ok", provider="lm_studio", vectors=len(data), dim=len(data[0]["embedding"]))
            return [item["embedding"] for item in data]
        except Exception:
            logger.warning("LM Studio unavailable, using local embedding fallback")
            logfire.warning("embedder.fallback", provider="local_hash", reason="LM Studio unreachable")
            return _local_embed(texts)


async def embed_query(query: str) -> list[float]:
    """Embed a single query string. Thin wrapper around embed_texts."""
    vectors = await embed_texts([query])
    return vectors[0]


async def rerank(query: str, passages: list[str], *, top_k: int | None = None) -> list[float]:
    """
    Rerank passages against a query using embedding similarity.
    LM Studio's reranker model doesn't expose a /v1/rerank endpoint,
    so we compute cosine similarity between query and passage embeddings.
    Returns one relevance score per passage, same order as input.
    Higher is more relevant.
    """
    with logfire.span("embedder.rerank", passages=len(passages)):
        try:
            # Embed query and all passages together
            all_texts = [query] + passages
            embeddings = await embed_texts(all_texts)
            query_emb = embeddings[0]
            passage_embs = embeddings[1:]

            # Compute cosine similarity scores
            scores = [_cosine_similarity(query_emb, emb) for emb in passage_embs]
            logfire.info("embedder.rerank.ok", provider="lm_studio_similarity", passages=len(passages))

            if top_k is not None:
                # Return scores for top_k passages, 0 for the rest
                indexed = list(enumerate(scores))
                indexed.sort(key=lambda x: x[1], reverse=True)
                result = [0.0] * len(passages)
                for idx, score in indexed[:top_k]:
                    result[idx] = score
                return result

            return scores
        except Exception:
            logger.warning("LM Studio reranker unavailable, returning uniform scores")
            logfire.warning("embedder.rerank.fallback", provider="uniform", reason="LM Studio unreachable")
            return [1.0] * len(passages)
