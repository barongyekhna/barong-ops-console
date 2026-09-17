"""A4 推新流程与评论簇:amz_launches(六步状态机)、amz_reviews(贴进来的评论 + 归簇)。

无 org_id 列(家规 14)。to_regclass 幂等。

Revision ID: 20260917_03_amz_launches
Revises: 20260917_02_amz_experience
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260917_03_amz_launches"
down_revision = "20260917_02_amz_experience"
branch_labels = None
depends_on = None

TABLES = ("amz_reviews", "amz_launches")


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
    if not _table_exists(conn, "amz_launches"):
        op.create_table(
            "amz_launches",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("store_code", sa.String(length=16), sa.ForeignKey("amz_stores.store_code", name="fk_amz_launches_store", ondelete="CASCADE"), nullable=False),
            sa.Column("product_line", sa.String(length=32), nullable=False),
            sa.Column("sku", sa.String(length=128), nullable=True),
            sa.Column("asin", sa.String(length=16), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("stage", sa.String(length=16), nullable=False, server_default="pnl"),
            sa.Column("inputs", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("pnl", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("battlefield", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("checklist", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("honeymoon", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("verdict", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("retro", _json(), nullable=False, server_default=_json_default(conn, "{}")),
            sa.Column("live_on", sa.Date(), nullable=True),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
            *_stamps(),
        )
        op.create_index("ix_amz_launches_store_stage", "amz_launches", ["store_code", "stage"])

    if not _table_exists(conn, "amz_reviews"):
        op.create_table(
            "amz_reviews",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("launch_id", sa.Uuid(), sa.ForeignKey("amz_launches.id", name="fk_amz_reviews_launch", ondelete="CASCADE"), nullable=True),
            sa.Column("store_code", sa.String(length=16), sa.ForeignKey("amz_stores.store_code", name="fk_amz_reviews_store", ondelete="SET NULL"), nullable=True),
            sa.Column("product_line", sa.String(length=32), nullable=False),
            sa.Column("asin", sa.String(length=16), nullable=True),
            sa.Column("whose", sa.String(length=16), nullable=False, server_default="ours"),
            sa.Column("stars", sa.Integer(), nullable=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("text_sha256", sa.String(length=64), nullable=False),
            sa.Column("family", sa.String(length=16), nullable=True),
            sa.Column("cluster", sa.String(length=120), nullable=True),
            sa.Column("clustered_by", sa.String(length=16), nullable=True),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
            *_stamps(),
            sa.UniqueConstraint("product_line", "whose", "asin", "text_sha256", name="uq_amz_reviews_text"),
        )
        op.create_index("ix_amz_reviews_line_whose", "amz_reviews", ["product_line", "whose"])


def downgrade() -> None:
    conn = op.get_bind()
    for name in TABLES:
        if _table_exists(conn, name):
            op.drop_table(name)
