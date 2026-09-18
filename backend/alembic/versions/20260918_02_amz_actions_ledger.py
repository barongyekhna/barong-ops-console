"""A3 执行台账 amz_actions_ledger(梯子 / 护栏 / 总闸 / 回读 / 回看的底账)。

无 org_id 列(家规 14)。to_regclass 幂等。amz_ladder / amz_guardrails 在 20260916_01 已建。

Revision ID: 20260918_02_amz_actions_ledger
Revises: 20260918_01_amz_inventory_listings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260918_02_amz_actions_ledger"
down_revision = "20260918_01_amz_inventory_listings"
branch_labels = None
depends_on = None


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _json_default(conn, literal: str):
    return sa.text(f"'{literal}'::jsonb") if conn.dialect.name == "postgresql" else literal


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "amz_actions_ledger"):
        return
    op.create_table(
        "amz_actions_ledger",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("suggestion_id", sa.Uuid(), nullable=False),
        sa.Column("store_code", sa.String(length=16), sa.ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.String(length=48), nullable=False),
        sa.Column("level", sa.String(length=4), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("op", _json(), nullable=False, server_default=_json_default(conn, "{}")),
        sa.Column("before", _json(), nullable=False, server_default=_json_default(conn, "{}")),
        sa.Column("after", _json(), nullable=False, server_default=_json_default(conn, "{}")),
        sa.Column("why", sa.Text(), nullable=False, server_default=""),
        sa.Column("prediction", sa.Text(), nullable=False, server_default=""),
        sa.Column("approved_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("guard", _json(), nullable=False, server_default=_json_default(conn, "{}")),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("countdown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("readback_ok", sa.Boolean(), nullable=True),
        sa.Column("lookback", _json(), nullable=False, server_default=_json_default(conn, "{}")),
        sa.Column("outcome", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("suggestion_id", name="uq_amz_actions_ledger_suggestion"),
    )
    op.create_index("ix_amz_actions_ledger_store_status", "amz_actions_ledger", ["store_code", "status"])


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "amz_actions_ledger"):
        op.drop_table("amz_actions_ledger")
