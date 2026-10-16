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
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings
from src.observability.setup import agent_run_trace
from src.research.checkpoint import get_saver
from src.research.models import Citation
from src.research.usage import enforce_budget
from src.retrieval.pipeline import RetrievedChunk, retrieve
from src.shared.model_gateway import StreamUsage, complete_stream, complete_with_tools
from src.shared.progress import ResearchStage
from src.shared.prompt_safety import (
    MAX_HISTORY_MESSAGES,
    MAX_QUESTION_CHARS,
    redact_secrets,
    sanitize_user_text,
    scan_input,
    scan_output,
    wrap_document,
)
from src.shared.prompts import get_prompt

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

# Served when the workspace has no finished documents at all — a different
# situation from "docs exist but nothing matched" (the message above), so it
# gets its own wording that points at uploading instead of rephrasing.
_NO_DOCUMENTS_RESPONSE = (
    "You don't have any searchable documents yet — upload a PDF, repo, or "
    "audio file first, wait for ingestion to finish, then ask again."
)


async def _workspace_has_searchable_docs(session: AsyncSession, workspace_id: uuid.UUID) -> bool:
    """True when the workspace has at least one finished document.

    A bounded COUNT — never loads rows — so the empty-corpus check stays
    cheap on the hot path. Any DB failure returns True (fail open): the
    generic insufficient-evidence refusal below is the safe fallback.
    """
    import inspect

    from sqlalchemy import func

    from src.ingestion.models import Document, JobStage

    try:
        result = await asyncio.wait_for(
            session.execute(
                select(func.count(Document.id)).where(
                    Document.workspace_id == workspace_id,
                    Document.processing_status == JobStage.done,
                )
            ),
            timeout=5,
        )
        count = result.scalar_one()
        # Step 1: tolerate mock sessions whose scalar_one is awaitable.
        if inspect.isawaitable(count):
            count = await count
        return bool(count)
    except Exception:
        logger.warning("research: searchable-docs check failed, assuming docs exist")
        return True


class AgentState(TypedDict):
    run_id: str
    workspace_id: str
    question: str
    plan: list[str]
    messages: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    draft_answer: str | None
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

# Prompt text lives in the versioned registry (src/shared/prompts.py) — these
# aliases keep call sites readable and stay pinned to the tested revisions.
SYSTEM_PROMPT = get_prompt("research.system")
PLANNER_PROMPT = get_prompt("research.planner")
SYNTHESIS_PROMPT = get_prompt("research.synthesis")

# Back-compat aliases for the raw strings (leak filter, tests).
_SYSTEM_PROMPT = SYSTEM_PROMPT.text
_PLANNER_PROMPT = PLANNER_PROMPT.text

# Served when the model answer leaks the system prompt (defense in depth on
# top of the untrusted-delimiter rule; the model is not trusted to follow it).
_SYSTEM_PROMPT_LEAK_RESPONSE = (
    "I can't share my internal instructions. Please ask a question about your uploaded documents."
)

_PLANNER_MAX_ASPECTS = 3


_PLAN_LIST = TypeAdapter(list[str])


def _parse_plan(content: str | None) -> list[str]:
    """Parse the planner's JSON array output, tolerantly.

    Accepts plain or code-fenced arrays, caps at _PLANNER_MAX_ASPECTS,
    and drops empty/non-string entries. Returns [] on anything unparseable.
    Item validation goes through pydantic so only real strings survive.
    """
    if not content:
        return []
    # Step 1: locate the outermost JSON array brackets (tolerates code fences
    # and prose around the array).
    start = content.find("[")
    end = content.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    # Step 2: decode the JSON; anything that isn't valid JSON fails the run's
    # planner fallback (single-step plan = raw question).
    try:
        raw = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    # Step 3: validate every item as a string via pydantic. Mixed-type arrays
    # are tolerated by keeping only the string entries and re-validating.
    try:
        parsed = _PLAN_LIST.validate_python(raw)
    except ValidationError:
        try:
            parsed = _PLAN_LIST.validate_python([q for q in raw if isinstance(q, str)])
        except ValidationError:
            return []
    # Step 4: trim, drop blanks, cap at the aspect limit.
    queries = [q.strip() for q in parsed if q.strip()]
    return queries[:_PLANNER_MAX_ASPECTS]


class _RetrieveArguments(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


def _validated_retrieval_query(arguments: Any, fallback: str) -> str:
    """Validate the retrieval tool's arguments against the tool schema.

    The model is probabilistic — a missing/blank/non-string query must never
    crash the run. Falls back to the raw question instead.
    """
    # Step 1: validate shape — must match the tool's declared schema.
    try:
        args = _RetrieveArguments.model_validate(arguments)
    except (ValidationError, TypeError, ValueError):
        logger.warning(
            "research: invalid retrieval tool args (%r) — falling back to question",
            arguments,
        )
        return fallback
    # Step 2: accept the model's query only if it survives stripping.
    query = args.query.strip()
    return query or fallback


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
    plan_tokens = 0
    try:
        response = await asyncio.wait_for(
            complete_with_tools(
                [
                    {"role": "system", "content": PLANNER_PROMPT.text},
                    {"role": "user", "content": state["question"]},
                ],
                tools=None,
                route="small",
                temperature=0.0,
                max_tokens=200,
                prompt_version=PLANNER_PROMPT.label,
            ),
            timeout=settings.AGENT_ITERATION_TIMEOUT,
        )
        plan = _parse_plan(response.content)
        plan_tokens = _msg_tokens(response)
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
    return {
        "plan": plan,
        "messages": state["messages"] + [plan_message],
        "tokens_used": state["tokens_used"] + plan_tokens,
    }


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
            prompt_version=SYSTEM_PROMPT.label,
        ),
        timeout=settings.AGENT_ITERATION_TIMEOUT,
    )

    if not response.tool_calls:
        return {
            "draft_answer": response.content or "",
            "messages": state["messages"]
            + [{"role": "assistant", "content": response.content or ""}],
            "tokens_used": state["tokens_used"] + _msg_tokens(response),
        }

    if callback:
        await callback(ResearchStage.SEARCHING)

    workspace_id = uuid.UUID(state["workspace_id"])
    new_citations: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    tool_tokens = 0  # HyDE LLM tokens across this round's retrieval calls

    for tool_call in response.tool_calls:
        # Step 1: resolve the model-requested query against the tool schema.
        query = _validated_retrieval_query(tool_call.function.arguments, state["question"])
        # Step 2: number this round's blocks from the global citation offset —
        # markers [k] always index citations[k-1], on every ReAct round.
        block_start = len(state["citations"]) + len(new_citations) + 1
        with logfire.span("agent.retrieval_tool", query=query, iteration=state["iterations"]):
            chunks, hyde_tokens = await retrieve(query, workspace_id, session)
            tool_tokens += hyde_tokens

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
                "content": _format_chunks_for_model(chunks, start=block_start),
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
        "tokens_used": state["tokens_used"] + _msg_tokens(response) + tool_tokens,
    }


async def _synthesize_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Final-answer node: generate the client-facing answer with the synthesis model.

    The researcher writes a draft after it stops calling tools. This node
    streams the final wording token-by-token through the stage callback (the
    router forwards text deltas as AG-UI content events) while accumulating
    the full text for persistence. If the iteration cap is exhausted, it
    synthesizes directly from gathered evidence.

    Note: post-hoc safety replacements in run_agent (leak filter, hard
    refusal) apply to the persisted/cached answer. Text already streamed stays
    on the wire — streaming trades pre-delivery filtering for live output,
    which is why the delimiter rules and evidence gate run before synthesis.
    """
    configurable = config.get("configurable") or {}
    callback = configurable.get("_stage_callback")

    if state.get("answer") is not None:
        return {}

    # Step 1: stream the final wording; forward each text delta live.
    parts: list[str] = []
    stream_tokens = 0
    async for part in complete_stream(
        state["messages"] + [{"role": "user", "content": SYNTHESIS_PROMPT.text}],
        route="synthesis",
        max_tokens=settings.MAX_ANSWER_TOKENS,
        prompt_version=SYNTHESIS_PROMPT.label,
    ):
        # Step 2: text deltas flow to the client; the trailing usage object
        # feeds cost accounting.
        if isinstance(part, str):
            parts.append(part)
            if callback is not None:
                await callback(part)
        elif isinstance(part, StreamUsage):
            stream_tokens = part.total_tokens

    # Step 3: persist the complete answer (or the insufficient-evidence fallback).
    answer = "".join(parts) or "Insufficient evidence to answer."
    return {
        "answer": answer,
        "messages": state["messages"],
        "tokens_used": state["tokens_used"] + stream_tokens,
    }


def _msg_tokens(response: Any) -> int:
    usage = getattr(response, "usage", None)
    return getattr(usage, "total_tokens", 0) or 0


def _route_after_research(state: AgentState) -> str:
    """Route to synthesize once an answer exists, iterations are spent, or
    the run's token budget is exhausted (maturity plan §7: hard cost caps)."""
    if state.get("answer") is not None or state.get("draft_answer") is not None:
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
    question = sanitize_user_text(question) or question.strip()

    # Step 0b: guardrail scan (ADR-010) — flag injections to telemetry, redact
    # secrets before anything reaches the model.
    if settings.GUARDRAILS_ENABLED:
        question_scan = scan_input(question)
        if question_scan.flagged:
            logger.warning(
                "research: guardrail flagged input in run %s: %s",
                run_id,
                question_scan.reasons,
            )
            logfire.warn(
                "research.guardrail_input_flagged",
                run_id=str(run_id),
                reasons=question_scan.reasons,
            )
        question = question_scan.redacted or question
    messages: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT}]

    # Step 0: budget gate — refuse before spending anything. Lives here (not
    # in the routers) so SSE, WebSocket, and voice share one enforcement point.
    if user_id is not None:
        try:
            await enforce_budget(session, uuid.UUID(user_id))
        except ValueError:
            # Non-UUID caller ids (tests, stubs) skip budget enforcement.
            logger.debug("research: skipping budget check for non-uuid user_id")

    if history:
        # Step 1: filter out any non-user/assistant roles (client-supplied
        # system/tool messages must never reach the model).
        # Step 2: sanitize each message's text (strip control chars, cap size).
        eligible: list[dict[str, Any]] = []
        for msg in history:
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            content = sanitize_user_text(
                extract_text(msg.get("parts", [])), max_chars=MAX_QUESTION_CHARS
            )
            if settings.GUARDRAILS_ENABLED:
                content = redact_secrets(content)
            if content:
                eligible.append({"role": role, "content": content})
        # Step 3: keep only the most recent N turns so history can't blow up
        # the context window or starve the current question.
        messages.extend(eligible[-MAX_HISTORY_MESSAGES:])

    messages.append({"role": "user", "content": question})

    initial_state: AgentState = {
        "run_id": str(run_id),
        "workspace_id": str(workspace_id),
        "question": question,
        "plan": [],
        "messages": messages,
        "citations": [],
        "draft_answer": None,
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
        # Empty-workspace ("upload first") and no-match ("rephrase") refusals
        # stay distinct so the UI can guide the user to the right next step.
        if confidence == "insufficient" and not citations:
            if await _workspace_has_searchable_docs(session, workspace_id):
                answer = _INSUFFICIENT_EVIDENCE_RESPONSE
            else:
                answer = _NO_DOCUMENTS_RESPONSE
        else:
            answer = (
                final_state.get("answer")
                or "I was unable to find sufficient evidence to answer this question."
            )

        # Step 1: block system-prompt leakage before it leaves the server.
        # Step 2: redact any secrets echoed from retrieved chunks.
        if settings.GUARDRAILS_ENABLED:
            out_scan = scan_output(answer, _SYSTEM_PROMPT)
            if "leak:system-prompt" in out_scan.reasons:
                logger.warning("research: blocked system-prompt leakage in run %s", run_id)
                logfire.warn("research.system_prompt_leak_blocked", run_id=str(run_id))
                answer = _SYSTEM_PROMPT_LEAK_RESPONSE
            else:
                answer = out_scan.redacted
            if out_scan.flagged:
                logfire.warn(
                    "research.guardrail_output_flagged",
                    run_id=str(run_id),
                    reasons=out_scan.reasons,
                )

        invalid_markers = _validate_citation_markers(answer, len(citations))
        if invalid_markers:
            logger.warning(
                "research: answer has %d dangling citation marker(s) %s in run %s",
                len(invalid_markers),
                invalid_markers,
                run_id,
            )
            logfire.warn(
                "research.dangling_citation_markers",
                run_id=str(run_id),
                invalid_markers=invalid_markers,
                n_citations=len(citations),
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
                "prompts": [
                    SYSTEM_PROMPT.label,
                    PLANNER_PROMPT.label,
                    SYNTHESIS_PROMPT.label,
                ],
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


def _format_chunks_for_model(chunks: list[RetrievedChunk], *, start: int = 1) -> str:
    if not chunks:
        return "No relevant documents found for this query."

    return _pack_chunks_for_model(chunks, start=start)


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


# Citation markers are 1-based indices into the run's citation list.
_MARKER = re.compile(r"\[(\d{1,2})\]")


def _validate_citation_markers(answer: str, n_citations: int) -> list[int]:
    """Return every [n] marker in the answer that has no matching citation.

    An empty list means every marker resolves to citations[n-1]. A marker is
    invalid when it points past the citation list (e.g. the model invented
    [9] with only 3 citations) — the packer guarantees valid numbers, so a
    hit here always means model drift.
    """
    # Step 1: collect the distinct marker numbers the answer uses.
    markers = {int(m) for m in _MARKER.findall(answer or "")}
    # Step 2: keep only the ones outside the valid citation range.
    return sorted(n for n in markers if n < 1 or n > n_citations)


def _estimate_tokens(text: str) -> int:
    """Rough token count without pulling in a tokenizer dependency."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _pack_chunks_for_model(chunks: list[RetrievedChunk], *, start: int = 1) -> str:
    """Pack retrieved chunks into the model context under a token budget.

    Chunks arrive relevance-ranked (descending) from the pipeline, so packing
    in input order drops only the least-relevant tail. ``start`` is the
    1-based number of the first block: the researcher passes the global
    citation offset so markers stay aligned with ``citations[n-1]`` across
    ReAct rounds (the citation-at-retrieval contract the UI relies on to
    resolve source links).

    The last included chunk is truncated (with a ``...`` marker) to consume
    remaining budget rather than dropped whole.
    """
    packed: list[str] = []
    remaining = _CONTEXT_TOKEN_BUDGET

    for offset, chunk in enumerate(chunks):
        index = start + offset
        body = chunk.chunk_text
        # Parent-context expansion (retrieval.md): sibling text rides inside
        # the SAME [n] block so citations stay 1:1 with the citations list.
        if getattr(chunk, "context_text", ""):
            body = f"{body}\n\nContext from the same source:\n{chunk.context_text}"
        block = f"[{index}] Source: {chunk.source_ref}\n{wrap_document(body)}"
        cost = _estimate_tokens(block)
        if cost <= remaining:
            packed.append(block)
            remaining -= cost
            continue
        # Partial fit: truncate the block to use the remaining budget.
        prefix = f"[{index}] Source: {chunk.source_ref}\n<document>\n"
        closing = "...\n</document>"
        room = remaining - _estimate_tokens(prefix) - _estimate_tokens(closing)
        if room > _CHARS_PER_TOKEN * 4:
            keep_chars = room * _CHARS_PER_TOKEN
            packed.append(f"{prefix}{body[:keep_chars]}...\n</document>")
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
