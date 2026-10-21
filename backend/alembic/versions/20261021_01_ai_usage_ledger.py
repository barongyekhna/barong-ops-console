"""AI 换血:ai_usage_ledger —— 每次出网的大模型调用记一行 token 与美元。

Claude 改走官方 API(Max 订阅每月送的额度,当期清零),当天花费到上限就降级给 DeepSeek;
这个上限要能查出「今天已经花了多少」。写入方见 backend/app/services/ai_usage_ledger.py。

无 org_id 列:C18G 会按会话组织自动过滤带这列的模型,而台账要跨组织汇总
(Claude 额度是整个 Console 组织共用的一个池)。归属组织记在 org_ref。to_regclass 幂等。

Revision ID: 20261021_01_ai_usage_ledger
Revises: 20260919_01_amz_finance
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261021_01_ai_usage_ledger"
down_revision = "20260919_01_amz_finance"
branch_labels = None
depends_on = None


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "ai_usage_ledger"):
        return
    op.create_table(
        "ai_usage_ledger",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("usage_day", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=96), nullable=False, server_default=""),
        sa.Column("module", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("task", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("org_ref", sa.String(length=64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ai_usage_ledger_day_provider", "ai_usage_ledger", ["usage_day", "provider"])
    op.create_index("ix_ai_usage_ledger_day_module", "ai_usage_ledger", ["usage_day", "module"])


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "ai_usage_ledger"):
        op.drop_table("ai_usage_ledger")
