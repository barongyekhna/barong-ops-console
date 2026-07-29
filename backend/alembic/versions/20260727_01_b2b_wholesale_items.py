"""B2B wholesale catalogue items.

Revision ID: 20260727_01_b2b_wholesale_items
Revises: 20260721_01_w_product_sources
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_01_b2b_wholesale_items"
down_revision: str | Sequence[str] | None = "20260721_01_w_product_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "b2b_wholesale_items"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("k_product_id", sa.Uuid(), nullable=True),
        sa.Column("woo_product_id", sa.Integer(), nullable=True),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("product_name", sa.String(length=512), nullable=False),
        sa.Column("category_path", sa.JSON(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("msrp", sa.Numeric(12, 2), nullable=True),
        sa.Column("wholesale_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_tiers_json", sa.JSON(), nullable=True),
        sa.Column("case_pack", sa.Integer(), nullable=True),
        sa.Column("moq_units", sa.Integer(), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("variant_note", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "needs_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("review_reason", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku", name="uq_b2b_wholesale_items_sku"),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'archived')",
            name="ck_b2b_wholesale_items_status",
        ),
        sa.CheckConstraint(
            "wholesale_price IS NULL OR wholesale_price >= 0",
            name="ck_b2b_wholesale_items_wholesale_price",
        ),
        sa.CheckConstraint(
            "case_pack IS NULL OR case_pack > 0",
            name="ck_b2b_wholesale_items_case_pack",
        ),
        sa.CheckConstraint(
            "moq_units IS NULL OR moq_units > 0",
            name="ck_b2b_wholesale_items_moq_units",
        ),
        sa.CheckConstraint(
            "lead_time_days IS NULL OR lead_time_days >= 0",
            name="ck_b2b_wholesale_items_lead_time_days",
        ),
    )
    op.create_index(
        "ix_b2b_wholesale_items_status",
        TABLE,
        ["status"],
    )
    op.create_index(
        "ix_b2b_wholesale_items_needs_review",
        TABLE,
        ["needs_review"],
    )
    op.create_index(
        "ix_b2b_wholesale_items_k_product_id",
        TABLE,
        ["k_product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_b2b_wholesale_items_k_product_id", table_name=TABLE)
    op.drop_index("ix_b2b_wholesale_items_needs_review", table_name=TABLE)
    op.drop_index("ix_b2b_wholesale_items_status", table_name=TABLE)
    op.drop_table(TABLE)
