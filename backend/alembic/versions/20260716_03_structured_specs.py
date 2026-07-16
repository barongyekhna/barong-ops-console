"""Persist verified 1688 structured specifications across F -> K.

Revision ID: 20260716_03_structured_specs
Revises: 20260716_02_k_sku_sequence
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260716_03_structured_specs"
down_revision: str | Sequence[str] | None = "20260716_02_k_sku_sequence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

F_CANDIDATES = "f_category_candidates"
K_PRODUCTS = "k_product_knowledge_products"


def _json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        F_CANDIDATES,
        sa.Column("structured_specs_json", _json_type(), nullable=True),
    )
    op.add_column(
        K_PRODUCTS,
        sa.Column("structured_specs_json", _json_type(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(K_PRODUCTS, "structured_specs_json")
    op.drop_column(F_CANDIDATES, "structured_specs_json")
