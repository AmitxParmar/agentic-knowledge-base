"""
tests/observability/test_setup.py
---------------------------------
Purpose:    Verify the Langfuse agent-run tracing helper degrades gracefully
            when Langfuse keys are unset (no network, no errors) and that the
            no-op observation absorbs updates.

Dependencies: pytest, src.observability.setup
Scope:      Tracing wiring only — asserts no real Langfuse client is touched.
"""

from __future__ import annotations

import pytest

from src.observability.setup import _NoOpObservation, agent_run_trace


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
async def test_agent_run_trace_yields_observation_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With keys set, the trace yields a real observation that records output."""
    from src.observability import setup

    monkeypatch.setattr(setup.settings, "LANGFUSE_PUBLIC_KEY", "pk_test")

    captured: dict = {}

    class FakeObservation:
        def update(self, **kwargs: object) -> None:
            captured.update(kwargs)

    @staticmethod  # type: ignore[misc]
    def fake_start(*args: object, **kwargs: object):
        class _Ctx:
            def __enter__(self):
                return FakeObservation()

            def __exit__(self, *exc):
                return False

        return _Ctx()

    import types

    fake_lf = types.SimpleNamespace(start_as_current_observation=fake_start)
    monkeypatch.setattr(setup, "get_langfuse", lambda: fake_lf)

    with agent_run_trace("run-1", "question?") as observation:
        observation.update(output={"answer": "ok"}, metadata={"citations": 1})

    assert captured["output"] == {"answer": "ok"}
    assert captured["metadata"] == {"citations": 1}
