"""K product category binding: amazon_category_id + category_review_needed

Amazon-group products bind to their Keepa category directly; DTC-group products
get the aligned Google category (google_product_category). When alignment is
low-confidence or missing, category_review_needed flags it for the operator.

Revision ID: 20260709_03_k_product_category_binding
Revises: 20260709_02_k_category_trees
Create Date: 2026-07-09
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260709_03_k_product_category_binding"
down_revision: str | Sequence[str] | None = "20260709_02_k_category_trees"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "k_product_knowledge_products"


def upgrade() -> None:
    op.add_column(T, sa.Column("amazon_category_id", sa.String(length=32), nullable=True))
    op.add_column(
        T,
        sa.Column(
            "category_review_needed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_kpk_products_amazon_category", T, ["amazon_category_id"])


def downgrade() -> None:
    op.drop_index("ix_kpk_products_amazon_category", table_name=T)
    op.drop_column(T, "category_review_needed")
    op.drop_column(T, "amazon_category_id")
