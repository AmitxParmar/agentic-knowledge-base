"""
retrieval/embedder.py
---------------------
Purpose:    Embedding and reranking clients backed by Cohere.
        Embeddings use Cohere embed-v3 (1024 dims). Reranking uses
        Cohere rerank-v3, a real cross-encoder.
Dependencies: cohere, settings
Scope:      embed_texts() → vectors, embed_query() → vector, rerank() → scores.
Fallback:   `ALLOW_EMBEDDING_FALLBACK` (default false) — when false a provider
        failure raises `EmbeddingError` and fails ingestion loudly instead of
        persisting hash/cosine vectors. Dev-only escape hatch for no-key runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import struct
from time import monotonic
from typing import Any

import logfire

from app.settings import settings
from src.observability.setup import traced_observation
from src.shared.rate_limit import embed_semaphore
from src.shared.retry import with_retry

logger = logging.getLogger(__name__)

_EMBED_DIM = settings.EMBEDDING_DIM
_EMBED_BATCH_SIZE = settings.EMBED_BATCH_SIZE


class EmbeddingError(Exception):
    """Provider-agnostic embedding/rerank failure. Raised when the provider is
    unreachable AND fallback is disabled, so ingestion fails loudly instead of
    persisting semantically-meaningless fallback vectors into the index."""


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
        if settings.ALLOW_EMBEDDING_FALLBACK:
            return _local_embed(texts)
        raise EmbeddingError("Embedding timed out and fallback is disabled") from None
    except Exception as exc:
        logger.warning("embedder: Cohere embedding unavailable, using local fallback")
        logfire.warning(
            "embedder.embed.fallback", provider="local_hash", reason="Cohere unreachable"
        )
        if settings.ALLOW_EMBEDDING_FALLBACK:
            return _local_embed(texts)
        raise EmbeddingError(f"Embedding provider unavailable: {exc}") from exc


async def _embed_once(texts: list[str], input_type: str) -> list[list[float]]:
    async with embed_semaphore():
        # Counts, not raw texts — ingestion batches can carry hundreds of
        # chunks and the vectors themselves are the payload here.
        with (
            traced_observation(
                "embed-texts",
                as_type="embedding",
                input={"batch_size": len(texts), "input_type": input_type},
                metadata={"model": settings.COHERE_EMBED_MODEL},
            ) as observation,
            logfire.span("embedder.embed", batch_size=len(texts), input_type=input_type),
        ):
            resp = await _get_client().embed(
                model=settings.COHERE_EMBED_MODEL,
                input_type=input_type,
                texts=texts,
                embedding_types=["float"],
            )
            vectors = resp.embeddings.float_
            dim = len(vectors[0]) if vectors else 0
            observation.update(output={"vectors": len(vectors), "dimensions": dim})
            logfire.info(
                "embedder.embed.ok",
                provider="cohere",
                vectors=len(vectors),
                dim=dim,
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
        if settings.ALLOW_EMBEDDING_FALLBACK:
            return await _cosine_fallback(query, passages)
        raise EmbeddingError("Rerank timed out and fallback is disabled") from None
    except Exception as exc:
        logger.warning("Cohere reranker unavailable, using cosine fallback")
        logfire.warning("embedder.rerank.fallback", provider="cosine", reason="Cohere unreachable")
        if settings.ALLOW_EMBEDDING_FALLBACK:
            return await _cosine_fallback(query, passages)
        raise EmbeddingError(f"Rerank provider unavailable: {exc}") from exc


async def _rerank_once(query: str, passages: list[str], top_k: int | None) -> list[float]:
    with (
        traced_observation(
            "rerank-passages",
            as_type="retriever",
            input={"query": query, "passages": len(passages)},
            metadata={"model": settings.COHERE_RERANK_MODEL},
        ) as observation,
        logfire.span("embedder.rerank", passages=len(passages)),
    ):
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

        observation.update(
            output={"scores": len(scores), "top_score": max(scores) if scores else None}
        )
        logfire.info("embedder.rerank.ok", provider="cohre", passages=len(passages))
        return scores


async def _cosine_fallback(query: str, passages: list[str]) -> list[float]:
    embeddings = await embed_texts([query, *passages], input_type="search_query")
    query_emb, passage_embs = embeddings[0], embeddings[1:]
    return [_cosine_similarity(query_emb, emb) for emb in passage_embs]


# ── Readiness probe ──────────────────────────────────────────────────────────

_HEALTH_TTL_SECONDS = 60.0
_PROBE_TIMEOUT_SECONDS = 5.0
_health_cache: tuple[float, str] | None = None


async def health_check() -> str:
    """Cheap readiness probe for the embedding dependency.

    Returns "ok", "skipped (dev fallback)", "unconfigured", or
    "error: <ExcName>". A successful result is cached for 60s so frequent
    readiness probes don't burn Cohere quota; failures are re-probed each
    call so recovery is detected on the next probe.
    """
    global _health_cache

    if not settings.COHERE_API_KEY:
        if settings.ALLOW_EMBEDDING_FALLBACK:
            return "skipped (dev fallback)"
        return "unconfigured"

    now = monotonic()
    if _health_cache is not None:
        cached_at, cached_status = _health_cache
        if cached_status == "ok" and now - cached_at < _HEALTH_TTL_SECONDS:
            return cached_status

    status = "ok"
    try:
        await asyncio.wait_for(embed_query("healthcheck"), timeout=_PROBE_TIMEOUT_SECONDS)
    except Exception as exc:
        status = f"error: {type(exc).__name__}"
        logger.warning("embedder.health_check failed: %s", exc)
    _health_cache = (now, status)
    return status
