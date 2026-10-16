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
from src.shared.model_gateway import ModelGatewayError, complete_with_tools
from src.shared.prompts import get_prompt
from src.shared.retrieval_cache import get_cached_chunks, store_chunks

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
    # Surrounding sibling text (adjacent positions, same document), attached
    # post-selection so fragment hits still carry their full local context.
    # Rides inside the SAME citation block when packed - never cited separately.
    context_text: str = ""


async def retrieve(
    question: str,
    workspace_id: uuid.UUID,
    session: AsyncSession,
    *,
    top_k: int = _TOP_K_FINAL,
) -> tuple[list[RetrievedChunk], int]:
    """Run the pipeline, returning (selected chunks, HyDE LLM tokens spent).

    The token count lets callers meter the full run — HyDE generation is an
    LLM call whose usage would otherwise vanish from cost accounting.
    """
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
            candidates, selected, hyde_tokens = await retrieve_with_ablation(
                question, workspace_id, session, top_k=top_k
            )
            if not candidates:
                logfire.info("retrieval.no_candidates", workspace_id=str(workspace_id))
            observation.update(
                output={"chunks": len(selected)},
                metadata={
                    "workspace_id": str(workspace_id),
                    "candidates": len(candidates),
                },
            )
            return selected, hyde_tokens
    except Exception as exc:
        # Model-provider failures bubble up as typed gateway errors so routers
        # can map them to PROVIDER_ERROR / RATE_LIMIT. Everything else is an
        # internal retrieval failure.
        if isinstance(exc, ModelGatewayError):
            raise
        raise RetrievalError(f"Retrieval pipeline failed: {exc}") from exc


async def retrieve_with_ablation(
    question: str,
    workspace_id: uuid.UUID,
    session: AsyncSession,
    *,
    pool: int = _CANDIDATE_POOL,
    top_k: int = _TOP_K_FINAL,
) -> tuple[list[RetrievedChunk], list[RetrievedChunk], int]:
    """Run the pipeline and return ranking stages plus HyDE LLM tokens.

    Returns ``(fusion_candidates, final_selection, hyde_tokens)``: the
    fusion-ordered candidate pool *before* reranking (RRF order), the
    post-rerank deduplicated final selection, and the LLM tokens spent on
    the HyDE rewrite (0 on cache hit or HyDE failure). The eval harness
    computes ΔNDCG between the two orders to verify the reranker actually
    improves relevance.

    A retrieval-cache hit returns the cached selection as both stages
    (the original fusion order is not cached — ΔNDCG for cached cases
    reads as 0, which is neutral for rerank verification).
    """
    cached = await get_cached_chunks(str(workspace_id), question)
    if cached is not None:
        chunks = [RetrievedChunk(**c) for c in cached]
        return chunks, chunks, 0

    expanded, hyde_tokens = await _hyde_expand(question)
    candidates = await _hybrid_search(expanded, workspace_id, session, pool=pool)
    if not candidates:
        return [], [], hyde_tokens

    ranked = await _rerank_candidates(question, candidates)
    selected = _dedup_and_select(ranked, top_k)
    await _attach_parent_context(selected, session)
    await store_chunks(
        str(workspace_id),
        question,
        [
            {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "chunk_text": c.chunk_text,
                "source_ref": c.source_ref,
                "relevance_score": c.relevance_score,
                "position": c.position,
                "context_text": c.context_text,
            }
            for c in selected
        ],
    )
    return candidates, selected, hyde_tokens


async def _hyde_expand(question: str) -> tuple[str, int]:
    """Rewrite the question as a hypothetical answer; return (text, LLM tokens).

    The prompt text is versioned (retrieval.hyde) and its revision travels
    to Langfuse with the generation. The token count lets callers meter the
    full run. Failures and empty generations fall back to the raw question
    with zero tokens spent.
    """
    hyde_prompt = get_prompt("retrieval.hyde")
    prompt = [
        {"role": "system", "content": hyde_prompt.text},
        {"role": "user", "content": question},
    ]
    try:
        response = await complete_with_tools(
            prompt,
            tools=None,
            route="small",
            temperature=0.1,
            max_tokens=256,
            prompt_version=hyde_prompt.label,
        )
    except Exception:
        logger.debug("HyDE expansion failed, falling back to original question", exc_info=True)
        return question, 0
    # Guard Cohere 400: an empty HyDE query would embed as [""] which Cohere
    # rejects outright (see embedder.py).
    expanded = response.content or ""
    if not expanded.strip():
        return question, 0
    tokens = getattr(response.usage, "total_tokens", 0) or 0
    return expanded, tokens


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


# ── Parent-context expansion (spec: retrieval.md - parent-child section) ─────

# Max chars of sibling context merged into one chunk's citation block.
# Sentence-bounded truncation keeps the merge extractive, not arbitrary.
_CONTEXT_MAX_CHARS = 1200
# Neighbors at position +/- this distance count as local context.
_CONTEXT_NEIGHBOR_RADIUS = 1


async def _attach_parent_context(selected: list[RetrievedChunk], session: AsyncSession) -> None:
    """Merge adjacent-sibling text into each selected chunk (in place).

    A rerank hit is often a fragment of its section. Pulling the chunk's
    immediate neighbors (same document, adjacent positions) gives the model
    the full local argument without adding new citations - the context rides
    inside the same [n] block, preserving the citation-at-retrieval contract.
    Best-effort: any DB failure leaves chunks unchanged.
    """
    if not selected:
        return
    try:
        doc_ids = {uuid.UUID(c.document_id) for c in selected}
        positions_by_doc: dict[uuid.UUID, set[int]] = {}
        result = await session.execute(
            select(Chunk.document_id, Chunk.position).where(Chunk.document_id.in_(doc_ids))
        )
        for doc_id, pos in result.all():
            positions_by_doc.setdefault(doc_id, set()).add(pos)

        wanted_positions: set[int] = {
            pos
            for chunk in selected
            for offset in range(-_CONTEXT_NEIGHBOR_RADIUS, _CONTEXT_NEIGHBOR_RADIUS + 1)
            for pos in [chunk.position + offset]
            if pos in positions_by_doc.get(uuid.UUID(chunk.document_id), set())
        }
        if not wanted_positions:
            return

        rows = await session.execute(
            select(Chunk)
            .where(
                Chunk.document_id.in_(doc_ids),
                Chunk.position.in_(wanted_positions),
            )
            .order_by(Chunk.document_id, Chunk.position)
        )
        siblings: dict[tuple[uuid.UUID, int], str] = {
            (row.document_id, row.position): row.text for row in rows.all()
        }

        for chunk in selected:
            doc_id = uuid.UUID(chunk.document_id)
            parts: list[str] = []
            total = 0
            for offset in range(-_CONTEXT_NEIGHBOR_RADIUS, _CONTEXT_NEIGHBOR_RADIUS + 1):
                if offset == 0:
                    continue  # the hit's own text is already packed separately
                text = siblings.get((doc_id, chunk.position + offset))
                if text is None:
                    continue
                truncated = _truncate_at_sentence_boundary(
                    text, remaining=_CONTEXT_MAX_CHARS - total
                )
                if not truncated:
                    continue
                parts.append(truncated)
                total += len(truncated) + len("\n...\n")
            context = "\n...\n".join(parts)
            # Don't duplicate what the hit itself already says: only attach
            # context when it adds material beyond the chunk's own text.
            normalized_own = " ".join(chunk.chunk_text.split()).lower()
            normalized_ctx = " ".join(context.split()).lower()
            if context and normalized_ctx not in normalized_own and not chunk.context_text:
                chunk.context_text = context
    except Exception:
        logger.debug("retrieval: parent-context expansion skipped", exc_info=True)


def _truncate_at_sentence_boundary(text: str, *, remaining: int) -> str:
    """Cut ``text`` to at most ``remaining`` chars, ending on a sentence end."""
    if remaining <= 0:
        return ""
    if len(text) <= remaining:
        return text.strip()
    window = text[:remaining]
    for punct in (". ", "! ", "? "):
        cut = window.rfind(punct)
        if cut > remaining // 2:
            return window[: cut + 1].strip()
    # No sentence boundary in range - hard cut at a word boundary.
    last_space = window.rfind(" ")
    return (window[:last_space] if last_space > remaining // 2 else window).strip()


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
