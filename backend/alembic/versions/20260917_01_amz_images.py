"""A5 图片通道:amz_image_briefs(带证据的 brief)、amz_image_assets(参考图 / 交稿 / 上线图 + 四道门结果)。

A 自己的表和素材(与 K/I 零交集)。无 org_id 列(家规 14)。to_regclass 幂等。

Revision ID: 20260917_01_amz_images
Revises: 20260916_04_amz_fact_sheets
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260917_01_amz_images"
down_revision = "20260916_04_amz_fact_sheets"
branch_labels = None
depends_on = None

TABLES = ("amz_image_assets", "amz_image_briefs")


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


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "amz_image_briefs"):
        op.create_table(
            "amz_image_briefs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("store_code", sa.String(length=16), sa.ForeignKey("amz_stores.store_code", name="fk_amz_image_briefs_store", ondelete="CASCADE"), nullable=False),
            sa.Column("sku", sa.String(length=128), nullable=True),
            sa.Column("asin", sa.String(length=16), nullable=True),
            sa.Column("product_line", sa.String(length=32), nullable=False, server_default="other"),
            sa.Column("position", sa.String(length=16), nullable=False, server_default="main"),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
            sa.Column("brief_md", sa.Text(), nullable=False, server_default=""),
            sa.Column("evidence", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("must_have", _json(), nullable=False, server_default=_json_default(conn, "[]")),
            sa.Column("forbidden", _json(), nullable=False, server_default=_json_default(conn, "[]")),
            sa.Column("rounds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_rounds", sa.Integer(), nullable=False, server_default="4"),
            sa.Column("source_suggestion_id", sa.Uuid(), nullable=True),
            sa.Column("fact_sheet_id", sa.Uuid(), nullable=True),
            sa.Column("chosen_asset_id", sa.Uuid(), nullable=True),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("decided_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("live_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("baseline", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("lookback", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            *_stamps(),
        )
        op.create_index("ix_amz_image_briefs_store_status", "amz_image_briefs", ["store_code", "status"])
        op.create_index("ix_amz_image_briefs_suggestion", "amz_image_briefs", ["source_suggestion_id"])

    if not _table_exists(conn, "amz_image_assets"):
        op.create_table(
            "amz_image_assets",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("brief_id", sa.Uuid(), sa.ForeignKey("amz_image_briefs.id", name="fk_amz_image_assets_brief", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(length=24), nullable=False),
            sa.Column("round", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("object_key", sa.String(length=512), nullable=False),
            sa.Column("mime_type", sa.String(length=64), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("dhash", sa.String(length=32), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("submitted_via", sa.String(length=16), nullable=False, server_default="upload"),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="available"),
            sa.Column("review", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("decided_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
            *_stamps(),
        )
        op.create_index("ix_amz_image_assets_brief_kind", "amz_image_assets", ["brief_id", "kind"])


def downgrade() -> None:
    conn = op.get_bind()
    for name in TABLES:
        if _table_exists(conn, name):
            op.drop_table(name)
