"""
shared/database.py
------------------
Purpose:    Async SQLAlchemy engine and session factory.
            One engine per process; sessions are per-request.
Dependencies: settings, sqlalchemy[asyncio], asyncpg
Scope:      Engine setup and get_session dependency only.
            Models live in each feature module (schema.md ownership boundaries).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.settings import settings

# ── Engine (one per process) ──────────────────────────────────────────────────
# ponytail: pool_pre_ping=True catches stale connections cheaply.
# Explicit pool bounds + pool_recycle keep sockets bounded across dev
# sleep/resume cycles (WinError 10055 hygiene — see ADR-009-era incident).
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.APP_DEBUG,  # SQL logging in debug mode only
    pool_size=5,
    max_overflow=10,
    pool_recycle=1800,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# ── Base class for all ORM models ─────────────────────────────────────────────
class Base(DeclarativeBase):
    """Import this in every feature's models.py to register with Alembic."""
    pass


# ── FastAPI dependency ────────────────────────────────────────────────────────
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a session per request; roll back on error, close always.
    Usage: session: AsyncSession = Depends(get_session)
    """
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Startup / shutdown ────────────────────────────────────────────────────────
async def connect() -> None:
    """Called in lifespan startup — warms the connection pool."""
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: None)  # ping


async def disconnect() -> None:
    """Called in lifespan shutdown."""
    await engine.dispose()
