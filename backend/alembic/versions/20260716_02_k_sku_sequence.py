"""K leaf-category SKU sequence allocator.

Revision ID: 20260716_02_k_sku_sequence
Revises: 20260716_01_p_wc_category_map
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_02_k_sku_sequence"
down_revision: str | Sequence[str] | None = "20260716_01_p_wc_category_map"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "k_sku_sequences"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("leaf_key", sa.String(length=128), nullable=False),
        sa.Column("leaf_name", sa.String(length=512), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        # next_seq is the next number available after the last atomic allocation.
        sa.Column(
            "next_seq",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("next_seq > 0", name="ck_k_sku_sequences_next_positive"),
        sa.PrimaryKeyConstraint("leaf_key"),
        sa.UniqueConstraint("prefix", name="uq_k_sku_sequences_prefix"),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
