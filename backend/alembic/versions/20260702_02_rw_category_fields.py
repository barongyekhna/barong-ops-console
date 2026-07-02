"""rw category and skill score fields

Revision ID: 20260702_02_rw_category_fields
Revises: 20260702_00_rw_initial_schema
Create Date: 2026-07-02 00:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260702_02_rw_category_fields"
down_revision = "20260702_00_rw_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE products_rw ADD COLUMN IF NOT EXISTS category_id TEXT")
    op.execute("ALTER TABLE products_rw ADD COLUMN IF NOT EXISTS category_path TEXT")
    op.execute("ALTER TABLE products_rw ADD COLUMN IF NOT EXISTS skill_score INTEGER")
    op.create_index("idx_products_rw_category_id", "products_rw", ["category_id"], if_not_exists=True)
    op.create_index("idx_products_rw_skill_score", "products_rw", ["skill_score"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("idx_products_rw_skill_score", table_name="products_rw")
    op.drop_index("idx_products_rw_category_id", table_name="products_rw")
    with op.batch_alter_table("products_rw") as batch_op:
        batch_op.drop_column("skill_score")
        batch_op.drop_column("category_path")
        batch_op.drop_column("category_id")
