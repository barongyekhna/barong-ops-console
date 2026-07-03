"""rw throughput and product signals

Revision ID: 20260703_01_rw_throughput_signals
Revises: 20260702_05_rw_runtime_settings
Create Date: 2026-07-03 06:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260703_01_rw_throughput_signals"
down_revision = "20260702_05_rw_runtime_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE products_rw ADD COLUMN IF NOT EXISTS fulfillment_method TEXT")
    op.execute(
        "ALTER TABLE products_rw "
        "ADD COLUMN IF NOT EXISTS lithium_battery_warning BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute("ALTER TABLE products_rw ADD COLUMN IF NOT EXISTS margin_source TEXT")
    op.execute("ALTER TABLE products_rw ADD COLUMN IF NOT EXISTS margin_confidence TEXT")
    op.create_index(
        "ix_products_rw_fulfillment_method",
        "products_rw",
        ["fulfillment_method"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_products_rw_lithium_warning",
        "products_rw",
        ["lithium_battery_warning"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_products_rw_lithium_warning", table_name="products_rw", if_exists=True)
    op.drop_index("ix_products_rw_fulfillment_method", table_name="products_rw", if_exists=True)
    op.execute("ALTER TABLE products_rw DROP COLUMN IF EXISTS margin_confidence")
    op.execute("ALTER TABLE products_rw DROP COLUMN IF EXISTS margin_source")
    op.execute("ALTER TABLE products_rw DROP COLUMN IF EXISTS lithium_battery_warning")
    op.execute("ALTER TABLE products_rw DROP COLUMN IF EXISTS fulfillment_method")
