"""add pgvector embedding column to chunks

Revision ID: 9f2a1c3b4e5d
Revises: dff4f4038646
Create Date: 2026-08-04 16:08:50.169280

Stores chunk embeddings in Postgres (pgvector) so the vector index survives
cold starts — no in-memory Turbovec rebuild or re-embedding on boot.

NOTE: dimension is fixed at migration time. Must match settings.EMBEDDING_DIM
(1024 for BGE-M3). Changing embedding models later requires a new migration.
"""
from __future__ import annotations

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# BGE-M3 dimension (must equal settings.EMBEDDING_DIM)
EMBEDDING_DIM = 1024

# revision identifiers, used by Alembic.
revision = '9f2a1c3b4e5d'
down_revision = 'dff4f4038646'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector extension — enabled by default on Neon, required on self-hosted PG
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # Nullable so existing rows migrate cleanly; new chunks always populate it.
    op.add_column(
        "chunks",
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chunks", "embedding")
    # Intentionally leave the vector extension in place (drop is invasive).
