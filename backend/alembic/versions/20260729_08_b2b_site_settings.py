"""B2B site settings KV (wholesale page ids).

存 /wholesale/ 主页和各店型子页的 WordPress 页面 id。页面在第一次发布时创建
或认领,之后每次重发靠 id 找回来——没有它就只能按 slug 猜,一超时就会建出
重复页。

**不复用 GEO 的 geo_site_settings**:跨模块共用一张表会让两边迁移互相绑死。

Revision ID: 20260729_08_b2b_site_settings
Revises: 20260729_07_geo_question_answer_type
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_08_b2b_site_settings"
down_revision: str | Sequence[str] | None = "20260729_07_geo_question_answer_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "b2b_site_settings",
        sa.Column("key", sa.String(length=96), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # 页面 1792 是手工建的,先认领进来,避免第一次发布时又建一个新的。
    op.execute(
        "INSERT INTO b2b_site_settings (key, value) "
        "VALUES ('wholesale_page_id', '1792') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("b2b_site_settings")
