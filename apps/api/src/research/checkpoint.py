"""
research/checkpoint.py
---------------------
Purpose:    Async Postgres checkpointer for LangGraph, built on the project's
            existing asyncpg pool. Stores serialized CheckpointTuple blobs in
            langgraph_checkpoints so research runs persist across worker
            restarts and can be replayed by thread_id (ADR-001 action item #2).

            The released langgraph-checkpoint-postgres package ships only stub
            methods against the pinned langgraph 1.2.x, so this is a thin
            reimplementation of the storage layer — serialization is delegated
            to langgraph's own JsonPlusSerializer (msgpack+pickle fallback).

Dependencies: asyncpg (already installed), langgraph-checkpoint (serde only)
Scope:      Storage only. Graph/research logic lives in research/agent.py.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import asyncpg
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.settings import settings

_pool: asyncpg.Pool | None = None
_serde = JsonPlusSerializer()


def _configurable(config: RunnableConfig) -> dict[str, Any]:
    """Safely read the optional ``configurable`` section of a run config."""
    return config.get("configurable") or {}


async def _get_pool() -> asyncpg.Pool:
    """A small pool shared across the worker process.

    LangGraph calls aput and aput_writes back-to-back during a super-step, so a
    single connection can't serve both — a pool hands each call its own
    connection. Writes are single-statement and idempotent, so we grab a fresh
    connection per operation rather than starting an explicit transaction.
    """
    global _pool
    if _pool is None:
        dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, timeout=10)
    return _pool


async def close() -> None:
    """Dispose the shared checkpoint pool. Called on app/worker shutdown so
    the process doesn't leak its Postgres sockets past its own lifetime."""
    global _pool
    if _pool is not None:
        try:
            await _pool.close()
        finally:
            _pool = None


async def setup() -> None:
    """Idempotent schema creation. Safe to call on every worker start."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
                thread_id     TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                parent_id     TEXT,
                checkpoint    JSONB NOT NULL,
                metadata      JSONB NOT NULL,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_langgraph_checkpoints_thread
            ON langgraph_checkpoints (thread_id, checkpoint_ns, checkpoint_id)
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS langgraph_checkpoint_writes (
                thread_id     TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                task_id       TEXT NOT NULL,
                channel       TEXT NOT NULL,
                write_json    JSONB NOT NULL,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, channel)
            )
            """
        )


def _serialize(value: Any) -> str:
    """Serialize a checkpoint payload to a JSON text column."""
    type_, data = _serde.dumps_typed(value)
    if isinstance(data, bytes):
        return json.dumps({"t": type_, "d": data.hex()})
    return json.dumps({"t": type_, "d": data})


def _deserialize(blob: str) -> Any:
    type_, raw = json.loads(blob)["t"], json.loads(blob).get("d")
    if type_ in ("bytes", "bytearray"):
        return _serde.loads_typed((type_, bytes.fromhex(raw)))
    return _serde.loads_typed((type_, raw))


class AsyncPostgresSaver(BaseCheckpointSaver):
    """Minimal async checkpointer implementing the surface langgraph 1.2.x calls.

    Enough for: resume a run after restart (aget_tuple), persist progress
    (aput), store pending writes (aput_writes), and replay history (alist).
    """

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        pool = await _get_pool()
        cfg = _configurable(config)
        thread_id = cfg["thread_id"]
        checkpoint_ns = cfg.get("checkpoint_ns", "")
        checkpoint_id = cfg.get("checkpoint_id")

        async with pool.acquire() as conn:
            if checkpoint_id is not None:
                row = await conn.fetchrow(
                    """
                    SELECT checkpoint, metadata, parent_id
                    FROM langgraph_checkpoints
                    WHERE thread_id = $1 AND checkpoint_ns = $2 AND checkpoint_id = $3
                    """,
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT checkpoint, metadata, parent_id, checkpoint_id
                    FROM langgraph_checkpoints
                    WHERE thread_id = $1 AND checkpoint_ns = $2
                    ORDER BY checkpoint_id DESC LIMIT 1
                    """,
                    thread_id,
                    checkpoint_ns,
                )
            if row is None:
                return None

            stored_checkpoint_id = checkpoint_id or row["checkpoint_id"]
            parent_config: RunnableConfig | None = None
            if row["parent_id"]:
                parent_config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": row["parent_id"],
                    }
                }
            return CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": stored_checkpoint_id,
                    }
                },
                checkpoint=_deserialize(row["checkpoint"]),
                metadata=_deserialize(row["metadata"]),
                parent_config=parent_config,
                pending_writes=None,
            )

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Any,
    ) -> RunnableConfig:
        pool = await _get_pool()
        cfg = _configurable(config)
        thread_id = cfg["thread_id"]
        checkpoint_ns = cfg.get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]
        parent_id = cfg.get("parent_checkpoint_id")

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO langgraph_checkpoints
                    (thread_id, checkpoint_ns, checkpoint_id, parent_id, checkpoint, metadata)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
                ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id)
                DO UPDATE SET parent_id = EXCLUDED.parent_id,
                              checkpoint = EXCLUDED.checkpoint,
                              metadata   = EXCLUDED.metadata
                """,
                thread_id,
                checkpoint_ns,
                checkpoint_id,
                parent_id,
                _serialize(checkpoint),
                _serialize(metadata),
            )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store intermediate writes (pending tool-call results) by checkpoint."""
        if not writes:
            return
        pool = await _get_pool()
        cfg = _configurable(config)
        thread_id = cfg["thread_id"]
        checkpoint_ns = cfg.get("checkpoint_ns", "")
        checkpoint_id = cfg["checkpoint_id"]
        rows = [
            (thread_id, checkpoint_ns, checkpoint_id, task_id, channel, _serialize(value))
            for channel, value in writes
        ]
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO langgraph_checkpoint_writes
                    (thread_id, checkpoint_ns, checkpoint_id, task_id, channel, write_json)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, channel)
                DO UPDATE SET write_json = EXCLUDED.write_json
                """,
                rows,
            )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> list[CheckpointTuple]:
        pool = await _get_pool()
        if config is None:
            return []
        cfg = _configurable(config)
        thread_id = cfg["thread_id"]
        checkpoint_ns = cfg.get("checkpoint_ns", "")

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT checkpoint_id, checkpoint, metadata, parent_id
                FROM langgraph_checkpoints
                WHERE thread_id = $1 AND checkpoint_ns = $2
                ORDER BY checkpoint_id
                """,
                thread_id,
                checkpoint_ns,
            )
        tuples: list[CheckpointTuple] = []
        for row in rows:
            tuples.append(
                CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": row["checkpoint_id"],
                        }
                    },
                    checkpoint=_deserialize(row["checkpoint"]),
                    metadata=_deserialize(row["metadata"]),
                    parent_config=(
                        {
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": row["parent_id"],
                            }
                        }
                        if row["parent_id"]
                        else None
                    ),
                    pending_writes=None,
                )
            )
        return tuples


async def get_saver() -> AsyncPostgresSaver:
    """Factory: ensures schema exists and returns a shared saver instance."""
    await setup()
    return AsyncPostgresSaver()


# Stable import path used by research/agent.py
__all__ = ["AsyncPostgresSaver", "get_saver", "setup"]
