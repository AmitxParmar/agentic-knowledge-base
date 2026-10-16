"""
tests/research/test_usage.py
----------------------------
Per-user token metering and daily budget enforcement. DB calls are mocked
at the session boundary — no live Postgres needed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.research.agent import run_agent
from src.research.router import _error_code
from src.research.usage import (
    BudgetExceededError,
    _day_start,
    _month_start,
    enforce_budget,
    get_budget_status,
    workspace_today_tokens,
)


def _session_sums(today: int, month: int, budget: int | None) -> Any:
    # Step 1: fake the three aggregate queries in call order
    # (today sum, month sum, user budget row).
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            SimpleNamespace(scalar=lambda: today),
            SimpleNamespace(scalar=lambda: month),
            SimpleNamespace(scalar_one_or_none=lambda: budget),
        ]
    )
    return session


def test_day_and_month_start_floor_correctly() -> None:
    now = datetime(2026, 9, 28, 15, 30, tzinfo=UTC)
    assert _day_start(now) == datetime(2026, 9, 28, tzinfo=UTC)
    assert _month_start(now) == datetime(2026, 9, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_budget_status_reports_spend_and_ratio() -> None:
    status = await get_budget_status(_session_sums(500, 2000, 1000), uuid.uuid4())
    assert status.today_tokens == 500
    assert status.month_tokens == 2000
    assert status.daily_budget == 1000
    assert status.over_budget is False
    assert status.pct_used == 0.5


@pytest.mark.asyncio
async def test_unlimited_budget_never_over() -> None:
    status = await get_budget_status(_session_sums(10**9, 10**9, None), uuid.uuid4())
    assert status.daily_budget is None
    assert status.over_budget is False
    assert status.pct_used is None


@pytest.mark.asyncio
async def test_enforce_blocks_exhausted_budget() -> None:
    with pytest.raises(BudgetExceededError) as exc_info:
        await enforce_budget(_session_sums(1000, 5000, 1000), uuid.uuid4())
    assert exc_info.value.http_status == 429


@pytest.mark.asyncio
async def test_enforce_passes_with_remaining_budget() -> None:
    status = await enforce_budget(_session_sums(100, 500, 1000), uuid.uuid4())
    assert status.over_budget is False


@pytest.mark.asyncio
async def test_error_code_maps_budget() -> None:
    assert _error_code(BudgetExceededError("spent")) == "BUDGET_EXCEEDED"


@pytest.mark.asyncio
async def test_run_agent_refuses_over_budget_user(monkeypatch: pytest.MonkeyPatch) -> None:
    # Step 1: force the budget gate to refuse...
    async def refuse(session: Any, user_id: Any) -> Any:
        raise BudgetExceededError("spent")

    monkeypatch.setattr("src.research.agent.enforce_budget", refuse)
    # Step 2: ...run_agent must surface the refusal before touching the graph.
    with pytest.raises(BudgetExceededError):
        await run_agent(
            question="q",
            workspace_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            session=AsyncMock(),
            user_id=str(uuid.uuid4()),
        )


@pytest.mark.asyncio
async def test_workspace_today_tokens_sums_all_users() -> None:
    """The workspace soft ceiling aggregates every user's runs for today."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=SimpleNamespace(scalar=lambda: 4321))
    total = await workspace_today_tokens(session, uuid.uuid4())
    assert total == 4321
