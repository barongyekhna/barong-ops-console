"""F 市场参考页 — 图搜种子图的来源网页收割

图搜接力从谷歌拿种子图时，图片来源网页（常是亚马逊/沃尔玛产品页）
顺手存下来（每画像产品~3条），供用户研究竞品定价与变体配置。

Revision ID: 20260714_04_f_market_refs
Revises: 20260714_03_arcade_high_scores
Create Date: 2026-07-14
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260714_04_f_market_refs"
down_revision: str | Sequence[str] | None = "20260714_03_arcade_high_scores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "f_product_market_refs"


def upgrade() -> None:
    op.create_table(
        T,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.String(length=32), nullable=False),
        sa.Column("profile_product_zh", sa.String(length=200), nullable=False),
        sa.Column("profile_product_en", sa.String(length=200), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("page_url", sa.String(length=2048), nullable=False),
        sa.Column("source_domain", sa.String(length=255), nullable=True),
        sa.Column("site_type", sa.String(length=20), nullable=True),
        sa.Column("image_url", sa.String(length=2048), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_f_market_refs_group", T, ["category_id", "profile_product_zh"]
    )


def downgrade() -> None:
    op.drop_index("ix_f_market_refs_group", table_name=T)
    op.drop_table(T)
