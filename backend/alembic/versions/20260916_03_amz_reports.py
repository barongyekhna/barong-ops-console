"""A1 第一批报表表:amz_sales_daily(销售与流量,按天按 ASIN)、amz_sqp(搜索词表现,按周)、amz_report_runs(要报表台账)。

无 org_id 列(家规 14)。to_regclass 幂等。

Revision ID: 20260916_03_amz_reports
Revises: 20260916_02_amz_work_log
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_03_amz_reports"
down_revision = "20260916_02_amz_work_log"
branch_labels = None
depends_on = None

TABLES = ("amz_report_runs", "amz_sqp", "amz_sales_daily")


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _json_default(conn, literal: str):
    return sa.text(f"'{literal}'::jsonb") if conn.dialect.name == "postgresql" else literal


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _store(name: str) -> sa.Column:
    return sa.Column("store_code", sa.String(length=16), sa.ForeignKey("amz_stores.store_code", name=name, ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "amz_sales_daily"):
        op.create_table(
            "amz_sales_daily",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            _store("fk_amz_sales_daily_store"),
            sa.Column("report_date", sa.Date(), nullable=False),
            sa.Column("parent_asin", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("child_asin", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("units_ordered", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ordered_product_sales", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("total_order_items", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("units_refunded", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sessions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("page_views", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("buy_box_pct", sa.Numeric(6, 2), nullable=True),
            sa.Column("unit_session_pct", sa.Numeric(6, 2), nullable=True),
            sa.Column("raw", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            *_stamps(),
            sa.UniqueConstraint("store_code", "report_date", "child_asin", name="uq_amz_sales_daily_store_date_asin"),
        )
        op.create_index("ix_amz_sales_daily_store_date", "amz_sales_daily", ["store_code", "report_date"])
        op.create_index("ix_amz_sales_daily_asin", "amz_sales_daily", ["child_asin"])

    if not _table_exists(conn, "amz_sqp"):
        op.create_table(
            "amz_sqp",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            _store("fk_amz_sqp_store"),
            sa.Column("period_type", sa.String(length=8), nullable=False, server_default="WEEK"),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("asin", sa.String(length=16), nullable=False),
            sa.Column("search_query", sa.Text(), nullable=False),
            sa.Column("query_score", sa.Integer(), nullable=True),
            sa.Column("query_volume", sa.Integer(), nullable=True),
            sa.Column("impressions_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("impressions_asin", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("impressions_share_pct", sa.Numeric(6, 2), nullable=True),
            sa.Column("clicks_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("clicks_asin", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("clicks_share_pct", sa.Numeric(6, 2), nullable=True),
            sa.Column("cart_adds_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cart_adds_asin", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cart_adds_share_pct", sa.Numeric(6, 2), nullable=True),
            sa.Column("purchases_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("purchases_asin", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("purchases_share_pct", sa.Numeric(6, 2), nullable=True),
            sa.Column("raw", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            *_stamps(),
            sa.UniqueConstraint("store_code", "period_start", "asin", "search_query", name="uq_amz_sqp_store_period_asin_query"),
        )
        op.create_index("ix_amz_sqp_store_period", "amz_sqp", ["store_code", "period_start"])

    if not _table_exists(conn, "amz_report_runs"):
        op.create_table(
            "amz_report_runs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            _store("fk_amz_report_runs_store"),
            sa.Column("report_type", sa.String(length=80), nullable=False),
            sa.Column("report_id", sa.String(length=64), nullable=True),
            sa.Column("params", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="requested"),
            sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_amz_report_runs_store_type_time", "amz_report_runs", ["store_code", "report_type", "requested_at"])


def downgrade() -> None:
    conn = op.get_bind()
    for name in TABLES:
        if _table_exists(conn, name):
            op.drop_table(name)
