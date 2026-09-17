"""A4 竞品名单自动派生:amz_ba_top_clicks(品牌分析搜索词报表里「我们核心词」的点击前三)。

只存核心词那几行,不存全站几百万行。无 org_id 列(家规 14)。to_regclass 幂等。

Revision ID: 20260917_05_amz_ba_top_clicks
Revises: 20260917_04_amz_competitors
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260917_05_amz_ba_top_clicks"
down_revision = "20260917_04_amz_competitors"
branch_labels = None
depends_on = None


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "amz_ba_top_clicks"):
        return
    op.create_table(
        "amz_ba_top_clicks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("marketplace", sa.String(length=4), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("search_term", sa.Text(), nullable=False),
        sa.Column("product_line", sa.String(length=32), nullable=False),
        sa.Column("search_frequency_rank", sa.Integer(), nullable=True),
        sa.Column("click_rank", sa.SmallInteger(), nullable=False),
        sa.Column("asin", sa.String(length=16), nullable=False),
        sa.Column("item_name", sa.String(length=512), nullable=True),
        sa.Column("click_share", sa.Numeric(7, 4), nullable=True),
        sa.Column("conversion_share", sa.Numeric(7, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("marketplace", "week_start", "search_term", "click_rank", name="uq_amz_ba_top_clicks_week_term_rank"),
    )
    op.create_index("ix_amz_ba_top_clicks_asin", "amz_ba_top_clicks", ["marketplace", "asin", "week_start"])


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "amz_ba_top_clicks"):
        op.drop_table("amz_ba_top_clicks")
