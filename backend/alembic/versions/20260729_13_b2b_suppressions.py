"""B2B 永不再发名单。

跟进模板里写着"回复 no thanks 我就不烦你了",但系统里没地方记这件事——下一轮
生成草稿还会给他生成。一个说过"别发了"还继续收到信的人会直接点「举报垃圾
邮件」,投诉率一高 barongsupply.com 就废了(用户红线:退信/投诉率 >3% 杀域名)。

独立一张表而不是 prospect 上的字段:说"别发了"的人可能根本不在候选池里
(转发来的、我们删过的行、手填的地址),而且候选行删了名单不能跟着没。

Revision ID: 20260729_13_b2b_suppressions
Revises: 20260729_12_seo_content_tables
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_13_b2b_suppressions"
down_revision: str | Sequence[str] | None = "20260729_12_seo_content_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "b2b_suppressions",
        sa.Column("id", sa.Uuid(), nullable=False),
        # 规范化后的地址(小写/去空白/去 +tag)。不归一的话同一个人换个大小写
        # 或加个 +tag 就又能收到信。
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("raw_email", sa.String(length=320), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_b2b_suppressions_email", "b2b_suppressions", ["email"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_b2b_suppressions_email", table_name="b2b_suppressions")
    op.drop_table("b2b_suppressions")
