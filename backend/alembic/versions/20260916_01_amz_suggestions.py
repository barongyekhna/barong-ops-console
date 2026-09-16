"""A 系列 A2 表:产品档案、员工建议(消息)、梯子、护栏。无 org_id 列(家规 14)。to_regclass 幂等。

Revision ID: 20260916_01_amz_suggestions
Revises: 20260915_02_amz_permissions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_01_amz_suggestions"
down_revision = "20260915_02_amz_permissions"
branch_labels = None
depends_on = None

TABLES = ("amz_guardrails", "amz_ladder", "amz_suggestions", "amz_products")


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


def _store_fk(name: str) -> sa.Column:
    return sa.Column(
        "store_code",
        sa.String(length=16),
        sa.ForeignKey("amz_stores.store_code", name=name, ondelete="CASCADE"),
        primary_key=True,
    )


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "amz_products"):
        op.create_table(
            "amz_products",
            _store_fk("fk_amz_products_store"),
            sa.Column("sku", sa.String(length=128), primary_key=True),
            sa.Column("asin", sa.String(length=16), nullable=True),
            sa.Column("parent_asin", sa.String(length=16), nullable=True),
            sa.Column("product_line", sa.String(length=32), nullable=False, server_default="other"),
            sa.Column("title", sa.String(length=512), nullable=True),
            sa.Column("price", sa.Numeric(10, 2), nullable=True),
            sa.Column("cost_factory", sa.Numeric(10, 2), nullable=True),
            sa.Column("cost_freight", sa.Numeric(10, 2), nullable=True),
            sa.Column("cost_currency", sa.String(length=3), nullable=False, server_default="CNY"),
            sa.Column("lifecycle_phase", sa.String(length=16), nullable=False, server_default="unknown"),
            sa.Column("season_phase", sa.String(length=16), nullable=False, server_default="unknown"),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
            sa.Column("metadata", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            *_stamps(),
        )

    if not _table_exists(conn, "amz_suggestions"):
        op.create_table(
            "amz_suggestions",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("employee", sa.String(length=4), nullable=False),
            sa.Column(
                "store_code",
                sa.String(length=16),
                sa.ForeignKey("amz_stores.store_code", name="fk_amz_suggestions_store", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("action_type", sa.String(length=48), nullable=False),
            sa.Column("severity", sa.String(length=8), nullable=False, server_default="info"),
            sa.Column("title", sa.String(length=512), nullable=False),
            sa.Column("why", sa.Text(), nullable=False, server_default=""),
            sa.Column("prediction", sa.Text(), nullable=False, server_default=""),
            sa.Column("evidence", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("level", sa.String(length=4), nullable=False, server_default="L0"),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
            sa.Column("reject_reason", sa.Text(), nullable=True),
            sa.Column("decided_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dedupe_key", sa.String(length=64), nullable=False),
            sa.Column("as_of", sa.Date(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            *_stamps(),
            sa.UniqueConstraint("dedupe_key", name="uq_amz_suggestions_dedupe_key"),
        )
        op.create_index("ix_amz_suggestions_store_status", "amz_suggestions", ["store_code", "status"])
        op.create_index("ix_amz_suggestions_employee_status", "amz_suggestions", ["employee", "status"])

    if not _table_exists(conn, "amz_ladder"):
        op.create_table(
            "amz_ladder",
            _store_fk("fk_amz_ladder_store"),
            sa.Column("action_type", sa.String(length=48), primary_key=True),
            sa.Column("level", sa.String(length=4), nullable=False, server_default="L0"),
            sa.Column("max_level", sa.String(length=4), nullable=False, server_default="L1"),
            sa.Column("history", _json(), nullable=False, server_default=_json_default(conn, "[]")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )

    if not _table_exists(conn, "amz_guardrails"):
        op.create_table(
            "amz_guardrails",
            _store_fk("fk_amz_guardrails_store"),
            sa.Column("daily_budget_cap", sa.Numeric(12, 2), nullable=True),
            sa.Column("bid_max_change_pct", sa.Integer(), nullable=False, server_default="25"),
            sa.Column("budget_max_change_pct", sa.Integer(), nullable=False, server_default="20"),
            sa.Column("actions_per_day", sa.Integer(), nullable=False, server_default="20"),
            sa.Column("cpc_max", sa.Numeric(10, 4), nullable=True),
            sa.Column("price_floor", sa.Numeric(10, 2), nullable=True),
            sa.Column("breaker_ratio", sa.Numeric(6, 2), nullable=False, server_default="1.3"),
            sa.Column("kill_switch", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("kill_switch_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("kill_switch_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )


def downgrade() -> None:
    conn = op.get_bind()
    for name in TABLES:
        if _table_exists(conn, name):
            op.drop_table(name)
