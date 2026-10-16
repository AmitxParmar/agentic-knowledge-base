"""
tests/research/test_empty_corpus.py
-------------------------------------
Purpose:    Empty-retrieval UX: "no searchable documents" (upload first) and
            "documents exist but nothing matched" (rephrase) are distinct
            refusals, so the UI guides the user to the right next step.
Dependencies: pytest.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.research.agent import (
    _INSUFFICIENT_EVIDENCE_RESPONSE,
    _NO_DOCUMENTS_RESPONSE,
    _workspace_has_searchable_docs,
    run_agent,
)


def _session_with_doc_count(count: int) -> Any:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one = MagicMock(return_value=count)
    session.execute = AsyncMock(return_value=result)
    return session


def _empty_final_state() -> dict[str, Any]:
    return {"citations": [], "answer": None, "iterations": 1, "tokens_used": 10}


def _mock_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(return_value=_empty_final_state())
    monkeypatch.setattr("src.research.agent._get_graph", AsyncMock(return_value=mock_graph))
    monkeypatch.setattr("src.research.agent._persist_citations", AsyncMock())


async def test_empty_workspace_points_at_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero finished docs → the refusal says to upload, not to rephrase."""
    _mock_graph(monkeypatch)
    result = await run_agent(
        question="What does the report say?",
        workspace_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        session=_session_with_doc_count(0),
    )
    assert result.answer == _NO_DOCUMENTS_RESPONSE
    assert result.answer != _INSUFFICIENT_EVIDENCE_RESPONSE


async def test_docs_but_no_match_points_at_rephrase(monkeypatch: pytest.MonkeyPatch) -> None:
    """Finished docs exist but nothing matched → the rephrase refusal."""
    _mock_graph(monkeypatch)
    result = await run_agent(
        question="What does the report say about unrelated topic X?",
        workspace_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        session=_session_with_doc_count(3),
    )
    assert result.answer == _INSUFFICIENT_EVIDENCE_RESPONSE


async def test_searchable_docs_check_fails_open() -> None:
    """A DB failure on the COUNT must not flip the refusal to upload-first —
    the generic insufficient-evidence message is the safe fallback."""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    assert await _workspace_has_searchable_docs(session, uuid.uuid4()) is True
