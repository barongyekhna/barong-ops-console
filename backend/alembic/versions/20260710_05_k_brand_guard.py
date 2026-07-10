"""K product knowledge: brand guard (品牌硬门)

独立站死命令：页面/图片/结构化数据绝不出现第三方品牌；结构化数据品牌永远
只有 Barong Yekhna。两列支撑：

- detected_brand_terms: 源头（R→K 搬运等）识别出的第三方品牌词黑名单，
  只作内部审查/生成红线依据，永不进上架包。
- brand_audit_json: 独立 AI 审查（文本面 + 每张成品图视觉审）的结果快照，
  含 content fingerprint —— P 上架门禁要求 audit 存在、clean、且指纹与
  当前内容一致（fail-closed）。

Revision ID: 20260710_05_k_brand_guard
Revises: 20260710_04_key_health
Create Date: 2026-07-10
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260710_05_k_brand_guard"
down_revision: str | Sequence[str] | None = "20260710_04_key_health"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "k_product_knowledge_products"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("detected_brand_terms", sa.JSON(), nullable=True))
    op.add_column(TABLE, sa.Column("brand_audit_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, "brand_audit_json")
    op.drop_column(TABLE, "detected_brand_terms")
