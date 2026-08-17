"""
Retrieval FTS tests — verify PostgreSQL Full-Text Search behavior without a
live DB. A fake session captures the compiled SQL so we can assert the
lexical query scopes by workspace allowlist, matches via `@@`, and ranks via
`ts_rank_cd`.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

import src.shared.models  # noqa: F401 — register all ORM models before mapper resolution
from src.retrieval.pipeline import _fts_search, _hybrid_search


class _FakeSession:
    """Captures the SQLAlchemy statement passed to execute()."""

    def __init__(self) -> None:
        self.captured: Any = None
        self._execute = AsyncMock()

    async def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> Any:
        self.captured = stmt
        return await self._execute(stmt, *args, **kwargs)


def _compiled(session: _FakeSession) -> Any:
    return session.captured.compile(dialect=postgresql.dialect())


@pytest.mark.asyncio
async def test_fts_search_scopes_to_allowlist_and_ranks() -> None:
    session = _FakeSession()
    allowed = [str(uuid.uuid4()), str(uuid.uuid4())]
    session._execute.return_value = MagicMock(
        all=lambda: [(allowed[0], 0.8), (allowed[1], 0.5)]
    )

    results = await _fts_search("status_code", allowed, session, top_k=10)  # type: ignore[arg-type]

    compiled = _compiled(session)
    sql = str(compiled)
    # Workspace filtering — allowlisted chunk ids are bound into the query.
    bound = list(compiled.params.values())
    assert allowed in bound
    # Keyword matching — @@ against the stored tsvector column (no per-query to_tsvector).
    assert "@@" in sql
    assert "tsv" in sql
    assert "to_tsvector" not in sql
    # Ranking — cover-density rank ordered descending.
    assert "ts_rank_cd" in sql
    assert "ORDER BY rank DESC" in sql

    assert results == [(allowed[0], 0.8), (allowed[1], 0.5)]


@pytest.mark.asyncio
async def test_hybrid_search_combines_dense_and_fts() -> None:
    """Hybrid retrieval must feed both ranked lists into RRF."""
    session = _FakeSession()
    workspace = uuid.uuid4()

    with (
        patch("src.retrieval.pipeline._get_workspace_chunk_ids", new=AsyncMock(return_value=["c1", "c2", "c3"])),
        patch("src.retrieval.pipeline.embed_query", new=AsyncMock(return_value=[0.1, 0.2])),
        patch("src.retrieval.pipeline.vector_search", new=AsyncMock(return_value=[])),
        patch("src.retrieval.pipeline._fts_search", new=AsyncMock(return_value=[("c1", 1.0)])),
        patch("src.retrieval.pipeline._reciprocal_rank_fusion", new=MagicMock(return_value=["c1"])) as rrf,
        patch("src.retrieval.pipeline._hydrate_chunks", new=AsyncMock(return_value=[])),
    ):
        await _hybrid_search("query", workspace, session, pool=10)  # type: ignore[arg-type]

    dense_calls = rrf.call_args.args[0]
    fts_calls = rrf.call_args.args[1]
    assert dense_calls == []
    assert fts_calls == [("c1", 1.0)]
