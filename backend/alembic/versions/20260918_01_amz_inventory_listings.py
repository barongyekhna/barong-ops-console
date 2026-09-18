"""A1/A2/A4 补齐:FBA 库存日表、自家 listing 日快照、请求留评台账、评论日期列。

无 org_id 列(家规 14)。to_regclass / 列探测幂等。

Revision ID: 20260918_01_amz_inventory_listings
Revises: 20260917_05_amz_ba_top_clicks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260918_01_amz_inventory_listings"
down_revision = "20260917_05_amz_ba_top_clicks"
branch_labels = None
depends_on = None


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT 1 FROM information_schema.columns WHERE table_name = %(t)s AND column_name = %(c)s", {"t": table, "c": column}).scalar())


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _json_default(conn, literal: str):
    return sa.text(f"'{literal}'::jsonb") if conn.dialect.name == "postgresql" else literal


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "amz_inventory_daily"):
        op.create_table(
            "amz_inventory_daily",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("store_code", sa.String(length=16), sa.ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False),
            sa.Column("snap_date", sa.Date(), nullable=False),
            sa.Column("sku", sa.String(length=128), nullable=False),
            sa.Column("asin", sa.String(length=16), nullable=True),
            sa.Column("fnsku", sa.String(length=16), nullable=True),
            sa.Column("fulfillable", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("inbound", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reserved", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unfulfillable", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("raw", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("store_code", "snap_date", "sku", name="uq_amz_inventory_daily_store_day_sku"),
        )
    if not _table_exists(conn, "amz_listing_snapshots"):
        op.create_table(
            "amz_listing_snapshots",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("store_code", sa.String(length=16), sa.ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False),
            sa.Column("sku", sa.String(length=128), nullable=False),
            sa.Column("snap_date", sa.Date(), nullable=False),
            sa.Column("asin", sa.String(length=16), nullable=True),
            sa.Column("status", sa.String(length=64), nullable=True),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("bullets", _json(), nullable=False, server_default=_json_default(conn, "[]")),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("price", sa.Numeric(10, 2), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("store_code", "sku", "snap_date", name="uq_amz_listing_snap_day"),
        )
    if not _table_exists(conn, "amz_solicitations"):
        op.create_table(
            "amz_solicitations",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("store_code", sa.String(length=16), sa.ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False),
            sa.Column("order_id", sa.String(length=32), nullable=False),
            sa.Column("sku", sa.String(length=128), nullable=True),
            sa.Column("ordered_on", sa.Date(), nullable=True),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("store_code", "order_id", name="uq_amz_solicitations_store_order"),
        )
    if _table_exists(conn, "amz_reviews") and not _column_exists(conn, "amz_reviews", "posted_on"):
        op.add_column("amz_reviews", sa.Column("posted_on", sa.Date(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "amz_reviews") and _column_exists(conn, "amz_reviews", "posted_on"):
        op.drop_column("amz_reviews", "posted_on")
    for name in ("amz_solicitations", "amz_listing_snapshots", "amz_inventory_daily"):
        if _table_exists(conn, name):
            op.drop_table(name)
