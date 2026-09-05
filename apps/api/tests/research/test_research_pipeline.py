"""
tests/research/test_research_pipeline.py
----------------------------------------
Tests for the composed pipeline (docs/specs/research-pipeline.md):
planner decomposition + fallbacks, synthesize dual paths, routing,
and an offline full-graph smoke run (model gateway + retriever mocked).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.runnables import RunnableConfig

from src.research.agent import (
    MAX_ITERATIONS,
    AgentState,
    _build_graph,
    _parse_plan,
    _planner_node,
    _route_after_research,
    _synthesize_node,
)
from src.retrieval.pipeline import RetrievedChunk
from src.shared.progress import ResearchStage

# ── _parse_plan ───────────────────────────────────────────────────────────────


def test_parse_plan_plain_array() -> None:
    assert _parse_plan('["a", "b"]') == ["a", "b"]


def test_parse_plan_code_fenced_array() -> None:
    assert _parse_plan('```json\n["query one"]\n```') == ["query one"]


def test_parse_plan_garbage_is_empty() -> None:
    assert _parse_plan("no arrays here") == []
    assert _parse_plan(None) == []
    assert _parse_plan("") == []
    assert _parse_plan("[broken") == []


def test_parse_plan_caps_at_three_and_drops_junk() -> None:
    raw = '["a", "", "b", 42, "c", "d", "e"]'
    assert _parse_plan(raw) == ["a", "b", "c"]


# ── planner node ──────────────────────────────────────────────────────────────


def _state(**overrides: Any) -> AgentState:
    base: AgentState = {
        "run_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
        "question": "What is the refund policy?",
        "plan": [],
        "messages": [{"role": "user", "content": "What is the refund policy?"}],
        "citations": [],
        "draft_answer": None,
        "answer": None,
        "iterations": 0,
        "tokens_used": 0,
    }
    return {**base, **overrides}  # type: ignore[typeddict-item]


async def test_planner_injects_plan_message(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_complete(*args: object, **kwargs: Any) -> str:
        captured.update(kwargs)
        return '["refund window", "EU exceptions"]'

    monkeypatch.setattr(
        "src.research.agent.complete",
        fake_complete,
    )

    result = await _planner_node(_state(), RunnableConfig(configurable={}))

    assert result["plan"] == ["refund window", "EU exceptions"]
    plan_messages = [
        m for m in result["messages"] if m["role"] == "system" and "Search plan" in m["content"]
    ]
    assert len(plan_messages) == 1
    assert "- refund window" in plan_messages[0]["content"]
    assert captured["route"] == "small"


async def test_planner_falls_back_on_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("provider down")

    monkeypatch.setattr("src.research.agent.complete", boom)

    result = await _planner_node(_state(), RunnableConfig(configurable={}))

    assert result["plan"] == ["What is the refund policy?"]


async def test_planner_falls_back_on_unparseable_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.research.agent.complete",
        AsyncMock(return_value="I cannot answer that."),
    )

    result = await _planner_node(_state(), RunnableConfig(configurable={}))
    assert result["plan"] == ["What is the refund policy?"]


# ── synthesize node ───────────────────────────────────────────────────────────


async def test_synthesize_passes_through_existing_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("must not call the model on pass-through")

    monkeypatch.setattr("src.research.agent.complete_with_tools", fail)

    state = _state(answer="Already answered.")
    assert await _synthesize_node(state, RunnableConfig(configurable={})) == {}


async def test_synthesize_generates_when_loop_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_complete_with_tools(messages: list, tools: Any, **kwargs: object) -> Any:
        captured["tools"] = tools
        captured["last_message"] = messages[-1]
        captured.update(kwargs)
        return SimpleNamespace(
            content="Best-effort answer.", usage=SimpleNamespace(total_tokens=42)
        )

    monkeypatch.setattr("src.research.agent.complete_with_tools", fake_complete_with_tools)

    state = _state(iterations=MAX_ITERATIONS)
    result = await _synthesize_node(state, RunnableConfig(configurable={}))

    assert result["answer"] == "Best-effort answer."
    assert result["tokens_used"] == 42
    assert captured["tools"] is None
    assert captured["route"] == "synthesis"
    assert "final answer" in captured["last_message"]["content"]


# ── routing ───────────────────────────────────────────────────────────────────


def test_routes_to_synthesize_on_answer() -> None:
    assert _route_after_research(_state(answer="done")) == "synthesize"


def test_routes_to_synthesize_on_researcher_draft() -> None:
    assert _route_after_research(_state(draft_answer="draft")) == "synthesize"


def test_routes_to_synthesize_on_iteration_cap() -> None:
    assert _route_after_research(_state(iterations=MAX_ITERATIONS)) == "synthesize"


def test_routes_back_to_researcher_mid_loop() -> None:
    assert _route_after_research(_state()) == "researcher"


def test_routes_to_synthesize_on_token_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.research.agent.settings.AGENT_TOKEN_BUDGET", 100)
    assert _route_after_research(_state(tokens_used=100)) == "synthesize"
    # Below the boundary the loop continues.
    assert _route_after_research(_state(tokens_used=99)) == "researcher"


# ── full-graph smoke (offline) ────────────────────────────────────────────────


class _FakeToolCall:
    def __init__(self, call_id: str, query: str) -> None:
        self.id = call_id
        self.function = SimpleNamespace(name="retrieve_evidence", arguments={"query": query})


def test_full_graph_produces_cited_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """plan → research (one tool round-trip) → answer, all offline."""
    monkeypatch.setattr(
        "src.research.agent.complete",
        AsyncMock(return_value='["refund window"]'),
    )

    calls: list[list[dict[str, Any]]] = []

    async def fake_complete_with_tools(messages: list, tools: Any, **kwargs: object) -> Any:
        calls.append([dict(m) for m in messages])
        if any(m.get("role") == "assistant" for m in messages):
            # Second iteration: evidence is in context — write the answer.
            return SimpleNamespace(
                content="Refunds take 30 days [1].",
                tool_calls=[],
                usage=SimpleNamespace(total_tokens=20),
            )
        return SimpleNamespace(
            content="",
            tool_calls=[_FakeToolCall("call_1", "refund window")],
            usage=SimpleNamespace(total_tokens=15),
        )

    monkeypatch.setattr("src.research.agent.complete_with_tools", fake_complete_with_tools)

    chunk = RetrievedChunk(
        chunk_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        chunk_text="The refund window is 30 days from purchase.",
        source_ref="policy.pdf, chunk 1",
        relevance_score=0.9,
        position=1,
    )
    monkeypatch.setattr("src.research.agent.retrieve", AsyncMock(return_value=[chunk]))

    stages: list[ResearchStage] = []

    async def callback(stage: ResearchStage) -> None:
        stages.append(stage)

    graph = _build_graph(checkpointer=None)
    config = RunnableConfig(configurable={"_session": AsyncMock(), "_stage_callback": callback})
    final = asyncio_run_graph(graph, _state(), config)

    # Plan flowed through.
    assert final["plan"] == ["refund window"]
    assert any("Search plan" in str(m.get("content")) for m in final["messages"])

    # Evidence was retrieved, cited, drafted by the researcher, then finalized
    # through the synthesis route.
    assert len(final["citations"]) == 1
    assert final["citations"][0]["chunk_id"] == chunk.chunk_id
    assert final["answer"] == "Refunds take 30 days [1]."
    assert final["iterations"] == 1
    assert final["tokens_used"] == 55  # 15 (tool turn) + 20 (draft) + 20 (final)

    # Fixed ux.md vocabulary only.
    assert stages == [ResearchStage.SEARCHING, ResearchStage.REVIEWING]


def asyncio_run_graph(graph: Any, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    import asyncio

    return asyncio.run(graph.ainvoke(dict(state), config=config))
