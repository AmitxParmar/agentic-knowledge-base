"""add tsvector GIN index for full-text search

Revision ID: a1b2c3d4e5f6
Revises: 9f2a1c3b4e5d
Create Date: 2026-08-04 16:26:42.137834

Full-text ranking previously computed to_tsvector() on the fly for every query
against every candidate row — no index, O(n) scan. This adds a generated
`tsv` column (always in sync with text) plus a GIN index so PostgreSQL
full-text search uses the index instead of a table scan. Generated column
keeps it in sync without a trigger.
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '9f2a1c3b4e5d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Generated tsvector column — Postgres recomputes it automatically on write.
    op.execute(
        "ALTER TABLE chunks "
        "ADD COLUMN tsv tsvector GENERATED ALWAYS AS "
        "(to_tsvector('english', text)) STORED"
    )
    # GIN index makes the @@ operator in full-text searches index-backed.
    op.execute("CREATE INDEX ix_chunks_tsv_gin ON chunks USING GIN (tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_tsv_gin")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv")
