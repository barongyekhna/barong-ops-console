"""独立站流量表（Jetpack Stats 采集）。

贸易公司主页置顶那张流量卡的数据源。n8n 流 `barongWtraffic001` 每 10 分钟拉
站内 Jetpack REST 七个接口，原样推到 `/w/traffic/ingest`，控制台归一化后
按 (workspace_key, 日) / (workspace_key, 小时桶) upsert。

`day` 按**站点时区**分日（实测 UTC-5），原样入库，不做二次换算——否则永远
和 WordPress 后台对不上。

Revision ID: 20260905_01_w_traffic
Revises: 20260903_01_user_skin_pref
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260905_01_w_traffic"
down_revision = "20260903_01_user_skin_pref"
branch_labels = None
depends_on = None

DAILY = "w_traffic_daily"
HOURLY = "w_traffic_hourly"


def _table_exists(conn, name: str) -> bool:
    return bool(
        conn.exec_driver_sql(
            "SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}
        ).scalar()
    )


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, DAILY):
        op.create_table(
            DAILY,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("workspace_key", sa.String(length=128), nullable=False),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("visitors", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("top_posts_json", _json(), nullable=True),
            sa.Column("referrers_json", _json(), nullable=True),
            sa.Column("countries_json", _json(), nullable=True),
            sa.Column("search_terms_json", _json(), nullable=True),
            sa.Column("clicks_json", _json(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint("workspace_key", "day", name="uq_w_traffic_daily_ws_day"),
        )
    if not _table_exists(conn, HOURLY):
        op.create_table(
            HOURLY,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("workspace_key", sa.String(length=128), nullable=False),
            sa.Column("bucket_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("visitors", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "workspace_key", "bucket_at", name="uq_w_traffic_hourly_ws_bucket"
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, HOURLY):
        op.drop_table(HOURLY)
    if _table_exists(conn, DAILY):
        op.drop_table(DAILY)
