"""
retrieval/pipeline.py
---------------------
Hybrid retrieval pipeline: HyDE rewrite, dense+PostgreSQL FTS fusion, rerank.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import logfire
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.models import Chunk, Document
from src.observability.setup import traced_observation
from src.retrieval.embedder import embed_query, rerank
from src.retrieval.vector_index import VectorSearchResult, vector_search
from src.shared.model_gateway import ModelGatewayError, complete

logger = logging.getLogger(__name__)

_CANDIDATE_POOL = 40
_TOP_K_FINAL = 8
# A single long document can flood the top slots after rerank. Capping how many
# chunks any one document contributes forces the answer to draw from multiple
# sources — better diversity, less source bias.
_MAX_CHUNKS_PER_DOCUMENT = 3


class RetrievalError(Exception):
    """Internal retrieval pipeline failure (not a model-provider error)."""


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    chunk_text: str
    source_ref: str
    relevance_score: float
    position: int = 0


async def retrieve(
    question: str,
    workspace_id: uuid.UUID,
    session: AsyncSession,
    *,
    top_k: int = _TOP_K_FINAL,
) -> list[RetrievedChunk]:
    try:
        # Root observation for standalone retrieval calls (HyDE generation,
        # embed/rerank children nest under it via the shared OTel context).
        with (
            traced_observation(
                "retrieve-context",
                input={"question": question},
                metadata={"workspace_id": str(workspace_id)},
            ) as observation,
            logfire.span("retrieval.pipeline", workspace_id=str(workspace_id)),
        ):
            expanded = await _hyde_expand(question)
            candidates = await _hybrid_search(expanded, workspace_id, session, pool=_CANDIDATE_POOL)
            if not candidates:
                logfire.info("retrieval.no_candidates", workspace_id=str(workspace_id))
                observation.update(output={"chunks": 0})
                return []

            ranked = await _rerank_candidates(question, candidates)
            selected = _dedup_and_select(ranked, top_k)
            observation.update(
                output={"chunks": len(selected)},
                metadata={
                    "workspace_id": str(workspace_id),
                    "candidates": len(candidates),
                },
            )
            return selected
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
    fts_results = await _fts_search(query, id_allowlist, session, top_k=pool)
    fused_ids = _reciprocal_rank_fusion(dense_results, fts_results, pool=pool)
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


async def _fts_search(
    query: str,
    id_allowlist: list[str],
    session: AsyncSession,
    *,
    top_k: int,
) -> list[tuple[str, float]]:
    """PostgreSQL Full-Text Search over the GIN-backed `tsv` column.

    `ts_rank_cd` is PostgreSQL's cover-density ranking — not BM25. The
    generated `chunks.tsv` column is indexed, so no `to_tsvector()` is
    recomputed per query.
    """
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
    fts: list[tuple[str, float]],
    *,
    pool: int,
    k: int = 60,
) -> list[str]:
    scores: dict[str, float] = {}

    for rank, result in enumerate(dense, start=1):
        scores[result.id] = scores.get(result.id, 0.0) + 1.0 / (k + rank)

    for rank, (turbovec_id, _) in enumerate(fts, start=1):
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
                position=chunk.position,
            )
        )
    return hydrated


def _build_source_ref(doc: Document, chunk: Chunk) -> str:
    page = chunk.chunk_metadata.get("page") or chunk.position
    return f"{doc.filename}, chunk {page}"


async def _rerank_candidates(
    question: str, candidates: list[RetrievedChunk]
) -> list[RetrievedChunk]:
    scores = await rerank(question, [candidate.chunk_text for candidate in candidates])
    for candidate, score in zip(candidates, scores, strict=True):
        candidate.relevance_score = score
    return sorted(candidates, key=lambda candidate: candidate.relevance_score, reverse=True)


def _dedup_and_select(ranked: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
    """Dedup near-duplicate chunks and cap per-document dominance.

    Two overlapping chunks from the same document (adjacent positions) often
    rerank next to each other — both would reach the model with near-identical
    text, wasting context budget. We keep the higher-ranked one and drop its
    neighbours. A per-document cap then forces source diversity so one long
    document can't monopolize every slot.
    """
    selected: list[RetrievedChunk] = []
    # Positions already kept per document, for adjacent-dedup.
    kept_positions: dict[str, set[int]] = {}
    doc_counts: dict[str, int] = {}

    for chunk in ranked:
        positions = kept_positions.setdefault(chunk.document_id, set())
        if any(abs(chunk.position - kept) <= 1 for kept in positions):
            continue
        if doc_counts.get(chunk.document_id, 0) >= _MAX_CHUNKS_PER_DOCUMENT:
            continue
        positions.add(chunk.position)
        doc_counts[chunk.document_id] = doc_counts.get(chunk.document_id, 0) + 1
        selected.append(chunk)
        if len(selected) >= top_k:
            break

    logfire.info(
        "retrieval.selection",
        input=len(ranked),
        output=len(selected),
        documents=len(doc_counts),
    )
    return selected
