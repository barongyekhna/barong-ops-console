"""Evidence-driven PDP selling points and FAQ research.

Revision ID: 20260717_01_pdp_evidence
Revises: 20260716_03_structured_specs
Create Date: 2026-07-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260717_01_pdp_evidence"
down_revision: str | Sequence[str] | None = "20260716_03_structured_specs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

K_PRODUCTS = "k_product_knowledge_products"


def _json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    for column_name in (
        "selling_points_candidates_json",
        "selling_points_approved_json",
        "faq_research_json",
    ):
        op.add_column(
            K_PRODUCTS,
            sa.Column(column_name, _json_type(), nullable=True),
        )


def downgrade() -> None:
    for column_name in (
        "faq_research_json",
        "selling_points_approved_json",
        "selling_points_candidates_json",
    ):
        op.drop_column(K_PRODUCTS, column_name)
