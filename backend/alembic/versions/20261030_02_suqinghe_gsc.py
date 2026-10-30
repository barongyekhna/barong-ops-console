"""苏青禾:Search Console 搜索表现(10-30,看板第二期)—— sqh_gsc_daily(天×词×页)、sqh_gsc_days(拉过哪几天)。

无 org_id 列(只有贸易公司一个站)。to_regclass 幂等。

Revision ID: 20261030_02_suqinghe_gsc
Revises: 20261030_01_suqinghe_digests
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261030_02_suqinghe_gsc"
down_revision = "20261030_01_suqinghe_digests"
branch_labels = None
depends_on = None


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "sqh_gsc_daily"):
        op.create_table(
            "sqh_gsc_daily",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("query", sa.String(300), nullable=False),
            sa.Column("page", sa.String(1000), nullable=False),
            sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ctr", sa.Numeric(8, 5), nullable=False, server_default="0"),
            sa.Column("position", sa.Numeric(8, 2), nullable=False, server_default="0"),
            sa.UniqueConstraint("day", "query", "page", name="uq_sqh_gsc_daily_day_query_page"),
        )
        op.create_index("ix_sqh_gsc_daily_day", "sqh_gsc_daily", ["day"])
    if not _table_exists(conn, "sqh_gsc_days"):
        op.create_table(
            "sqh_gsc_days",
            sa.Column("day", sa.Date(), primary_key=True),
            sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("pulled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )


def downgrade() -> None:
    conn = op.get_bind()
    for name in ("sqh_gsc_days", "sqh_gsc_daily"):
        if _table_exists(conn, name):
            op.drop_table(name)
