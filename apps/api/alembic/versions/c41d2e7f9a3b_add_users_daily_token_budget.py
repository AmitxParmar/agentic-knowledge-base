"""add users.daily_token_budget for per-user cost enforcement

Revision ID: c41d2e7f9a3b
Revises: f2c8d4e6a9b1
Create Date: 2026-09-28 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "c41d2e7f9a3b"
down_revision = "f2c8d4e6a9b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("daily_token_budget", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "daily_token_budget")
