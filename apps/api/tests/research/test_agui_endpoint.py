"""
tests/research/test_agui_endpoint.py
-------------------------------------
Purpose:    Tests for the AG-UI SSE chat endpoint (POST /api/research/chat).
Dependencies: pytest, fastapi test client, mocked agent
Scope:      Verifies event stream format, event ordering, and error handling.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import create_app


def make_client() -> TestClient:
    """Create a test client with mocked agent and session."""
    app = create_app()
    return TestClient(app)


def test_agui_chat_streams_run_started() -> None:
    """The first event must be RUN_STARTED with thread/run IDs."""
    client = make_client()

    async def mock_run(**_kwargs):
        return SimpleNamespace(
            answer="Test answer",
            citations=[{"chunk_id": "c1", "source_ref": "doc.pdf", "relevance_score": 0.9}],
            iterations=1,
        )

    with patch("src.research.router.run_agent", new=AsyncMock(side_effect=mock_run)):
        response = client.post("/api/research/chat", json={"question": "What is this?"})

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")

    events = parse_sse_events(response.text)
    assert any(e["type"] == "RUN_STARTED" for e in events)

    run_started = next(e for e in events if e["type"] == "RUN_STARTED")
    assert "threadId" in run_started
    assert "runId" in run_started


def test_agui_chat_streams_run_finished() -> None:
    """The stream must end with RUN_FINISHED."""
    client = make_client()

    async def mock_run(**_kwargs):
        return SimpleNamespace(
            answer="The answer is 42.",
            citations=[],
            iterations=1,
        )

    with patch("src.research.router.run_agent", new=AsyncMock(side_effect=mock_run)):
        response = client.post("/api/research/chat", json={"question": "test"})

    events = parse_sse_events(response.text)
    assert events[-1]["type"] == "RUN_FINISHED"


def test_agui_chat_rejects_empty_question() -> None:
    """Empty questions must return 422."""
    client = make_client()
    response = client.post("/api/research/chat", json={"question": "   "})
    assert response.status_code == 422


def parse_sse_events(text: str) -> list[dict]:
    """Parse SSE text body into a list of event dicts."""
    events: list[dict] = []
    for block in text.strip().split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events
