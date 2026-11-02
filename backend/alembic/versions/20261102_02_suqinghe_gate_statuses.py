"""苏青禾档案加两个状态(11-02 独立站合规门):dropped(合规门不做)、gate_ask(清单外,等老板定)。

只改 sqh_dossiers 的状态检查约束,原名重建(同 20261028_01 的写法)。降级时把这两个状态退回 rejected / ready。

Revision ID: 20261102_02_suqinghe_gate_statuses
Revises: 20261102_01_ai_key_budgets
"""

from __future__ import annotations

from alembic import op

revision = "20261102_02_suqinghe_gate_statuses"
down_revision = "20261102_01_ai_key_budgets"
branch_labels = None
depends_on = None

_OLD_STATUSES = "'queued','fetching','reading','ready','blocked','failed','created','rejected','needs_human'"
_NEW_STATUSES = _OLD_STATUSES + ",'dropped','gate_ask'"


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def _is_postgres(conn) -> bool:
    return conn.dialect.name == "postgresql"


def _replace_status_check(statuses: str) -> None:
    op.execute("ALTER TABLE sqh_dossiers DROP CONSTRAINT IF EXISTS ck_sqh_dossiers_status")
    op.execute("ALTER TABLE sqh_dossiers DROP CONSTRAINT IF EXISTS ck_sqh_dossiers_ck_sqh_dossiers_status")
    op.execute(f"ALTER TABLE sqh_dossiers ADD CONSTRAINT ck_sqh_dossiers_status CHECK (status IN ({statuses}))")


def upgrade() -> None:
    conn = op.get_bind()
    if _is_postgres(conn) and _table_exists(conn, "sqh_dossiers"):
        _replace_status_check(_NEW_STATUSES)


def downgrade() -> None:
    conn = op.get_bind()
    if _is_postgres(conn) and _table_exists(conn, "sqh_dossiers"):
        op.execute("UPDATE sqh_dossiers SET status = 'rejected' WHERE status = 'dropped'")
        op.execute("UPDATE sqh_dossiers SET status = 'ready' WHERE status = 'gate_ask'")
        _replace_status_check(_OLD_STATUSES)
