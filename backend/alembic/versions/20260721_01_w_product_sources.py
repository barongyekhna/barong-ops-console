"""W-S product source links.

Revision ID: 20260721_01_w_product_sources
Revises: 20260719_02_cs_replies
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_01_w_product_sources"
down_revision: str | Sequence[str] | None = "20260719_02_cs_replies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "w_product_sources"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("supplier_name", sa.String(length=200), nullable=True),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "currency",
            sa.String(length=8),
            nullable=False,
            server_default="CNY",
        ),
        sa.Column("moq", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            onupdate=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w_product_sources"),
        sa.UniqueConstraint("sku", name="uq_w_product_sources_sku"),
    )
    op.create_index("ix_w_product_sources_sku", TABLE, ["sku"])


def downgrade() -> None:
    op.drop_index("ix_w_product_sources_sku", table_name=TABLE)
    op.drop_table(TABLE)
