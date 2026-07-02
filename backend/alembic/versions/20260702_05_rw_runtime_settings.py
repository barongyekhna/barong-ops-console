"""rw runtime settings

Revision ID: 20260702_05_rw_runtime_settings
Revises: 20260702_04_rw_realtime_engine
Create Date: 2026-07-02 18:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260702_05_rw_runtime_settings"
down_revision = "20260702_04_rw_realtime_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rw_runtime_settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("key"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("rw_runtime_settings", if_exists=True)
