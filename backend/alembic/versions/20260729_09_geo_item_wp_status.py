"""记录指南文章在 WordPress 上的真实状态。

`published_url` 非空只说明"写进过 WP",不等于访客看得到:n8n 首次建文刻意落
draft 等人工发布,而那一刻 URL 就已经写进库了;用户之后在 WP 后台点发布,控制台
无从得知。结果是产品页的「Learn more」反链、批发页挂的指南,都可能指向草稿——
访客点过去 404。

修在源头:让库记下真实状态,由一次批量 API 刷新维护,所有消费方只读这一列,
不必各自再查一遍网(否则逐产品调用就会变成 N 次请求)。

Revision ID: 20260729_09_geo_item_wp_status
Revises: 20260729_08_b2b_site_settings
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_09_geo_item_wp_status"
down_revision: str | Sequence[str] | None = "20260729_08_b2b_site_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "geo_content_items",
        sa.Column("wp_status", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("geo_content_items", "wp_status")
