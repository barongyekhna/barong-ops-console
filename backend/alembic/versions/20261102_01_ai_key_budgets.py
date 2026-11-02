"""Claude 两把钥匙按动态配额分(11-02,老板拍板):台账记用的哪把钥匙;每把钥匙登记月额度、重置日。

- ai_usage_ledger 加 key_id(可空:历史行和直连调用没有,算到默认钥匙头上)。
- ai_key_budgets:key_id、月额度、每月几号重置、月底保留比例、是不是默认钥匙(没记 key_id 的花费归它)。
  种子:老钥匙(桌面账号 Max 赠送 $200,18 日重置,默认)、新钥匙(控制台账号 Max 赠送 $100,11 日重置)。
  以后改额度直接改这张表,不用改代码。
无 org_id 列(额度跨组织共用,和台账一样)。to_regclass / 列存在性检查,幂等。

Revision ID: 20261102_01_ai_key_budgets
Revises: 20261030_02_suqinghe_gsc
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261102_01_ai_key_budgets"
down_revision = "20261030_02_suqinghe_gsc"
branch_labels = None
depends_on = None

SEED = (
    # key_id, monthly_usd, reset_day, reserve_pct, is_default, note
    ("key_ed01de5e3029344ec5ba19f7b8e46a35", 200, 18, 10, True, "桌面 Claude 账号 Max 赠送 $200/月,每月 18 日重置(17 日到期)"),
    ("key_aa93f82e7b719d0c1324386658f1dbed", 100, 11, 10, False, "控制台 Claude 账号 Max 赠送 $100/月,每月 11 日重置(10 日到期)"),
)


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(
        conn.exec_driver_sql(
            "SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=%(t)s AND column_name=%(c)s",
            {"t": table, "c": column},
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "ai_usage_ledger") and not _column_exists(conn, "ai_usage_ledger", "key_id"):
        op.add_column("ai_usage_ledger", sa.Column("key_id", sa.String(length=40), nullable=True))
        op.create_index("ix_ai_usage_ledger_key_day", "ai_usage_ledger", ["key_id", "usage_day"])
    if not _table_exists(conn, "ai_key_budgets"):
        op.create_table(
            "ai_key_budgets",
            sa.Column("key_id", sa.String(length=40), primary_key=True),
            sa.Column("provider", sa.String(length=32), nullable=False, server_default="claude"),
            sa.Column("monthly_usd", sa.Numeric(10, 2), nullable=False),
            sa.Column("reset_day", sa.SmallInteger(), nullable=False),
            sa.Column("reserve_pct", sa.SmallInteger(), nullable=False, server_default="10"),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("note", sa.String(length=200), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("reset_day BETWEEN 1 AND 28", name="ck_ai_key_budgets_reset_day"),
            sa.CheckConstraint("reserve_pct BETWEEN 0 AND 50", name="ck_ai_key_budgets_reserve_pct"),
        )
    for key_id, monthly, reset_day, reserve, is_default, note in SEED:
        conn.exec_driver_sql(
            "INSERT INTO ai_key_budgets (key_id, provider, monthly_usd, reset_day, reserve_pct, is_default, note) "
            "VALUES (%(k)s, 'claude', %(m)s, %(r)s, %(p)s, %(d)s, %(n)s) ON CONFLICT (key_id) DO NOTHING",
            {"k": key_id, "m": monthly, "r": reset_day, "p": reserve, "d": is_default, "n": note},
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "ai_key_budgets"):
        op.drop_table("ai_key_budgets")
    if _column_exists(conn, "ai_usage_ledger", "key_id"):
        op.drop_index("ix_ai_usage_ledger_key_day", table_name="ai_usage_ledger")
        op.drop_column("ai_usage_ledger", "key_id")
