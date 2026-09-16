"""A 系列员工工作日志 amz_work_log:四名数字员工的硬记忆(谁、哪个店、哪个对象、做了什么、为什么)。

不是模型自己写的软笔记,是每条建议 / 决定 / 执行 / 老板口述的事实落库,聊天时按问题检索出来喂给她们——
「不允许失忆」靠库,不靠模型。无 org_id 列(家规 14)。to_regclass 幂等。

Revision ID: 20260916_02_amz_work_log
Revises: 20260916_01_amz_suggestions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_02_amz_work_log"
down_revision = "20260916_01_amz_suggestions"
branch_labels = None
depends_on = None

TABLE = "amz_work_log"


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
        sa.Column("employee", sa.String(length=4), nullable=False),
        sa.Column(
            "store_code",
            sa.String(length=16),
            sa.ForeignKey("amz_stores.store_code", name="fk_amz_work_log_store", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("asin", sa.String(length=16), nullable=True),
        sa.Column("sku", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("why", sa.Text(), nullable=False, server_default=""),
        sa.Column("detail", _json(), nullable=False, server_default=_json_default(conn, "{}")),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="rule"),
        sa.Column("suggestion_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_amz_work_log_employee_time", TABLE, ["employee", "occurred_at"])
    op.create_index("ix_amz_work_log_store_subject", TABLE, ["store_code", "subject"])
    op.create_index("ix_amz_work_log_suggestion", TABLE, ["suggestion_id"])


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, TABLE):
        op.drop_table(TABLE)
