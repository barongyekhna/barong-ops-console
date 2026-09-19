"""殷乐乐(财务):amz_costs 成本表(人手填,带生效日期);「亏卖线」从殷素素交给乐乐——D 名下没处理的 loss_line 建议作废。

无 org_id 列(家规 14)。to_regclass 幂等。

Revision ID: 20260919_01_amz_finance
Revises: 20260918_03_rd_client_traces
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260919_01_amz_finance"
down_revision = "20260918_03_rd_client_traces"
branch_labels = None
depends_on = None


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "amz_costs"):
        op.create_table(
            "amz_costs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("store_code", sa.String(length=16), sa.ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False),
            sa.Column("sku", sa.String(length=128), nullable=False),
            sa.Column("factory_cny", sa.Numeric(10, 2), nullable=False),
            sa.Column("freight_cny", sa.Numeric(10, 2), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("note", sa.String(length=255), nullable=True),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("store_code", "sku", "effective_from", name="uq_amz_costs_store_sku_from"),
        )
        op.create_index("ix_amz_costs_store_sku", "amz_costs", ["store_code", "sku"])
    if _table_exists(conn, "amz_suggestions"):
        conn.exec_driver_sql("UPDATE amz_suggestions SET status = 'expired', updated_at = now() WHERE action_type = 'loss_line' AND status = 'open'")


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "amz_costs"):
        op.drop_table("amz_costs")
