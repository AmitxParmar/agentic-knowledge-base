"""
tests/research/test_sse_leakage.py
----------------------------------
Channel discipline for the AG-UI SSE stream (ux.md + AGENTS.md rule 4):
frames must carry ONLY the documented stage vocabulary and must never leak
system-prompt fragments or chain-of-thought. Complements the run-level
guardrail tests by scanning the wire frames themselves.

The stream is consumed directly (async generator with a mocked agent) so
the test needs no HTTP client and no live agent — DB is an AsyncMock.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.research.router import agui_event_stream
from src.shared.prompt_safety import find_system_prompt_leak
from src.shared.prompts import get_prompt

# The exact prompt the agent sends to the model — the string that must not
# appear on the client channel.
_SYSTEM_PROMPT_TEXT = get_prompt("research.system").text


def _fake_result(answer: str) -> Any:
    # Minimal AgentResult-shaped object; only the fields the router reads.
    return SimpleNamespace(
        answer=answer,
        citations=[
            {
                "chunk_id": str(uuid.uuid4()),
                "source_ref": "policy.pdf, p.1",
                "relevance_score": 0.91,
            }
        ],
        iterations=1,
        tokens_used=42,
        confidence=0.8,
    )


@pytest.mark.asyncio
async def test_sse_frames_are_vocabulary_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.shared.progress import ResearchStage

    sentinel = "Refunds take 30 days [1]."

    async def fake_run_agent(
        *,
        question: str,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
        session: Any,
        stage_callback: Any,
        **kwargs: Any,
    ) -> Any:
        # Step 1: emit every documented progress stage...
        for stage in ResearchStage:
            await stage_callback(stage)
        # Step 2: ...then one synthesis text delta (raw str = delta by design).
        await stage_callback("Refunds take ")
        return _fake_result(sentinel)

    class FakeCache:
        async def lookup(self, *args: Any, **kwargs: Any) -> None:
            return None

        async def store(self, *args: Any, **kwargs: Any) -> None:
            return None

    monkeypatch.setattr("src.research.router.run_agent", fake_run_agent)
    monkeypatch.setattr("src.research.router.SemanticCache", FakeCache)

    frames: list[dict[str, Any]] = []
    async for frame in agui_event_stream(
        "what is the refund policy", uuid.uuid4(), uuid.uuid4(), session=AsyncMock()
    ):
        frames.append(frame)

    # Step 1: stage frames use ONLY the documented ux.md vocabulary.
    stages = [f["value"]["stage"] for f in frames if f.get("name") == "stage"]
    allowed = {s.value for s in ResearchStage}
    assert stages, "fake agent emitted stages but no stage frames were queued"
    assert set(stages) <= allowed, f"undeclared stage vocabulary on the wire: {stages}"

    # Step 2: no frame may contain a system-prompt fragment (CoT leak scan).
    raw = "\n".join(json.dumps(f) for f in frames)
    assert not find_system_prompt_leak(raw, _SYSTEM_PROMPT_TEXT), "prompt leaked into SSE frames"

    # Step 3: the answer travels as a delta; the run terminates cleanly.
    assert any(
        f.get("type") == "TEXT_MESSAGE_CONTENT" and f.get("delta") == "Refunds take "
        for f in frames
    )
    assert any(f.get("type") == "TEXT_MESSAGE_END" for f in frames)
    assert any(f.get("type") == "RUN_FINISHED" for f in frames)


@pytest.mark.asyncio
async def test_sse_error_frames_use_safe_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failures map to stable codes + user-safe text — never raw exceptions."""
    from src.shared.model_gateway import ProviderError

    async def failing_run_agent(**kwargs: Any) -> Any:
        raise ProviderError("groq/api-key-xyz rejected the request: internal detail")

    class FakeCache:
        async def lookup(self, *args: Any, **kwargs: Any) -> None:
            return None

        async def store(self, *args: Any, **kwargs: Any) -> None:
            return None

    monkeypatch.setattr("src.research.router.run_agent", failing_run_agent)
    monkeypatch.setattr("src.research.router.SemanticCache", FakeCache)

    frames = [
        frame
        async for frame in agui_event_stream(
            "question", uuid.uuid4(), uuid.uuid4(), session=AsyncMock()
        )
    ]

    errors = [f for f in frames if f.get("type") == "RUN_ERROR"]
    assert errors and errors[0]["code"] == "PROVIDER_ERROR"
    raw = "\n".join(json.dumps(f) for f in frames)
    # Internal provider detail must not reach the client channel.
    assert "api-key-xyz" not in raw
