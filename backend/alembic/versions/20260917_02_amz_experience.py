"""A4 经验库:amz_outcomes(每条建议 14/28 天后对不对,含回测)+ amz_experience(经验条目与参数漂移)。

无 org_id 列(家规 14)。to_regclass 幂等。

Revision ID: 20260917_02_amz_experience
Revises: 20260917_01_amz_images
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260917_02_amz_experience"
down_revision = "20260917_01_amz_images"
branch_labels = None
depends_on = None

TABLES = ("amz_experience", "amz_outcomes")


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _json_default(conn, literal: str):
    return sa.text(f"'{literal}'::jsonb") if conn.dialect.name == "postgresql" else literal


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "amz_outcomes"):
        op.create_table(
            "amz_outcomes",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("store_code", sa.String(length=16), sa.ForeignKey("amz_stores.store_code", name="fk_amz_outcomes_store", ondelete="CASCADE"), nullable=False),
            sa.Column("action_type", sa.String(length=48), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("as_of", sa.Date(), nullable=False),
            sa.Column("horizon_days", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(length=16), nullable=False, server_default="live"),
            sa.Column("verdict", sa.String(length=8), nullable=False),
            sa.Column("metrics", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("suggestion_id", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("store_code", "action_type", "subject", "as_of", "horizon_days", "source", name="uq_amz_outcomes_key"),
        )
        op.create_index("ix_amz_outcomes_store_action", "amz_outcomes", ["store_code", "action_type"])

    if not _table_exists(conn, "amz_experience"):
        op.create_table(
            "amz_experience",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("entry_key", sa.String(length=200), nullable=False),
            sa.Column("scope", sa.String(length=8), nullable=False, server_default="store"),
            sa.Column("store_code", sa.String(length=16), sa.ForeignKey("amz_stores.store_code", name="fk_amz_experience_store", ondelete="CASCADE"), nullable=True),
            sa.Column("action_type", sa.String(length=48), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("employee", sa.String(length=4), nullable=True),
            sa.Column("statement", sa.Text(), nullable=False),
            sa.Column("evidence", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("samples", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("value", sa.Numeric(10, 2), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("entry_key", name="uq_amz_experience_key"),
        )
        op.create_index("ix_amz_experience_store_action", "amz_experience", ["store_code", "action_type"])


def downgrade() -> None:
    conn = op.get_bind()
    for name in TABLES:
        if _table_exists(conn, name):
            op.drop_table(name)
