"""CS outbound reply history.

Revision ID: 20260719_02_cs_replies
Revises: 20260719_01_cs_customer_service
Create Date: 2026-07-19
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260719_02_cs_replies"
down_revision: str | Sequence[str] | None = "20260719_01_cs_customer_service"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "cs_replies"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sent_by", sa.BigInteger(), nullable=False),
        sa.Column("delivery_status", sa.String(length=20), nullable=False),
        sa.Column("provider_note", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(body) BETWEEN 1 AND 10000",
            name="ck_cs_replies_body_length",
        ),
        sa.CheckConstraint(
            "delivery_status IN ('sent', 'failed')",
            name="ck_cs_replies_valid_delivery_status",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["cs_messages.id"],
            name="fk_cs_replies_message_id_cs_messages",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sent_by"],
            ["users.id"],
            name="fk_cs_replies_sent_by_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cs_replies"),
    )
    op.create_index("ix_cs_replies_message_id", TABLE, ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_cs_replies_message_id", table_name=TABLE)
    op.drop_table(TABLE)
