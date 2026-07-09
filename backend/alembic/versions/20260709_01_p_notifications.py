"""Console notification inbox: p_notifications table

Append-only event log surfaced by the console inbox; the P upload pipeline /
n8n callbacks (and in-console emitters) write rows here.

Revision ID: 20260709_01_p_notifications
Revises: 20260708_03_k_plain_chinese
Create Date: 2026-07-09
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260709_01_p_notifications"
down_revision: str | Sequence[str] | None = "20260708_03_k_plain_chinese"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "p_notifications"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.String(length=40), nullable=True),
        sa.Column(
            "source",
            sa.String(length=128),
            nullable=False,
            server_default="system",
        ),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column(
            "level",
            sa.String(length=16),
            nullable=False,
            server_default="info",
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("external_refs", JSONB(), nullable=True),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="unread",
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_p_notifications_status_created",
        TABLE,
        ["status", "created_at"],
    )
    op.create_index("ix_p_notifications_org", TABLE, ["org_id"])
    op.create_index("ix_p_notifications_product", TABLE, ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_p_notifications_product", table_name=TABLE)
    op.drop_index("ix_p_notifications_org", table_name=TABLE)
    op.drop_index("ix_p_notifications_status_created", table_name=TABLE)
    op.drop_table(TABLE)
