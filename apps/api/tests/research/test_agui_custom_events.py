"""
tests/research/test_agui_custom_events.py
-------------------------------------------
Purpose:    Verifies the AG-UI CUSTOM event envelope emitted by
            agui_event_stream. Progress stages and citations must ride
            (name, value) pairs that the @tanstack/ai-client SSE parser
            normalizes into onCustomEvent(eventType, data) — NOT the legacy
            (custom_type, data) shape the WebSocket transport used.
Dependencies: pytest, src.research.router, src.research.agent
Scope:      Wire-format contract for the SSE chat endpoint.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from src.research import router
from src.research.agent import AgentResult
from src.shared.progress import ResearchStage

FAKE_CITATIONS = [
    {"chunk_id": str(uuid.uuid4()), "source_ref": "report.pdf, chunk 3", "relevance_score": 0.91},
    {"chunk_id": str(uuid.uuid4()), "source_ref": "code/main.py:MyClass", "relevance_score": 0.84},
]


class FakeSession:
    """Minimal AsyncSession stand-in: assigns an id on flush, commits as no-op."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self) -> None:
        return None


async def _fake_run_agent(
    question: str,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: FakeSession,
    *,
    stage_callback=None,
    history=None,
) -> AgentResult:
    del question, workspace_id, run_id, session, history
    if stage_callback:
        await stage_callback(ResearchStage.SEARCHING)
        await stage_callback(ResearchStage.GENERATING)
    return AgentResult(
        answer="The report states [1] and [2].",
        citations=FAKE_CITATIONS,
        iterations=1,
    )


async def _collect_events(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    monkeypatch.setattr(router, "run_agent", _fake_run_agent)

    events: list[dict] = []
    async for event in router.agui_event_stream(
        question="What does the report say?",
        workspace_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        session=FakeSession(),  # pyright: ignore[reportArgumentType]
    ):
        events.append(event)
    return events


def test_custom_events_use_name_value_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    events = asyncio.run(_collect_events(monkeypatch))

    custom_events = [e for e in events if e.get("type") == "CUSTOM"]
    assert custom_events, "expected CUSTOM events in the stream"

    for event in custom_events:
        assert "custom_type" not in event, "legacy custom_type field must not be emitted"
        assert "data" not in event, "legacy top-level data field must not be emitted"
        assert event["name"] in ("stage", "citations")
        assert "value" in event

    stage_events = [e for e in custom_events if e["name"] == "stage"]
    assert [e["value"]["stage"] for e in stage_events] == [
        ResearchStage.SEARCHING.value,
        ResearchStage.GENERATING.value,
    ]

    citations_event = next(e for e in custom_events if e["name"] == "citations")
    assert citations_event["value"]["run_id"]
    assert citations_event["value"]["citations"] == FAKE_CITATIONS


def test_stream_has_terminal_events(monkeypatch: pytest.MonkeyPatch) -> None:
    events = asyncio.run(_collect_events(monkeypatch))

    assert events[0]["type"] == "RUN_STARTED"
    assert events[-1]["type"] == "RUN_FINISHED"
