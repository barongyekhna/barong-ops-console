"""苏青禾:sqh_dossiers —— 一个 1688 链接 → 一份 K 档案草稿,批卡才建进 K。

无 org_id 列(家规 14 同理,办公室全站可看)。to_regclass 幂等。

Revision ID: 20261023_01_suqinghe_dossiers
Revises: 20261022_01_suqinghe
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261023_01_suqinghe_dossiers"
down_revision = "20261022_01_suqinghe"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "sqh_dossiers"):
        return
    op.create_table(
        "sqh_dossiers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("offer_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("requested_by_user_id", sa.String(64), nullable=True),
        sa.Column("channel", sa.String(8), nullable=False, server_default="web"),
        sa.Column("capture", _JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("draft", _JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("flagged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("card_ref", sa.String(8), nullable=True),
        sa.Column("k_product_id", sa.String(64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('queued','fetching','reading','ready','blocked','failed','created','rejected')",
            name="ck_sqh_dossiers_status",
        ),
        sa.CheckConstraint("channel IN ('web','c19')", name="ck_sqh_dossiers_channel"),
    )
    op.create_index("ix_sqh_dossiers_offer_id", "sqh_dossiers", ["offer_id"])
    op.create_index("ix_sqh_dossiers_status_created", "sqh_dossiers", ["status", "created_at"])


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "sqh_dossiers"):
        op.drop_table("sqh_dossiers")
