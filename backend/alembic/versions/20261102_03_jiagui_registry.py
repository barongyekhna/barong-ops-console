"""作图家规风格包注册表(M2a,11-02):jiagui_core_versions / jiagui_packs / jiagui_pack_checks 三张表,
加苏青禾的选包记录 sqh_route_records。

无 org_id 列(风格包是全站共用的家规)。jiagui_packs 上有部分唯一索引:同一个包 id 只能有一行 status='active'。
to_regclass 幂等。

Revision ID: 20261102_03_jiagui_registry
Revises: 20261102_02_suqinghe_gate_statuses
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261102_03_jiagui_registry"
down_revision = "20261102_02_suqinghe_gate_statuses"
branch_labels = None
depends_on = None


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def _json():
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "jiagui_core_versions"):
        op.create_table(
            "jiagui_core_versions",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("version", sa.String(32), nullable=False, unique=True),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("selftest", _json(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("decided_by_user_id", sa.String(64), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("status IN ('pending','active','retired','rejected')", name="ck_jiagui_core_versions_status"),
        )
    if not _table_exists(conn, "jiagui_packs"):
        op.create_table(
            "jiagui_packs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("pack_id", sa.String(64), nullable=False),
            sa.Column("version", sa.String(32), nullable=False),
            sa.Column("name", sa.String(120), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("stage", sa.String(16), nullable=False, server_default=""),
            sa.Column("provides", _json(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("core_req", sa.String(64), nullable=False, server_default=""),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("source", sa.String(200), nullable=False, server_default=""),
            sa.Column("pack_json", _json(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("manifest", _json(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("previous_version", sa.String(32), nullable=True),
            sa.Column("progress_only", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("card_ref", sa.String(8), nullable=True),
            sa.Column("registered_by", sa.String(64), nullable=False, server_default=""),
            sa.Column("decided_by", sa.String(64), nullable=True),
            sa.Column("decision_reason", sa.Text(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("pack_id", "version", name="uq_jiagui_packs_pack_version"),
            sa.CheckConstraint("status IN ('pending','active','retired','rejected')", name="ck_jiagui_packs_status"),
        )
        op.create_index("ix_jiagui_packs_pack_id", "jiagui_packs", ["pack_id"])
        op.create_index("uq_jiagui_packs_one_active", "jiagui_packs", ["pack_id"], unique=True, postgresql_where=sa.text("status = 'active'"))
    if not _table_exists(conn, "jiagui_pack_checks"):
        op.create_table(
            "jiagui_pack_checks",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("pack_row_id", sa.BigInteger(), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("result", _json(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
        op.create_index("ix_jiagui_pack_checks_pack_row_id", "jiagui_pack_checks", ["pack_row_id"])
    if not _table_exists(conn, "sqh_route_records"):
        op.create_table(
            "sqh_route_records",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("dossier_id", sa.BigInteger(), nullable=False),
            sa.Column("sku", sa.String(32), nullable=False, server_default=""),
            sa.Column("purpose", sa.String(16), nullable=False, server_default="pipeline"),
            sa.Column("replay_for", sa.BigInteger(), nullable=True),
            sa.Column("registry_fp", sa.String(32), nullable=False, server_default=""),
            sa.Column("price", _json(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("facts", sa.Text(), nullable=False, server_default=""),
            sa.Column("decision_kind", sa.String(16), nullable=False),
            sa.Column("pack_id", sa.String(64), nullable=True),
            sa.Column("pack_version", sa.String(32), nullable=True),
            sa.Column("variant", sa.String(64), nullable=True),
            sa.Column("missing_key", sa.String(160), nullable=True),
            sa.Column("record", _json(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("calls", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("card_ref", sa.String(8), nullable=True),
            sa.Column("owner_pick", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
        op.create_index("ix_sqh_route_records_dossier_id", "sqh_route_records", ["dossier_id"])


def downgrade() -> None:
    conn = op.get_bind()
    for name in ("sqh_route_records", "jiagui_pack_checks", "jiagui_packs", "jiagui_core_versions"):
        if _table_exists(conn, name):
            op.drop_table(name)
