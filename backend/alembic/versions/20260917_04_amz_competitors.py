"""A4 竞品盯盘:amz_competitors(盯哪些 ASIN)、amz_competitor_snapshots(每天一张快照,来自 Keepa)。

无 org_id 列(家规 14)。to_regclass 幂等。

Revision ID: 20260917_04_amz_competitors
Revises: 20260917_03_amz_launches
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260917_04_amz_competitors"
down_revision = "20260917_03_amz_launches"
branch_labels = None
depends_on = None

TABLES = ("amz_competitor_snapshots", "amz_competitors")


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _json_default(conn, literal: str):
    return sa.text(f"'{literal}'::jsonb") if conn.dialect.name == "postgresql" else literal


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "amz_competitors"):
        op.create_table(
            "amz_competitors",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("marketplace", sa.String(length=4), nullable=False),
            sa.Column("asin", sa.String(length=16), nullable=False),
            sa.Column("product_line", sa.String(length=32), nullable=False, server_default="other"),
            sa.Column("whose", sa.String(length=16), nullable=False, server_default="competitor"),
            sa.Column("label", sa.String(length=120), nullable=True),
            sa.Column("source", sa.String(length=16), nullable=False, server_default="manual"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("marketplace", "asin", name="uq_amz_competitors_market_asin"),
        )
    if not _table_exists(conn, "amz_competitor_snapshots"):
        op.create_table(
            "amz_competitor_snapshots",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("marketplace", sa.String(length=4), nullable=False),
            sa.Column("asin", sa.String(length=16), nullable=False),
            sa.Column("snap_date", sa.Date(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("brand", sa.String(length=120), nullable=True),
            sa.Column("price", sa.Numeric(10, 2), nullable=True),
            sa.Column("in_stock", sa.Boolean(), nullable=True),
            sa.Column("rating", sa.Numeric(3, 1), nullable=True),
            sa.Column("reviews", sa.Integer(), nullable=True),
            sa.Column("bsr", sa.Integer(), nullable=True),
            sa.Column("monthly_sold", sa.Integer(), nullable=True),
            sa.Column("coupon", sa.String(length=64), nullable=True),
            sa.Column("raw", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("marketplace", "asin", "snap_date", name="uq_amz_competitor_snap_day"),
        )
        op.create_index("ix_amz_competitor_snapshots_asin_date", "amz_competitor_snapshots", ["marketplace", "asin", "snap_date"])


def downgrade() -> None:
    conn = op.get_bind()
    for name in TABLES:
        if _table_exists(conn, name):
            op.drop_table(name)
