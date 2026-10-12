"""create applications and meta tables

Revision ID: 0001
Revises:
Create Date: 2026-10-12

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("provider", sa.JSON(), nullable=False),
        sa.Column("user", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=True),
    )
    op.create_index("ix_applications_key", "applications", ["key"], unique=True)

    op.create_table(
        "meta",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("meta")
    op.drop_index("ix_applications_key", table_name="applications")
    op.drop_table("applications")
