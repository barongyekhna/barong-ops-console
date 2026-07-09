"""K product reference_image_url (temporary 1688/Amazon ref image for I-system)

Filled on R→K transfer with the product's image URL; auto-loaded into the
I-system editor's reference images on 去I作图; cleared when the I output is
saved back to K. Not a long-lived asset — just the作图参考 handoff.

Revision ID: 20260709_04_k_reference_image
Revises: 20260709_03_k_product_category_binding
Create Date: 2026-07-09
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260709_04_k_reference_image"
down_revision: str | Sequence[str] | None = "20260709_03_k_product_category_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "k_product_knowledge_products"


def upgrade() -> None:
    op.add_column(T, sa.Column("reference_image_url", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    op.drop_column(T, "reference_image_url")
