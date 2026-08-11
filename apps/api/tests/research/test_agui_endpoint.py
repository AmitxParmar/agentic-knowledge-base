"""
tests/research/test_agui_endpoint.py
-------------------------------------
Purpose:    Tests for the AG-UI SSE chat endpoint (POST /api/research/chat).
Dependencies: pytest, fastapi test client
Scope:      Verifies SSE headers and request validation.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from src.research.router import ChatRequest


def make_client() -> TestClient:
    """Create a test client."""
    app = create_app()
    return TestClient(app)


def test_agui_chat_returns_sse_headers() -> None:
    """The endpoint must return text/event-stream content type."""
    client = make_client()
    response = client.post("/api/research/chat", json={"question": "test"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")


def test_agui_chat_accepts_thread_id() -> None:
    """The AG-UI envelope's threadId must map to ChatRequest.thread_id.

    Model-level test: hitting the endpoint a second time in the same pytest
    session would reuse a pooled asyncpg connection across TestClient's
    per-request event loops (a harness limitation, not app code).
    """
    request = ChatRequest(threadId="thread-123", question="test")
    assert request.thread_id == "thread-123"


def test_agui_chat_accepts_thread_id_via_field_name() -> None:
    request = ChatRequest(thread_id="thread-456", question="test")
    assert request.thread_id == "thread-456"


def test_agui_chat_rejects_empty_question() -> None:
    """Empty questions must return 422."""
    client = make_client()
    response = client.post("/api/research/chat", json={"question": "   "})
    assert response.status_code == 422



