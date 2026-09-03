"""给 auth_sessions 补 active_org_id —— 让多组织用户能真的切换组织。

2026-08-31 体检：`middleware/org_context.py:155` 的 `_server_state_active_org_id`
依次读 6 个来源，其中一个是 `auth_session.active_org_id`。**而这一列根本不存在。**
另外 5 个来源（`request.state.*`、`jwt_claims`、`session_claims`）在整个 `app/` 里
只出现在这一个文件、从无人写。所以那个函数恒返回 None，
`_resolve_org` 里那 24 行「会话选定组织」分支**永不执行**。

后果：任何拥有 ≥2 个 active 成员关系、又不恰好是某组织 `owner_user_id` 的用户，
解析链全落空 → 整站 403 `C18H org context is required.`。
真 owner 只是碰巧靠 `_owner_org_for_user` 兜底才没暴雷 —— 本次体检建 QA 账号时
一头撞上，只能把测试账号收敛成单组织才跑得起来。

而前端**根本没有组织切换器**（全库 0 处相关 UI），所以撞上了也没有自救出口。

这一列就是那条死分支缺的东西。纯 additive、可为空，旧代码完全不受影响
（9 个 worker 在发版窗口里跑旧镜像，读不到这列也不会出错）。

Revision ID: 20260901_03_auth_session_active_org
Revises: 20260901_02_worker_heartbeats
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260901_03_auth_session_active_org"
down_revision = "20260901_02_worker_heartbeats"
branch_labels = None
depends_on = None

TABLE = "auth_sessions"
COLUMN = "active_org_id"


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(
        conn.exec_driver_sql(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = %(t)s AND column_name = %(c)s",
            {"t": table, "c": column},
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, TABLE, COLUMN):
        return
    op.add_column(
        TABLE,
        # 与 organizations.org_id 同宽。可为空 = 「这个会话还没选组织」，
        # 此时解析链继续往下走（唯一成员关系 → user.organization_id → 名下组织），
        # 与既有行为完全一致。
        sa.Column(COLUMN, sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, TABLE, COLUMN):
        return
    op.drop_column(TABLE, COLUMN)
