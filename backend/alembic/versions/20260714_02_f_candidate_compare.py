"""F 候选对比进阶档 — 画像产品分组 + 评分 + top3 推荐

用户拍板（2026-07-14）：候选按画像产品分组，每组自动推荐评分最高 3 家
（MOQ 越小分越高为重要加分项），其余折叠可展开。

- profile_product_zh/en: 来源画像产品（分组键；手动候选/旧数据为 NULL）
- score: 0-100 推荐分；score_json: 分项明细（MOQ/月销/一件代发/组内价格）
- recommended_rank: 组内推荐名次 1-3，其余 NULL（折叠）

Revision ID: 20260714_02_f_candidate_compare
Revises: 20260714_01_w_logistics_hub
Create Date: 2026-07-14
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260714_02_f_candidate_compare"
down_revision: str | Sequence[str] | None = "20260714_01_w_logistics_hub"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "f_category_candidates"


def upgrade() -> None:
    op.add_column(
        T, sa.Column("profile_product_zh", sa.String(length=200), nullable=True)
    )
    op.add_column(
        T, sa.Column("profile_product_en", sa.String(length=200), nullable=True)
    )
    op.add_column(T, sa.Column("score", sa.Integer(), nullable=True))
    op.add_column(T, sa.Column("score_json", sa.JSON(), nullable=True))
    op.add_column(T, sa.Column("recommended_rank", sa.Integer(), nullable=True))
    op.create_index(
        "ix_f_candidates_category_product",
        T,
        ["category_id", "profile_product_zh"],
    )


def downgrade() -> None:
    op.drop_index("ix_f_candidates_category_product", table_name=T)
    op.drop_column(T, "recommended_rank")
    op.drop_column(T, "score_json")
    op.drop_column(T, "score")
    op.drop_column(T, "profile_product_en")
    op.drop_column(T, "profile_product_zh")
