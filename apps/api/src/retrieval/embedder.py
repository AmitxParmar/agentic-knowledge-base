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

import asyncio
import hashlib
import logging
import struct
from typing import Any

import logfire

from app.settings import settings
from src.shared.rate_limit import embed_semaphore
from src.shared.retry import with_retry

logger = logging.getLogger(__name__)

_EMBED_DIM = settings.EMBEDDING_DIM
_EMBED_BATCH_SIZE = settings.EMBED_BATCH_SIZE


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


async def embed_texts(
    texts: list[str],
    *,
    input_type: str = "search_document",
) -> list[list[float]]:
    """Embed a batch of texts using Cohere embed-v3.

    input_type tunes how Cohere scales the vectors (search_document for
    stored text, search_query for a user question). Falls back to local
    hash-based embedding if Cohere is unavailable (dev / missing key).

    Processes texts in batches of EMBED_BATCH_SIZE to respect Cohere's
    96-text limit per request.
    """
    all_vectors: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[i : i + _EMBED_BATCH_SIZE]
        vectors = await _embed_batch(batch, input_type)
        all_vectors.extend(vectors)
    return all_vectors


async def _embed_batch(texts: list[str], input_type: str) -> list[list[float]]:
    """Embed a single batch of texts using Cohere embed-v3."""
    async def _do_embed() -> list[list[float]]:
        return await asyncio.wait_for(
            _embed_once(texts, input_type),
            timeout=settings.RETRIEVAL_EMBED_TIMEOUT,
        )

    try:
        return await with_retry(
            _do_embed,
            max_attempts=settings.RETRY_MAX_ATTEMPTS,
            base_delay=settings.RETRY_BASE_DELAY,
            max_delay=settings.RETRY_MAX_DELAY,
            retryable_exceptions=(
                asyncio.TimeoutError,
                ConnectionError,
                IOError,
                OSError,
            ),
        )
    except TimeoutError:
        logger.warning("embedder: embedding timed out after %ss", settings.RETRIEVAL_EMBED_TIMEOUT)
        logfire.warning("embedder.embed.timeout", batch_size=len(texts))
        return _local_embed(texts)
    except Exception:
        logger.warning("embedder: Cohere embedding unavailable, using local fallback")
        logfire.warning("embedder.embed.fallback", provider="local_hash", reason="Cohere unreachable")
        return _local_embed(texts)


async def _embed_once(texts: list[str], input_type: str) -> list[list[float]]:
    async with embed_semaphore():
        with logfire.span("embedder.embed", batch_size=len(texts), input_type=input_type):
            resp = await _get_client().embed(
                model=settings.COHERE_EMBED_MODEL,
                input_type=input_type,
                texts=texts,
                embedding_types=["float"],
            )
            vectors = resp.embeddings.float_
            logfire.info(
                "embedder.embed.ok",
                provider="cohere",
                vectors=len(vectors),
                dim=len(vectors[0]) if vectors else 0,
            )
            return [list(vector) for vector in vectors]


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
    async def _do_rerank() -> list[float]:
        return await asyncio.wait_for(
            _rerank_once(query, passages, top_k),
            timeout=settings.RETRIEVAL_RERANK_TIMEOUT,
        )

    try:
        return await with_retry(
            _do_rerank,
            max_attempts=settings.RETRY_MAX_ATTEMPTS,
            base_delay=settings.RETRY_BASE_DELAY,
            max_delay=settings.RETRY_MAX_DELAY,
            retryable_exceptions=(
                asyncio.TimeoutError,
                ConnectionError,
                IOError,
                OSError,
            ),
        )
    except TimeoutError:
        logger.warning("rerank: timed out after %ss", settings.RETRIEVAL_RERANK_TIMEOUT)
        logfire.warning("embedder.rerank.timeout", passages=len(passages))
        return await _cosine_fallback(query, passages)
    except Exception:
        logger.warning("Cohere reranker unavailable, using cosine fallback")
        logfire.warning("embedder.rerank.fallback", provider="cosine", reason="Cohere unreachable")
        return await _cosine_fallback(query, passages)


async def _rerank_once(query: str, passages: list[str], top_k: int | None) -> list[float]:
    with logfire.span("embedder.rerank", passages=len(passages)):
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

        logfire.info("embedder.rerank.ok", provider="cohre", passages=len(passages))
        return scores


async def _cosine_fallback(query: str, passages: list[str]) -> list[float]:
    embeddings = await embed_texts([query, *passages], input_type="search_query")
    query_emb, passage_embs = embeddings[0], embeddings[1:]
    return [_cosine_similarity(query_emb, emb) for emb in passage_embs]
