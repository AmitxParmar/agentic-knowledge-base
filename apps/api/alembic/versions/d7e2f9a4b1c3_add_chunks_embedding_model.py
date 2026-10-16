"""add chunks.embedding_model for embedding provenance

Revision ID: d7e2f9a4b1c3
Revises: c41d2e7f9a3b
Create Date: 2026-10-16 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "d7e2f9a4b1c3"
down_revision = "c41d2e7f9a3b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
    )
    # The /readyz embedding-version advisory runs DISTINCT over this column;
    # the index keeps that cheap on larger corpora. Pre-tracking rows stay
    # NULL ("unversioned") — provenance cannot be reconstructed honestly.
    op.create_index(
        "ix_chunks_embedding_model",
        "chunks",
        ["embedding_model"],
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_embedding_model", table_name="chunks")
    op.drop_column("chunks", "embedding_model")
