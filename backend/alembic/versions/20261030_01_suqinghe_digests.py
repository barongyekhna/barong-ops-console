"""苏青禾:运营看板(10-30)—— sqh_digests(日报/周报各一行:各路数 + 面板 sections + 规则层异常)。

无 org_id 列(办公室全站可看)。to_regclass 幂等。

Revision ID: 20261030_01_suqinghe_digests
Revises: 20261028_01_suqinghe_browser
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261030_01_suqinghe_digests"
down_revision = "20261028_01_suqinghe_browser"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "sqh_digests"):
        return
    op.create_table(
        "sqh_digests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("period_key", sa.String(16), nullable=False),
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column("payload", _JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("findings", _JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("kind", "period_key", name="uq_sqh_digests_kind_period"),
    )


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "sqh_digests"):
        op.drop_table("sqh_digests")
