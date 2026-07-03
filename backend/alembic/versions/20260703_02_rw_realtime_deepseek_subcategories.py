"""rw realtime deepseek titles and subcategory indexes

Revision ID: 20260703_02_rw_realtime_deepseek
Revises: 20260703_01_rw_throughput_signals
Create Date: 2026-07-03 13:40:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "20260703_02_rw_realtime_deepseek"
down_revision = "20260703_01_rw_throughput_signals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE products_rw ADD COLUMN IF NOT EXISTS title_zh TEXT")
    op.execute("ALTER TABLE products_rw ADD COLUMN IF NOT EXISTS title_zh_source TEXT")
    op.execute("ALTER TABLE products_rw ADD COLUMN IF NOT EXISTS title_zh_updated_at TIMESTAMPTZ")
    op.create_index(
        "ix_products_rw_category_id_updated",
        "products_rw",
        ["category_id", "updated_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_products_rw_title_zh",
        "products_rw",
        ["title_zh"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_products_rw_title_zh", table_name="products_rw", if_exists=True)
    op.drop_index("ix_products_rw_category_id_updated", table_name="products_rw", if_exists=True)
    op.execute("ALTER TABLE products_rw DROP COLUMN IF EXISTS title_zh_updated_at")
    op.execute("ALTER TABLE products_rw DROP COLUMN IF EXISTS title_zh_source")
    op.execute("ALTER TABLE products_rw DROP COLUMN IF EXISTS title_zh")
