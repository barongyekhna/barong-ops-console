"""K category specification templates and product completeness markers.

Revision ID: 20260718_01_k_category_spec_templates
Revises: 20260717_01_pdp_evidence
Create Date: 2026-07-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260718_01_k_category_spec_templates"
down_revision: str | Sequence[str] | None = "20260717_01_pdp_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

K_PRODUCTS = "k_product_knowledge_products"
K_SPEC_TEMPLATES = "k_category_spec_templates"


def _json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        K_SPEC_TEMPLATES,
        sa.Column("category_tree", sa.String(length=16), nullable=False),
        sa.Column("category_id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("fields", _json_type(), nullable=False),
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
        sa.CheckConstraint(
            "category_tree IN ('google', 'amazon')",
            name="ck_k_category_spec_templates_tree",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'approved')",
            name="ck_k_category_spec_templates_status",
        ),
        sa.PrimaryKeyConstraint(
            "category_tree",
            "category_id",
            name="pk_k_category_spec_templates",
        ),
    )
    op.create_index(
        "ix_k_category_spec_templates_status",
        K_SPEC_TEMPLATES,
        ["status"],
    )
    op.add_column(
        K_PRODUCTS,
        sa.Column(
            "specs_incomplete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        K_PRODUCTS,
        sa.Column("specs_missing_required_json", _json_type(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(K_PRODUCTS, "specs_missing_required_json")
    op.drop_column(K_PRODUCTS, "specs_incomplete")
    op.drop_index(
        "ix_k_category_spec_templates_status",
        table_name=K_SPEC_TEMPLATES,
    )
    op.drop_table(K_SPEC_TEMPLATES)
