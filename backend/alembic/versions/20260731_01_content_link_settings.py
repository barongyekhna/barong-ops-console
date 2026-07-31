"""content_core 的 KV 表:链接图的指纹 / 推送时间 / dirty 标志 / 摘要。

链接图是 GEO + SEO + 产品页三边共有的东西,放在任何一边的表里都会让另外两边
"借"别人的家具。一张表、四个键。

Revision ID: 20260731_01_content_link_settings
Revises: 20260730_01_geo_mined_questions
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_01_content_link_settings"
down_revision: str | Sequence[str] | None = "20260730_01_geo_mined_questions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_link_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("content_link_settings")
