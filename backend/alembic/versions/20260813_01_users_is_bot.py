"""users.is_bot: 数字员工标记

白苏婉(内容专员)这类数字员工需要在员工名单和 C19 通讯里一眼可辨,否则截图
流传出去会被当成老板本人说的话。

刻意新开一列而不是复用 role="bot_agent":那个 legacy role 被 core/rbac.py
映射成 ROLE_SYSTEM,只剩 ACTION_INTERNAL,数字员工连自己的 geo.content.read
都用不了。所以 role 照常走 viewer 那条正常权限链,is_bot 只作标签,
永远不参与任何鉴权判断。

Revision ID: 20260813_01_users_is_bot
Revises: 20260803_01_k_gen_jobs_stage
Create Date: 2026-08-13
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260813_01_users_is_bot"
down_revision: str | Sequence[str] | None = "20260803_01_k_gen_jobs_stage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "users"
COLUMN = "is_bot"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            COLUMN,
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN)
