"""苏青禾:登录浏览器(10-28)—— sqh_browser(单行状态 + 画面)、sqh_browser_inputs(老板的点击/输入),
sqh_dossiers.status 多一个 needs_human(等老板过验证)。

无 org_id 列(办公室全站可看;写只有 owner,闸在接口)。to_regclass 幂等。

Revision ID: 20261028_01_suqinghe_browser
Revises: 20261023_01_suqinghe_dossiers
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261028_01_suqinghe_browser"
down_revision = "20261023_01_suqinghe_dossiers"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
_OLD_STATUSES = "'queued','fetching','reading','ready','blocked','failed','created','rejected'"
_NEW_STATUSES = _OLD_STATUSES + ",'needs_human'"


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def _is_postgres(conn) -> bool:
    return conn.dialect.name == "postgresql"


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "sqh_browser"):
        op.create_table(
            "sqh_browser",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="idle"),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("url", sa.String(1000), nullable=True),
            sa.Column("title", sa.String(300), nullable=True),
            sa.Column("dossier_id", sa.BigInteger(), nullable=True),
            sa.Column("frame", sa.LargeBinary(), nullable=True),
            sa.Column("frame_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("viewer_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("logged_in_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
        op.execute("INSERT INTO sqh_browser (id, status) VALUES (1, 'idle')")
        if _is_postgres(conn):
            # 单行反复 UPDATE(帧)靠 TOAST 翻新,autovacuum 要勤一点
            op.execute("ALTER TABLE sqh_browser SET (autovacuum_vacuum_scale_factor = 0, autovacuum_vacuum_threshold = 50)")
    if not _table_exists(conn, "sqh_browser_inputs"):
        op.create_table(
            "sqh_browser_inputs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("payload", _JSON, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_by_user_id", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_sqh_browser_inputs_pending", "sqh_browser_inputs", ["applied_at", "id"])
    if _is_postgres(conn) and _table_exists(conn, "sqh_dossiers"):
        _replace_status_check(_NEW_STATUSES)


def _replace_status_check(statuses: str) -> None:
    """原名重建(不用 op.create_check_constraint:命名规则会把名字叠成 ck_sqh_dossiers_ck_…,第二次跑就撞「已存在」)。"""
    op.execute("ALTER TABLE sqh_dossiers DROP CONSTRAINT IF EXISTS ck_sqh_dossiers_status")
    op.execute("ALTER TABLE sqh_dossiers DROP CONSTRAINT IF EXISTS ck_sqh_dossiers_ck_sqh_dossiers_status")
    op.execute(f"ALTER TABLE sqh_dossiers ADD CONSTRAINT ck_sqh_dossiers_status CHECK (status IN ({statuses}))")


def downgrade() -> None:
    conn = op.get_bind()
    if _is_postgres(conn) and _table_exists(conn, "sqh_dossiers"):
        op.execute("UPDATE sqh_dossiers SET status = 'blocked' WHERE status = 'needs_human'")
        _replace_status_check(_OLD_STATUSES)
    if _table_exists(conn, "sqh_browser_inputs"):
        op.drop_table("sqh_browser_inputs")
    if _table_exists(conn, "sqh_browser"):
        op.drop_table("sqh_browser")
