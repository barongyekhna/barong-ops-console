"""苏青禾(独立站运营总管)骨架:审批卡、硬记忆、目标、流水、状态单行、每日快照。

无 org_id 列(家规 14 同理):办公室全站可看,C18G 会按会话组织过滤带 org_id 的模型。
to_regclass 幂等。

Revision ID: 20261022_01_suqinghe
Revises: 20261021_01_ai_usage_ledger
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261022_01_suqinghe"
down_revision = "20261021_01_ai_usage_ledger"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
_TABLES = ("sqh_cards", "sqh_memory", "sqh_goals", "sqh_activity", "sqh_state", "sqh_snapshots")


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def _ts(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "sqh_cards"):
        op.create_table(
            "sqh_cards",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("ref", sa.String(8), nullable=False, unique=True),
            sa.Column("dedupe_key", sa.String(160), nullable=False, unique=True),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("conclusion", sa.Text(), nullable=False),
            sa.Column("why", sa.Text(), nullable=False, server_default=""),
            sa.Column("if_not", sa.Text(), nullable=False, server_default=""),
            sa.Column("reversible", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("confidence", sa.String(16), nullable=False, server_default="medium"),
            sa.Column("evidence", _JSON, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("data_fingerprint", sa.String(64), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("decided_by_user_id", sa.String(64), nullable=True),
            sa.Column("decided_via", sa.String(8), nullable=True),
            sa.Column("decision_reason", sa.Text(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            _ts(),
            sa.CheckConstraint("status IN ('pending','approved','rejected','stale','expired')", name="ck_sqh_cards_status"),
            sa.CheckConstraint("decided_via IS NULL OR decided_via IN ('web','c19','mcp')", name="ck_sqh_cards_via"),
        )
        op.create_index("ix_sqh_cards_status_created", "sqh_cards", ["status", "created_at"])
    if not _table_exists(conn, "sqh_memory"):
        op.create_table(
            "sqh_memory",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("subject", sa.String(200), nullable=False, server_default=""),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("refs", _JSON, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("source", sa.String(16), nullable=False, server_default="agent"),
            sa.Column("actor_user_id", sa.String(64), nullable=True),
            _ts(),
            sa.CheckConstraint("kind IN ('plan','suggestion','decision','note','dictation','observation')", name="ck_sqh_memory_kind"),
        )
        op.create_index("ix_sqh_memory_kind_created", "sqh_memory", ["kind", "created_at"])
    if not _table_exists(conn, "sqh_goals"):
        op.create_table(
            "sqh_goals",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("metric", _JSON, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("created_by_user_id", sa.String(64), nullable=True),
            _ts(),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('active','paused','done','dropped')", name="ck_sqh_goals_status"),
        )
    if not _table_exists(conn, "sqh_activity"):
        op.create_table(
            "sqh_activity",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("kind", sa.String(16), nullable=False, server_default="work"),
            sa.Column("text", sa.String(500), nullable=False),
            _ts(),
        )
        op.create_index("ix_sqh_activity_created", "sqh_activity", ["created_at"])
    if not _table_exists(conn, "sqh_state"):
        op.create_table(
            "sqh_state",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("paused_by_user_id", sa.String(64), nullable=True),
            sa.Column("activity", sa.String(16), nullable=False, server_default="working"),
            sa.Column("task", sa.String(300), nullable=False, server_default=""),
            sa.Column("progress", sa.Integer(), nullable=True),
            sa.Column("muted_until", sa.Date(), nullable=True),
            sa.Column("last_spoke_date", sa.Date(), nullable=True),
            sa.Column("last_plan_date", sa.Date(), nullable=True),
            _ts("updated_at"),
        )
        conn.exec_driver_sql("INSERT INTO sqh_state (id) VALUES (1) ON CONFLICT DO NOTHING")
    if not _table_exists(conn, "sqh_snapshots"):
        op.create_table(
            "sqh_snapshots",
            sa.Column("snapshot_date", sa.Date(), primary_key=True),
            sa.Column("payload", _JSON, nullable=False),
            _ts(),
        )


def downgrade() -> None:
    conn = op.get_bind()
    for name in reversed(_TABLES):
        if _table_exists(conn, name):
            op.drop_table(name)
