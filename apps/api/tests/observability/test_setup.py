"""
tests/observability/test_setup.py
---------------------------------
Purpose:    Verify the Langfuse tracing helpers degrade gracefully when
            Langfuse keys are unset (no network, no errors), that the no-op
            observation absorbs updates, and that user/session/tags context is
            propagated when tracing is enabled.

Dependencies: pytest, src.observability.setup
Scope:      Tracing wiring only — asserts no real Langfuse client is touched.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from src.observability.setup import (
    _NoOpObservation,
    agent_run_trace,
    traced_observation,
)


def _fake_client(captured_start: dict[str, Any], captured_update: dict[str, Any]):
    """Builds a fake Langfuse client recording start/update kwargs."""

    class FakeObservation:
        def update(self, **kwargs: object) -> None:
            captured_update.update(kwargs)

    @staticmethod  # type: ignore[misc]
    def fake_start(*args: object, **kwargs: object):
        captured_start.update(kwargs)

        class _Ctx:
            def __enter__(self):
                return FakeObservation()

            def __exit__(self, *exc):
                return False

        return _Ctx()

    return types.SimpleNamespace(start_as_current_observation=fake_start)


def test_no_op_observation_absorbs_update() -> None:
    """A disabled observation must silently swallow update() calls."""
    obs = _NoOpObservation()
    # Must not raise, regardless of kwargs.
    obs.update(output={"answer": "x"}, metadata={"citations": 0}, usage_details={})


@pytest.mark.asyncio
async def test_agent_run_trace_disabled_without_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without LANGFUSE_PUBLIC_KEY, the trace must be a no-op — no client call."""
    from src.observability import setup

    monkeypatch.setattr(setup.settings, "LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr(setup, "get_langfuse", pytest.fail)  # would error if called

    with agent_run_trace("run-1", "question?") as observation:
        observation.update(output={"answer": "ok"}, metadata={}, usage_details={})

    # Reaching here without exception (or the pytest.fail hook firing) = pass.


@pytest.mark.asyncio
async def test_agent_run_trace_propagates_user_session_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With keys set, user/session context flows to propagate_attributes."""
    from src.observability import setup

    monkeypatch.setattr(setup.settings, "LANGFUSE_PUBLIC_KEY", "pk_test")

    propagated: dict[str, Any] = {}

    def fake_propagate(**kwargs: object):
        propagated.update(kwargs)

        from contextlib import nullcontext

        return nullcontext()

    monkeypatch.setattr(setup, "propagate_attributes", fake_propagate)

    captured_start: dict[str, Any] = {}
    fake_lf = _fake_client(captured_start, {})
    monkeypatch.setattr(setup, "get_langfuse", lambda: fake_lf)

    with agent_run_trace(
        "run-1", "question?", user_id="user-7", session_id="thread-9"
    ) as observation:
        observation.update(output={"answer": "ok"})

    assert propagated["user_id"] == "user-7"
    assert propagated["session_id"] == "thread-9"
    assert propagated["tags"] == ["feature:research"]
    assert captured_start["name"] == "research-agent-run"
    assert captured_start["as_type"] == "agent"


@pytest.mark.asyncio
async def test_traced_observation_disabled_without_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """traced_observation must be a no-op without keys — no client call."""
    from src.observability import setup

    monkeypatch.setattr(setup.settings, "LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr(setup, "get_langfuse", pytest.fail)

    with traced_observation("embed-texts", as_type="embedding") as observation:
        observation.update(output={"vectors": 3})


@pytest.mark.asyncio
async def test_traced_observation_records_output_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabled: records output; on exception marks ERROR and re-raises."""
    from src.observability import setup

    monkeypatch.setattr(setup.settings, "LANGFUSE_PUBLIC_KEY", "pk_test")

    captured_start: dict[str, Any] = {}
    captured_update: dict[str, Any] = {}
    fake_lf = _fake_client(captured_start, captured_update)
    monkeypatch.setattr(setup, "get_langfuse", lambda: fake_lf)

    with traced_observation(
        "rerank-passages",
        as_type="retriever",
        input={"query": "q"},
    ) as observation:
        observation.update(output={"scores": 2})

    assert captured_start["name"] == "rerank-passages"
    assert captured_start["as_type"] == "retriever"
    assert captured_update["output"] == {"scores": 2}

    with pytest.raises(RuntimeError, match="boom"), traced_observation("step-x"):
        raise RuntimeError("boom")

    assert captured_update["level"] == "ERROR"
    assert "step-x failed" in str(captured_update["status_message"])
