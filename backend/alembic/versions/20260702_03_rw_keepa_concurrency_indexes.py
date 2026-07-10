"""rw keepa concurrency indexes

Revision ID: 20260702_03_rw_keepa_concurrency_indexes
Revises: 20260702_02_rw_category_fields
Create Date: 2026-07-02 10:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260702_03_rw_keepa_concurrency_indexes"
down_revision = "20260702_02_rw_category_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic creates version_num as VARCHAR(32), but this revision id is 40
    # characters. Widen it before Alembic records this migration.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=128),
        existing_nullable=False,
    )
    op.create_index("idx_products_rw_asin", "products_rw", ["asin"], if_not_exists=True)
    op.create_index("idx_products_rw_updated_at", "products_rw", ["updated_at"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("idx_products_rw_updated_at", table_name="products_rw", if_exists=True)
    op.drop_index("idx_products_rw_asin", table_name="products_rw", if_exists=True)
