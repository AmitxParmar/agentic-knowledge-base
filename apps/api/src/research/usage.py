"""
research/usage.py
-----------------
Per-user LLM token metering and daily budget enforcement.

Token spend is already recorded per run (ResearchRun.token_count); this
module aggregates it per user and blocks new agent runs once the
configured daily budget is exhausted. Enforcement lives in run_agent so
every transport (SSE chat, WebSocket, voice) is covered by one check.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import logfire
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings
from src.auth.models import User
from src.research.models import ResearchRun
from src.shared.errors import ResearchWorkspaceError

logger = logging.getLogger(__name__)

# Warn at 80% of budget so the client can surface "almost out" states.
_BUDGET_WARN_RATIO = 0.8


class BudgetExceededError(ResearchWorkspaceError):
    """Daily LLM token budget exhausted — the run is refused, not started."""

    http_status = 429


@dataclass(frozen=True)
class BudgetStatus:
    """Point-in-time usage snapshot for one user."""

    today_tokens: int
    month_tokens: int
    daily_budget: int | None
    over_budget: bool
    pct_used: float | None


def _day_start(now: datetime) -> datetime:
    # Step 1: floor the current UTC time to midnight — the daily window.
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(now: datetime) -> datetime:
    # Step 1: floor to the first of the month — the monthly window.
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _sum_tokens(session: AsyncSession, user_id: uuid.UUID, since: datetime) -> int:
    # Step 1: sum token_count over the user's completed runs in the window.
    result = await session.execute(
        select(func.coalesce(func.sum(ResearchRun.token_count), 0)).where(
            ResearchRun.user_id == user_id,
            ResearchRun.created_at >= since,
        )
    )
    return int(result.scalar() or 0)


async def workspace_today_tokens(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    """Today's token spend across ALL users in a workspace.

    The daily budget is enforced per user (single-tenant MVP); this
    workspace-wide sum is the soft ceiling that makes a runaway workspace
    visible on the usage dashboard and in logs before hard limits land.
    """
    # Step 1: one aggregate over today's runs in the workspace.
    result = await session.execute(
        select(func.coalesce(func.sum(ResearchRun.token_count), 0)).where(
            ResearchRun.workspace_id == workspace_id,
            ResearchRun.created_at >= _day_start(datetime.now(UTC)),
        )
    )
    return int(result.scalar() or 0)


async def _effective_budget(session: AsyncSession, user_id: uuid.UUID) -> int | None:
    # Step 1: the user's own budget wins when set...
    result = await session.execute(select(User.daily_token_budget).where(User.id == user_id))
    row_budget = result.scalar_one_or_none()
    if row_budget is not None:
        return int(row_budget)
    # Step 2: ...otherwise fall back to the instance default (None = unlimited).
    return settings.DEFAULT_DAILY_TOKEN_BUDGET


async def get_budget_status(session: AsyncSession, user_id: uuid.UUID) -> BudgetStatus:
    """Aggregate today's + this month's token spend against the budget."""
    # Step 1: gather spend in both windows and the effective budget.
    now = datetime.now(UTC)
    today = await _sum_tokens(session, user_id, _day_start(now))
    month = await _sum_tokens(session, user_id, _month_start(now))
    budget = await _effective_budget(session, user_id)
    # Step 2: derive the over-budget flag and usage ratio.
    over = budget is not None and today >= budget
    pct = round(today / budget, 4) if budget else None
    return BudgetStatus(
        today_tokens=today,
        month_tokens=month,
        daily_budget=budget,
        over_budget=over,
        pct_used=pct,
    )


async def enforce_budget(session: AsyncSession, user_id: uuid.UUID) -> BudgetStatus:
    """Block the run when the daily budget is exhausted; warn near the edge.

    Returns the status for telemetry. Raises BudgetExceededError (HTTP 429
    via the domain-error handler) when no budget remains.
    """
    # Step 1: measure current spend — a single cheap aggregate query.
    status = await get_budget_status(session, user_id)
    if status.daily_budget is None:
        return status
    # Step 2: refuse when exhausted; warn when inside the 80% band.
    if status.over_budget:
        logger.warning(
            "research.budget_exceeded: user=%s today=%d budget=%d",
            user_id,
            status.today_tokens,
            status.daily_budget,
        )
        logfire.warn(
            "research.budget_exceeded",
            user_id=str(user_id),
            today_tokens=status.today_tokens,
            daily_budget=status.daily_budget,
        )
        raise BudgetExceededError(
            "Daily token budget exhausted. Please try again tomorrow.",
            detail=f"user={user_id} today={status.today_tokens} budget={status.daily_budget}",
        )
    if status.pct_used is not None and status.pct_used >= _BUDGET_WARN_RATIO:
        logfire.warn(
            "research.budget_warning",
            user_id=str(user_id),
            today_tokens=status.today_tokens,
            daily_budget=status.daily_budget,
        )
    return status
