"""add research_runs.token_count for per-run cost metering

Revision ID: f2c8d4e6a9b1
Revises: b3e7a9f2c1d4
Create Date: 2026-08-10 16:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = 'f2c8d4e6a9b1'
down_revision = 'b3e7a9f2c1d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'research_runs',
        sa.Column('token_count', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('research_runs', 'token_count')
