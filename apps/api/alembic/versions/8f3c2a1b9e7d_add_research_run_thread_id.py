"""add research_run thread_id

Revision ID: 8f3c2a1b9e7d
Revises: 0063abdd50a0
Create Date: 2026-08-08 22:10:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = '8f3c2a1b9e7d'
down_revision = '0063abdd50a0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'research_runs',
        sa.Column('thread_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_research_runs_thread_id',
        'research_runs',
        'conversation_threads',
        ['thread_id'],
        ['id'],
    )
    op.create_index('ix_research_runs_thread_id', 'research_runs', ['thread_id'])


def downgrade() -> None:
    op.drop_index('ix_research_runs_thread_id', table_name='research_runs')
    op.drop_constraint('fk_research_runs_thread_id', 'research_runs', type_='foreignkey')
    op.drop_column('research_runs', 'thread_id')
