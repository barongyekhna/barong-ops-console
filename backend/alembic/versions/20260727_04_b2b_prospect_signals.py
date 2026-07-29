"""Add Google Places signals used for manual review.

Revision ID: 20260727_04_b2b_prospect_signals
Revises: 20260727_03_b2b_prospects
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_04_b2b_prospect_signals"
down_revision: str | Sequence[str] | None = "20260727_03_b2b_prospects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "b2b_prospects"


def upgrade() -> None:
    # 人工审核只有店名电话是判断不了的。谷歌返回的 category(店铺类型)和
    # cid(地图 ID,可拼出地图链接点开看店面照片和官网)才是真正的判断依据。
    op.add_column(TABLE, sa.Column("place_category", sa.String(length=128), nullable=True))
    op.add_column(TABLE, sa.Column("place_cid", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, "place_cid")
    op.drop_column(TABLE, "place_category")
