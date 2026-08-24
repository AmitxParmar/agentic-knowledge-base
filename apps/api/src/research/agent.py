"""
research/agent.py
-----------------
Composed research pipeline (docs/specs/research-pipeline.md):

    entry → planner → researcher ⇄ (ReAct loop) → synthesize → END

- planner:    cheap-model query decomposition; never fails a run.
- researcher: ReAct loop over the retrieval tool (spec: researcher.md).
- synthesize: owns final-answer generation (pass-through or forced
              best-effort at the iteration cap).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

import logfire
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings
from src.observability.setup import agent_run_trace
from src.research.checkpoint import get_saver
from src.research.models import Citation
from src.retrieval.pipeline import RetrievedChunk, retrieve
from src.shared.model_gateway import complete, complete_with_tools
from src.shared.progress import ResearchStage

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5

# Below this mean rerank score, retrieved chunks are deemed too tangential to
# support a grounded answer. Tuned conservatively — Cohere rerank scores
# relevant passages > 0.5 and near-irrelevant ones < 0.1, so 0.2 catches runs
# where nothing actually matched the question.
_RELEVANCE_THRESHOLD = 0.2

# Served when the agent retrieved nothing at all — the unambiguous fabrication
# risk. Hard-coded so a grounded refusal can never be overridden by the model.
_INSUFFICIENT_EVIDENCE_RESPONSE = (
    "I couldn't find sufficient evidence in your uploaded documents to answer "
    "this question. Try rephrasing it, or upload documents that cover this topic."
)


class AgentState(TypedDict):
    run_id: str
    workspace_id: str
    question: str
    plan: list[str]
    messages: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    answer: str | None
    iterations: int
    tokens_used: int


_RETRIEVAL_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "retrieve_evidence",
        "description": "Search the user's uploaded documents for supporting evidence.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The specific aspect of the question to search for.",
                }
            },
            "required": ["query"],
        },
    },
}

_SYSTEM_PROMPT = """\
You are a research assistant that answers questions strictly from the user's uploaded documents.

Rules:
- Use the retrieve_evidence tool before answering.
- Base every claim on retrieved evidence.
- If evidence is insufficient, say so clearly.
- Never fabricate facts.
- When you have enough evidence, answer directly without calling the tool again.
"""

_PLANNER_MAX_ASPECTS = 3

_PLANNER_PROMPT = """\
Decompose the user's question into 1-3 independent document-search queries. \
Each query targets one specific aspect that together fully cover the question. \
Respond with ONLY a JSON array of query strings — no other text. \
If the question is simple and single-faceted, return an array with one query."""


def _parse_plan(content: str | None) -> list[str]:
    """Parse the planner's JSON array output, tolerantly.

    Accepts plain or code-fenced arrays, caps at _PLANNER_MAX_ASPECTS,
    and drops empty/non-string entries. Returns [] on anything unparseable.
    """
    if not content:
        return []
    start = content.find("[")
    end = content.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        raw = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    queries = [q.strip() for q in raw if isinstance(q, str) and q.strip()]
    return queries[:_PLANNER_MAX_ASPECTS]


async def _planner_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Pre-node: decompose the question into search aspects.

    Best-effort by design (spec invariant): any provider error, timeout,
    or malformed output falls back to a single-step plan equal to the raw
    question, so planning can never break a run. Emits no progress stage —
    the fixed ux.md vocabulary is untouched; SEARCHING still fires on
    first retrieval inside the researcher node.
    """
    del config
    fallback = [state["question"]]
    try:
        response = await asyncio.wait_for(
            complete(
                [
                    {"role": "system", "content": _PLANNER_PROMPT},
                    {"role": "user", "content": state["question"]},
                ],
                temperature=0.0,
                max_tokens=200,
            ),
            timeout=settings.AGENT_ITERATION_TIMEOUT,
        )
        plan = _parse_plan(response)
    except Exception:
        logger.debug("research.planner failed — single-step fallback", exc_info=True)
        plan = []

    if not plan:
        plan = fallback

    logfire.info("research.plan", run_id=state["run_id"], aspects=len(plan))
    plan_message = {
        "role": "system",
        "content": "Search plan (cover these aspects):\n" + "\n".join(f"- {q}" for q in plan),
    }
    return {"plan": plan, "messages": state["messages"] + [plan_message]}


async def _researcher_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    configurable = config.get("configurable") or {}
    session: AsyncSession = configurable["_session"]
    callback = configurable.get("_stage_callback")

    response = await asyncio.wait_for(
        complete_with_tools(
            state["messages"],
            tools=[_RETRIEVAL_TOOL],
            temperature=0.1,
            max_tokens=2048,
        ),
        timeout=settings.AGENT_ITERATION_TIMEOUT,
    )

    if not response.tool_calls:
        return {
            "answer": response.content or "",
            "messages": state["messages"]
            + [{"role": "assistant", "content": response.content or ""}],
            "tokens_used": state["tokens_used"] + _msg_tokens(response),
        }

    if callback:
        await callback(ResearchStage.SEARCHING)

    workspace_id = uuid.UUID(state["workspace_id"])
    new_citations: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []

    for tool_call in response.tool_calls:
        query = tool_call.function.arguments.get("query", state["question"])
        with logfire.span("agent.retrieval_tool", query=query, iteration=state["iterations"]):
            chunks = await retrieve(query, workspace_id, session)

        for chunk in chunks:
            new_citations.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "source_ref": chunk.source_ref,
                    "relevance_score": chunk.relevance_score,
                }
            )

        tool_results.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": _format_chunks_for_model(chunks),
            }
        )

    if callback:
        await callback(ResearchStage.REVIEWING)

    assistant_tool_calls = [
        {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.function.name,
                "arguments": json.dumps(tool_call.function.arguments),
            },
        }
        for tool_call in response.tool_calls
    ]

    return {
        "messages": state["messages"]
        + [
            {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": assistant_tool_calls,
            }
        ]
        + tool_results,
        "citations": state["citations"] + new_citations,
        "iterations": state["iterations"] + 1,
        "tokens_used": state["tokens_used"] + _msg_tokens(response),
    }


async def _synthesize_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Final-answer node: pass-through, or forced best-effort generation.

    The researcher normally writes the answer itself when it stops calling
    tools. When instead the iteration cap exhausted the loop with no answer,
    this node makes exactly one grounded generation call (no tools) from
    whatever evidence was gathered — same prompt the inline path used.
    """
    del config
    if state.get("answer") is not None:
        return {}

    final_msg = await asyncio.wait_for(
        complete_with_tools(
            state["messages"]
            + [
                {
                    "role": "user",
                    "content": (
                        "You have reached the maximum number of searches. "
                        "Write the best answer you can from the gathered evidence. "
                        "If evidence is insufficient, say so."
                    ),
                }
            ],
            tools=None,
            max_tokens=2048,
        ),
        timeout=settings.AGENT_ITERATION_TIMEOUT,
    )
    return {
        "answer": final_msg.content or "Insufficient evidence to answer.",
        "messages": state["messages"],
        "tokens_used": state["tokens_used"] + _msg_tokens(final_msg),
    }


def _msg_tokens(response: Any) -> int:
    usage = getattr(response, "usage", None)
    return getattr(usage, "total_tokens", 0) or 0


def _route_after_research(state: AgentState) -> str:
    """Route to synthesize once an answer exists, iterations are spent, or
    the run's token budget is exhausted (maturity plan §7: hard cost caps)."""
    if state.get("answer") is not None:
        return "synthesize"
    if state["iterations"] >= MAX_ITERATIONS:
        return "synthesize"
    if state["tokens_used"] >= settings.AGENT_TOKEN_BUDGET:
        logfire.info(
            "research.token_budget_exceeded",
            run_id=state["run_id"],
            tokens_used=state["tokens_used"],
            budget=settings.AGENT_TOKEN_BUDGET,
        )
        return "synthesize"
    return "researcher"


def _build_graph(checkpointer: Any = None) -> Any:
    builder = StateGraph(AgentState)
    builder.add_node("planner", _planner_node)
    builder.add_node("researcher", _researcher_node)
    builder.add_node("synthesize", _synthesize_node)
    builder.set_entry_point("planner")
    builder.add_edge("planner", "researcher")
    builder.add_conditional_edges(
        "researcher",
        _route_after_research,
        {"researcher": "researcher", "synthesize": "synthesize"},
    )
    builder.add_edge("synthesize", END)
    return builder.compile(checkpointer=checkpointer)


@dataclass
class AgentResult:
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    iterations: int = 0
    tokens_used: int = 0
    confidence: Literal["sufficient", "insufficient"] = "sufficient"


_saver = None
_graph: Any = None


async def _get_saver() -> Any:
    """Lazily initialize the async Postgres checkpointer.

    Returns None (run without checkpointing) if the saver can't be created, so
    the worker stays usable where the DB/schema is unavailable. Initialized
    once and reused across all runs in the worker's lifetime.
    """
    global _saver
    if _saver is not None:
        return _saver
    try:
        _saver = await get_saver()
    except Exception:
        logger.warning(
            "research: checkpointing disabled (could not init saver)",
            exc_info=True,
        )
        _saver = False
    return _saver if _saver else None


async def _get_graph() -> Any:
    """Build the compiled graph on first use, bound to the (optional) saver.

    Compilation happens once and is cached. Doing it here — instead of at
    module import — lets the async saver initialize first, so the graph can be
    bound to a real checkpointer when one is available.
    """
    global _graph
    if _graph is not None:
        return _graph
    saver = await _get_saver()
    _graph = _build_graph(checkpointer=saver)
    return _graph


async def run_agent(
    question: str,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: AsyncSession,
    *,
    stage_callback: Any = None,
    history: list[dict[str, Any]] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> AgentResult:
    messages: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT}]

    if history:
        for msg in history:
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            parts = msg.get("parts", [])
            content = extract_text(parts)
            if content:
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": question})

    initial_state: AgentState = {
        "run_id": str(run_id),
        "workspace_id": str(workspace_id),
        "question": question,
        "plan": [],
        "messages": messages,
        "citations": [],
        "answer": None,
        "iterations": 0,
        "tokens_used": 0,
    }

    run_config = RunnableConfig(
        configurable={
            "_session": session,
            "_stage_callback": stage_callback,
            "thread_id": str(run_id),
        },
    )

    graph = await _get_graph()

    # Langfuse trace (PRD N3) — no-op when keys are unset. The observation is
    # updated with output + usage just before the context exits.
    with agent_run_trace(
        str(run_id), question, user_id=user_id, session_id=session_id
    ) as observation:
        with logfire.span("research_agent.run", run_id=str(run_id), question=question[:80]):
            final_state = await asyncio.wait_for(
                graph.ainvoke(initial_state, config=run_config),
                timeout=settings.AGENT_RUN_TIMEOUT,
            )

        if stage_callback:
            await stage_callback(ResearchStage.GENERATING)

        citations = final_state.get("citations", [])
        confidence = _assess_evidence(citations)

        # Zero retrieved evidence is the unambiguous fabrication risk: the model
        # has nothing to ground claims in, so force an honest refusal rather than
        # trusting the system prompt alone. The LLM's own answer is kept when
        # citations exist (even if weak) — low confidence surfaces via the flag.
        if confidence == "insufficient" and not citations:
            answer = _INSUFFICIENT_EVIDENCE_RESPONSE
        else:
            answer = (
                final_state.get("answer")
                or "I was unable to find sufficient evidence to answer this question."
            )

        iterations = final_state.get("iterations", 0)
        tokens_used = final_state.get("tokens_used", 0)

        await _persist_citations(session, run_id, citations, answer=answer)

        if stage_callback:
            await stage_callback(ResearchStage.FINALIZING)

        logfire.info(
            "research_agent.done",
            run_id=str(run_id),
            answer_len=len(answer),
            citations=len(citations),
            iterations=iterations,
            tokens_used=tokens_used,
            confidence=confidence,
        )

        observation.update(
            output={"answer": answer, "confidence": confidence},
            metadata={
                "citations": len(citations),
                "iterations": iterations,
                "confidence": confidence,
            },
            usage_details={"total_tokens": tokens_used},
        )

        return AgentResult(
            answer=answer,
            citations=citations,
            iterations=iterations,
            tokens_used=tokens_used,
            confidence=confidence,
        )


def extract_text(parts: list[dict[str, Any]]) -> str:
    """Extract plain text from a TanStack AI message parts array."""
    segments: list[str] = []
    for part in parts:
        if part.get("type") == "text" and part.get("content"):
            segments.append(str(part["content"]))
        elif part.get("type") == "tool-result" and part.get("content"):
            content = part["content"]
            if isinstance(content, str):
                segments.append(content)
    return " ".join(segments).strip()


def _format_chunks_for_model(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "No relevant documents found for this query."

    return _pack_chunks_for_model(chunks)


# Evidence-context budget in tokens. The pipeline returns up to 8 chunks of
# ~512 tokens each (~4096 total) — that alone can overflow a small local model
# (PRD targets 3B-4B, often 4k-8k context). Packing to a budget keeps headroom
# for the system prompt, question, history, and answer.
_CONTEXT_TOKEN_BUDGET = 3000

# Conservative chars-per-token for English text without a tokenizer. Slightly
# underestimates the true ratio (~4.0), which biases packing toward safety.
_CHARS_PER_TOKEN = 4

# Shortest probe (in words) worth matching against the answer when locating a
# citation span. Below this the match is too short to be meaningful grounding.
_MIN_MATCH_WORDS = 5


def _estimate_tokens(text: str) -> int:
    """Rough token count without pulling in a tokenizer dependency."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _pack_chunks_for_model(chunks: list[RetrievedChunk]) -> str:
    """Pack retrieved chunks into the model context under a token budget.

    Chunks arrive relevance-ranked (descending) from the pipeline, so packing
    in input order drops only the least-relevant tail. That keeps each `[n]`
    marker aligned with ``citations[n-1]`` — the citation-at-retrieval
    contract the UI relies on to resolve source links.

    The last included chunk is truncated (with a ``...`` marker) to consume
    remaining budget rather than dropped whole.
    """
    packed: list[str] = []
    remaining = _CONTEXT_TOKEN_BUDGET

    for index, chunk in enumerate(chunks, start=1):
        body = chunk.chunk_text
        # Parent-context expansion (retrieval.md): sibling text rides inside
        # the SAME [n] block so citations stay 1:1 with the citations list.
        if getattr(chunk, "context_text", ""):
            body = f"{body}\n\nContext from the same source:\n{chunk.context_text}"
        block = f"[{index}] Source: {chunk.source_ref}\n{body}"
        cost = _estimate_tokens(block)
        if cost <= remaining:
            packed.append(block)
            remaining -= cost
            continue
        # Partial fit: truncate the block to use the remaining budget.
        prefix = f"[{index}] Source: {chunk.source_ref}\n"
        room = remaining - _estimate_tokens(prefix) - _estimate_tokens("...")
        if room > _CHARS_PER_TOKEN * 4:
            keep_chars = room * _CHARS_PER_TOKEN
            packed.append(f"{prefix}{body[:keep_chars]}...")
        break

    return "\n\n".join(packed) if packed else "No relevant documents found for this query."


def _mean_relevance(citations: list[dict[str, Any]]) -> float:
    """Average rerank score across all citations in a run.

    A low mean signals that every retrieved chunk was tangential — the agent is
    working with evidence that doesn't actually address the question.
    """
    if not citations:
        return 0.0
    scores = [c.get("relevance_score") or 0.0 for c in citations]
    return sum(scores) / len(scores)


def _assess_evidence(citations: list[dict[str, Any]]) -> Literal["sufficient", "insufficient"]:
    """Decide whether retrieved evidence supports a grounded answer.

    Two failure modes:
    1. No citations at all — the agent never found anything. This is the
       unambiguous fabrication risk and forces a hard refusal.
    2. Citations exist but every relevance score is below threshold — the
       matches are too tangential to ground specific claims.
    """
    if not citations:
        return "insufficient"
    if _mean_relevance(citations) < _RELEVANCE_THRESHOLD:
        return "insufficient"
    return "sufficient"


async def _persist_citations(
    session: AsyncSession,
    run_id: uuid.UUID,
    citations: list[dict[str, Any]],
    *,
    answer: str | None,
) -> None:
    # Resolve answer spans only when there's an answer to search and at least
    # one citation to ground. Best-effort: a span stays NULL if the chunk text
    # can't be located (e.g. the model paraphrased it away).
    chunk_texts: dict[uuid.UUID, str] = {}
    if answer and citations:
        chunk_texts = await _fetch_chunk_texts(session, citations)

    for citation_data in citations:
        chunk_id = uuid.UUID(citation_data["chunk_id"])
        span = _locate_in_answer(chunk_texts.get(chunk_id), answer)
        session.add(
            Citation(
                run_id=run_id,
                chunk_id=chunk_id,
                relevance_score=citation_data.get("relevance_score"),
                answer_span_start=span[0] if span else None,
                answer_span_end=span[1] if span else None,
            )
        )


async def _fetch_chunk_texts(
    session: AsyncSession,
    citations: list[dict[str, Any]],
) -> dict[uuid.UUID, str]:
    """Fetch chunk texts for a batch of citations in one query."""
    from src.ingestion.models import Chunk

    chunk_ids = [uuid.UUID(c["chunk_id"]) for c in citations]
    result = await session.execute(select(Chunk.id, Chunk.text).where(Chunk.id.in_(chunk_ids)))
    return {row[0]: row[1] for row in result.all()}


def _locate_in_answer(chunk_text: str | None, answer: str | None) -> tuple[int, int] | None:
    """Locate a cited chunk's text within the answer, returning char offsets.

    Uses a normalized, whitespace-tolerant match against a probe of the chunk
    (first ~120 chars). If the full probe doesn't resolve — e.g. the model
    quoted only the opening of the chunk — the matcher trims the probe word by
    word and retries, finding the longest matching prefix-substring. Returns
    None if no substantial match is found; the citation keeps a NULL span,
    which is the existing behavior.
    """
    if not chunk_text or not answer:
        return None

    probe = _make_probe(chunk_text)
    tokens = probe.split(" ")
    if not tokens:
        return None

    for end in range(len(tokens), 0, -1):
        candidate = " ".join(tokens[:end])
        if end < len(tokens) and end < _MIN_MATCH_WORDS:
            break
        pattern = r"\s+".join(re.escape(tok) for tok in candidate.split(" "))
        match = re.search(pattern, answer, re.IGNORECASE)
        if match is not None:
            return match.start(), match.end()

    return None


def _make_probe(chunk_text: str, *, max_len: int = 120) -> str:
    """Derive a distinctive, normalized probe from a chunk for span matching."""
    normalized = re.sub(r"\s+", " ", chunk_text).strip()
    if len(normalized) <= max_len:
        return normalized
    # Trim to max_len, but don't cut mid-word — back off to the last space.
    trimmed = normalized[:max_len]
    last_space = trimmed.rfind(" ")
    if last_space > max_len // 2:
        trimmed = trimmed[:last_space]
    return trimmed
