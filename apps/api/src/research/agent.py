"""
research/agent.py
-----------------
Single-agent MVP research loop with LangGraph.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, TypedDict

import logfire
from langgraph.graph import END, StateGraph  # type: ignore[import-untyped]
from sqlalchemy.ext.asyncio import AsyncSession

from src.research.models import Citation
from src.retrieval.pipeline import RetrievedChunk, retrieve
from src.shared.model_gateway import complete_with_tools
from src.shared.progress import ResearchStage

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5


class AgentState(TypedDict):
    run_id: str
    workspace_id: str
    question: str
    messages: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    answer: str | None
    iterations: int
    _stage_callback: Any
    _session: Any


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


async def _researcher_node(state: AgentState) -> dict[str, Any]:
    callback = state.get("_stage_callback")

    if state["iterations"] >= MAX_ITERATIONS:
        final_msg = await complete_with_tools(
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
        )
        return {
            "answer": final_msg.content or "Insufficient evidence to answer.",
            "messages": state["messages"],
        }

    response = await complete_with_tools(
        state["messages"],
        tools=[_RETRIEVAL_TOOL],
        temperature=0.1,
        max_tokens=2048,
    )

    if not response.tool_calls:
        return {
            "answer": response.content or "",
            "messages": state["messages"] + [{"role": "assistant", "content": response.content or ""}],
        }

    if callback:
        await callback(ResearchStage.SEARCHING)

    session: AsyncSession = state["_session"]
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
        + [{"role": "assistant", "content": response.content or "", "tool_calls": assistant_tool_calls}]
        + tool_results,
        "citations": state["citations"] + new_citations,
        "iterations": state["iterations"] + 1,
    }


def _should_continue(state: AgentState) -> str:
    if state.get("answer") is not None:
        return END
    if state["iterations"] >= MAX_ITERATIONS:
        return END
    return "researcher"


def _build_graph() -> Any:
    builder = StateGraph(AgentState)
    builder.add_node("researcher", _researcher_node)
    builder.set_entry_point("researcher")
    builder.add_conditional_edges("researcher", _should_continue, {"researcher": "researcher", END: END})
    return builder.compile()


_graph = _build_graph()


@dataclass
class AgentResult:
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    iterations: int = 0


async def run_agent(
    question: str,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: AsyncSession,
    *,
    stage_callback: Any = None,
    langfuse_trace_id: str | None = None,
    history: list[dict[str, Any]] | None = None,
) -> AgentResult:
    del langfuse_trace_id

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
        "messages": messages,
        "citations": [],
        "answer": None,
        "iterations": 0,
        "_stage_callback": stage_callback,
        "_session": session,
    }

    with logfire.span("research_agent.run", run_id=str(run_id), question=question[:80]):
        final_state = await _graph.ainvoke(initial_state)

    if stage_callback:
        await stage_callback(ResearchStage.GENERATING)

    answer = final_state.get("answer") or "I was unable to find sufficient evidence to answer this question."
    citations = final_state.get("citations", [])
    iterations = final_state.get("iterations", 0)

    await _persist_citations(session, run_id, citations)

    if stage_callback:
        await stage_callback(ResearchStage.FINALIZING)

    logfire.info(
        "research_agent.done",
        run_id=str(run_id),
        answer_len=len(answer),
        citations=len(citations),
        iterations=iterations,
    )

    return AgentResult(answer=answer, citations=citations, iterations=iterations)


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

    return "\n\n".join(
        f"[{index}] Source: {chunk.source_ref}\n{chunk.chunk_text}"
        for index, chunk in enumerate(chunks, start=1)
    )


async def _persist_citations(
    session: AsyncSession,
    run_id: uuid.UUID,
    citations: list[dict[str, Any]],
) -> None:
    for citation_data in citations:
        session.add(
            Citation(
                run_id=run_id,
                chunk_id=uuid.UUID(citation_data["chunk_id"]),
                relevance_score=citation_data.get("relevance_score"),
            )
        )
