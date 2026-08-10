"""add documents.content_hash for dedup + idempotency

Revision ID: b3e7a9f2c1d4
Revises: 8f3c2a1b9e7d
Create Date: 2026-08-10 14:30:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = 'b3e7a9f2c1d4'
down_revision = '8f3c2a1b9e7d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('content_hash', sa.String(length=64), nullable=True),
    )
    # Per-workspace uniqueness is enforced at the application layer (early
    # dedup check); the index just accelerates the lookup by hash.
    op.create_index('ix_documents_content_hash', 'documents', ['content_hash'])
    op.create_index(
        'ix_documents_workspace_content_hash',
        'documents',
        ['workspace_id', 'content_hash'],
    )


def downgrade() -> None:
    op.drop_index('ix_documents_workspace_content_hash', table_name='documents')
    op.drop_index('ix_documents_content_hash', table_name='documents')
    op.drop_column('documents', 'content_hash')
