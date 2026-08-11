"""
retrieval/pipeline.py
---------------------
Hybrid retrieval pipeline: HyDE rewrite, dense+keyword fusion, rerank.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import logfire
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.models import Chunk, Document
from src.retrieval.embedder import embed_query, rerank
from src.retrieval.vector_index import VectorSearchResult, vector_search
from src.shared.model_gateway import ModelGatewayError, complete

logger = logging.getLogger(__name__)

_CANDIDATE_POOL = 40
_TOP_K_FINAL = 8


class RetrievalError(Exception):
    """Internal retrieval pipeline failure (not a model-provider error)."""


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    chunk_text: str
    source_ref: str
    relevance_score: float


async def retrieve(
    question: str,
    workspace_id: uuid.UUID,
    session: AsyncSession,
    *,
    top_k: int = _TOP_K_FINAL,
) -> list[RetrievedChunk]:
    try:
        with logfire.span("retrieval.pipeline", workspace_id=str(workspace_id)):
            expanded = await _hyde_expand(question)
            candidates = await _hybrid_search(expanded, workspace_id, session, pool=_CANDIDATE_POOL)
            if not candidates:
                logfire.info("retrieval.no_candidates", workspace_id=str(workspace_id))
                return []

            ranked = await _rerank_candidates(question, candidates)
            return ranked[:top_k]
    except Exception as exc:
        # Model-provider failures bubble up as typed gateway errors so routers
        # can map them to PROVIDER_ERROR / RATE_LIMIT. Everything else is an
        # internal retrieval failure.
        if isinstance(exc, ModelGatewayError):
            raise
        raise RetrievalError(f"Retrieval pipeline failed: {exc}") from exc


async def _hyde_expand(question: str) -> str:
    prompt = [
        {
            "role": "system",
            "content": (
                "Write a concise hypothetical answer to the user's question as if the "
                "relevant document were available. Keep it factual and 2-3 sentences."
            ),
        },
        {"role": "user", "content": question},
    ]
    return await complete(prompt, temperature=0.1, max_tokens=256)


async def _hybrid_search(
    query: str,
    workspace_id: uuid.UUID,
    session: AsyncSession,
    *,
    pool: int,
) -> list[RetrievedChunk]:
    id_allowlist = await _get_workspace_chunk_ids(workspace_id, session)
    if not id_allowlist:
        return []

    query_vector = await embed_query(query)
    dense_results = await vector_search(
        query_vector, id_allowlist=id_allowlist, top_k=pool, session=session
    )
    bm25_results = await _bm25_search(query, id_allowlist, session, top_k=pool)
    fused_ids = _reciprocal_rank_fusion(dense_results, bm25_results, pool=pool)
    return await _hydrate_chunks(fused_ids, session)


async def _get_workspace_chunk_ids(
    workspace_id: uuid.UUID,
    session: AsyncSession,
) -> list[str]:
    result = await session.execute(
        select(Chunk.turbovec_id)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.workspace_id == workspace_id)
    )
    return [row[0] for row in result.all()]


async def _bm25_search(
    query: str,
    id_allowlist: list[str],
    session: AsyncSession,
    *,
    top_k: int,
) -> list[tuple[str, float]]:
    ts_query = func.plainto_tsquery("english", query)
    rank = func.ts_rank_cd(Chunk.tsv, ts_query)

    result = await session.execute(
        select(Chunk.turbovec_id, rank.label("rank"))
        .where(Chunk.turbovec_id.in_(id_allowlist))
        .where(Chunk.tsv.op("@@")(ts_query))
        .order_by(desc("rank"))
        .limit(top_k)
    )
    return [(row[0], float(row[1])) for row in result.all()]


def _reciprocal_rank_fusion(
    dense: list[VectorSearchResult],
    bm25: list[tuple[str, float]],
    *,
    pool: int,
    k: int = 60,
) -> list[str]:
    scores: dict[str, float] = {}

    for rank, result in enumerate(dense, start=1):
        scores[result.id] = scores.get(result.id, 0.0) + 1.0 / (k + rank)

    for rank, (turbovec_id, _) in enumerate(bm25, start=1):
        scores[turbovec_id] = scores.get(turbovec_id, 0.0) + 1.0 / (k + rank)

    return sorted(scores, key=lambda item: scores[item], reverse=True)[:pool]


async def _hydrate_chunks(turbovec_ids: list[str], session: AsyncSession) -> list[RetrievedChunk]:
    if not turbovec_ids:
        return []

    result = await session.execute(
        select(Chunk, Document)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.turbovec_id.in_(turbovec_ids))
    )
    rows = result.all()
    row_by_id = {chunk.turbovec_id: (chunk, doc) for chunk, doc in rows}

    hydrated: list[RetrievedChunk] = []
    for turbovec_id in turbovec_ids:
        row = row_by_id.get(turbovec_id)
        if row is None:
            continue
        chunk, doc = row
        hydrated.append(
            RetrievedChunk(
                chunk_id=str(chunk.id),
                document_id=str(doc.id),
                chunk_text=chunk.text,
                source_ref=_build_source_ref(doc, chunk),
                relevance_score=0.0,
            )
        )
    return hydrated


def _build_source_ref(doc: Document, chunk: Chunk) -> str:
    page = chunk.chunk_metadata.get("page") or chunk.position
    return f"{doc.filename}, chunk {page}"


async def _rerank_candidates(question: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
    scores = await rerank(question, [candidate.chunk_text for candidate in candidates])
    for candidate, score in zip(candidates, scores, strict=True):
        candidate.relevance_score = score
    return sorted(candidates, key=lambda candidate: candidate.relevance_score, reverse=True)
