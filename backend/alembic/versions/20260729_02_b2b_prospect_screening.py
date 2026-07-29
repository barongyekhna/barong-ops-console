"""B2B prospect auto-screening results.

机器读官网判断"这家店值不值得发",结论落这几列。用户只读 screen_reason
那一句人话,不再自己看原始数据。

Revision ID: 20260729_02_b2b_prospect_screening
Revises: 20260729_01_geo_publish
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_02_b2b_prospect_screening"
down_revision: str | Sequence[str] | None = "20260729_01_geo_publish"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "b2b_prospects",
        sa.Column("website_source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "b2b_prospects",
        sa.Column("screen_verdict", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "b2b_prospects",
        sa.Column("screen_reason", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "b2b_prospects",
        sa.Column("screen_signals_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "b2b_prospects",
        sa.Column("screened_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_b2b_prospects_screen_verdict",
        "b2b_prospects",
        "screen_verdict IS NULL OR screen_verdict IN ('fit', 'unfit', 'unsure')",
    )
    # 界面默认只看"推荐发的",这个索引让筛完之后的列表查询走得动。
    op.create_index(
        "ix_b2b_prospects_screen_verdict",
        "b2b_prospects",
        ["screen_verdict"],
    )


def downgrade() -> None:
    op.drop_index("ix_b2b_prospects_screen_verdict", table_name="b2b_prospects")
    op.drop_constraint(
        "ck_b2b_prospects_screen_verdict", "b2b_prospects", type_="check"
    )
    for column in (
        "screened_at",
        "screen_signals_json",
        "screen_reason",
        "screen_verdict",
        "website_source",
    ):
        op.drop_column("b2b_prospects", column)
