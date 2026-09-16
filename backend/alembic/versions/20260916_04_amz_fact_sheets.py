"""A 系列产品事实表 amz_fact_sheets:按产品线(可细到店 / SKU)手填的事实 + AI 判「够不够」的结果。

事实在 A 里手填,与 K 零交集(家规)。无 org_id 列(家规 14)。to_regclass 幂等。

Revision ID: 20260916_04_amz_fact_sheets
Revises: 20260916_03_amz_reports
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_04_amz_fact_sheets"
down_revision = "20260916_03_amz_reports"
branch_labels = None
depends_on = None

TABLE = "amz_fact_sheets"


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _json_default(conn, literal: str):
    return sa.text(f"'{literal}'::jsonb") if conn.dialect.name == "postgresql" else literal


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope_key", sa.String(length=200), nullable=False),
        sa.Column("product_line", sa.String(length=32), nullable=False),
        sa.Column("store_code", sa.String(length=16), sa.ForeignKey("amz_stores.store_code", name="fk_amz_fact_sheets_store", ondelete="SET NULL"), nullable=True),
        sa.Column("sku", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("facts", _json(), nullable=False, server_default=_json_default(conn, "{}")),
        sa.Column("sufficiency", _json(), nullable=False, server_default=_json_default(conn, "{}")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("scope_key", name="uq_amz_fact_sheets_scope"),
    )
    op.create_index("ix_amz_fact_sheets_line", TABLE, ["product_line"])


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, TABLE):
        op.drop_table(TABLE)
