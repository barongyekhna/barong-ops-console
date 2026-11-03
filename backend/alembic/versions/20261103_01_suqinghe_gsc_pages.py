"""苏青禾:Search Console 改按「页」存(11-03,看板第二期修正)。

站小,谷歌把每天的搜索词全部匿名(拉 90 天也是 0 个词),「天×词×页」的 sqh_gsc_daily 永远是空表;按页、按天、全站合计都有数。
- 新表 sqh_gsc_pages(天×页)、sqh_gsc_queries(截止某天的 N 天窗口×词);
- sqh_gsc_days 加当天全站合计 clicks/impressions/ctr/position、口径版本 fmt(旧行 = 1,新口径拉过 = 2,旧的自动重拉)、window_rows;
- 删掉 sqh_gsc_daily(上线前核对过 0 行;发版脚本迁移前再查一次,不是 0 行就停)。

无 org_id 列(只有贸易公司一个站)。to_regclass / 列存在判断幂等。

Revision ID: 20261103_01_suqinghe_gsc_pages
Revises: 20261102_03_jiagui_registry
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261103_01_suqinghe_gsc_pages"
down_revision = "20261102_03_jiagui_registry"
branch_labels = None
depends_on = None

_DAY_COLUMNS = (
    ("fmt", sa.Integer(), "1", False),
    ("clicks", sa.Integer(), "0", False),
    ("impressions", sa.Integer(), "0", False),
    ("ctr", sa.Numeric(8, 5), "0", False),
    ("position", sa.Numeric(8, 2), "0", False),
    ("window_rows", sa.Integer(), None, True),
)


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(
        conn.exec_driver_sql(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %(t)s AND column_name = %(c)s",
            {"t": table, "c": column},
        ).scalar()
    )


def _metrics() -> list[sa.Column]:
    return [
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ctr", sa.Numeric(8, 5), nullable=False, server_default="0"),
        sa.Column("position", sa.Numeric(8, 2), nullable=False, server_default="0"),
    ]


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "sqh_gsc_pages"):
        op.create_table(
            "sqh_gsc_pages",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("page", sa.String(1000), nullable=False),
            *_metrics(),
            sa.UniqueConstraint("day", "page", name="uq_sqh_gsc_pages_day_page"),
        )
        op.create_index("ix_sqh_gsc_pages_day", "sqh_gsc_pages", ["day"])
    if not _table_exists(conn, "sqh_gsc_queries"):
        op.create_table(
            "sqh_gsc_queries",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("window_end", sa.Date(), nullable=False),
            sa.Column("window_days", sa.Integer(), nullable=False),
            sa.Column("query", sa.String(300), nullable=False),
            *_metrics(),
            sa.UniqueConstraint("window_end", "window_days", "query", name="uq_sqh_gsc_queries_window_query"),
        )
        op.create_index("ix_sqh_gsc_queries_window_end", "sqh_gsc_queries", ["window_end"])
    if _table_exists(conn, "sqh_gsc_days"):
        for name, type_, default, nullable in _DAY_COLUMNS:
            if not _column_exists(conn, "sqh_gsc_days", name):
                op.add_column("sqh_gsc_days", sa.Column(name, type_, nullable=nullable, server_default=default))
    if _table_exists(conn, "sqh_gsc_daily"):
        op.drop_table("sqh_gsc_daily")


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "sqh_gsc_daily"):
        op.create_table(
            "sqh_gsc_daily",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("query", sa.String(300), nullable=False),
            sa.Column("page", sa.String(1000), nullable=False),
            *_metrics(),
            sa.UniqueConstraint("day", "query", "page", name="uq_sqh_gsc_daily_day_query_page"),
        )
        op.create_index("ix_sqh_gsc_daily_day", "sqh_gsc_daily", ["day"])
    if _table_exists(conn, "sqh_gsc_days"):
        for name, _type, _default, _nullable in reversed(_DAY_COLUMNS):
            if _column_exists(conn, "sqh_gsc_days", name):
                op.drop_column("sqh_gsc_days", name)
    for name in ("sqh_gsc_queries", "sqh_gsc_pages"):
        if _table_exists(conn, name):
            op.drop_table(name)
