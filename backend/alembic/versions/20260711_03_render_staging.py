"""渲染成品暂存态 + 单张重做参考图。

- k_image_render_jobs.reference_asset_id: 重做时指定"以哪张已生成图为参考"
  （空 = 用产品原始参考图）。
- 渲染成品从本版本起先落 status='staged'（暂存，不入硬门/审查/上架包），
  用户点「保存」才转 available；staged 超 24 小时惰性清除。

Revision ID: 20260711_03_render_staging
Revises: 20260711_02_webhook_registry
Create Date: 2026-07-11
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260711_03_render_staging"
down_revision: str | Sequence[str] | None = "20260711_02_webhook_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "k_image_render_jobs",
        sa.Column("reference_asset_id", sa.Uuid(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("k_image_render_jobs", "reference_asset_id")
