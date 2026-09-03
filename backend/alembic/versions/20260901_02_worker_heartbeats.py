"""通用 worker 业务心跳表。

2026-08-31 体检最刺眼的一条：R-A worker 崩了整整一个月、白苏婉和霓旌瘫了一周、
C19 附件通道断了五周——三件事全都发生在 `docker ps` 一片 `Up` 的情况下。
**「容器活着」被当成了「功能正常」。**

容器级健康检查回答的是「进程还在吗」，而我们要问的是
**「它最近一次真的干成活是什么时候」**。这两件事在这套系统里反复被证明不是一回事：
- r-a-worker：容器 Up 5 weeks，实际最后一次输出停在一个月前的崩溃；
- r-w-keepa-daemon：容器 Up，每一轮都因 statement timeout 失败（2026-09-01 已修）；
- 两个数字员工：容器 Up，七天内每条日志都是「控制台够不着」。

这张表存的就是那个问题的答案。字段刻意做小：谁、最后一次成功、最后一次尝试、
连续失败几次、最后的错。判断「是不是该报警」交给读取方，因为不同 worker 的
正常间隔差很多（key-health 一小时一次，k-worker 三秒一轮）。

R 系列已有的 `rw_worker_status` 不动 —— 那张表带着 keepa/deepseek 的专有字段，
是 R-W 的运行面板；这张是跨模块的、只关心「活没干成」。

Revision ID: 20260901_02_worker_heartbeats
Revises: 20260901_01_products_rw_needs_image_index
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260901_02_worker_heartbeats"
down_revision = "20260901_01_products_rw_needs_image_index"
branch_labels = None
depends_on = None

TABLE = "worker_heartbeats"


def _table_exists(conn, name: str) -> bool:
    return bool(
        conn.exec_driver_sql(
            "SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, TABLE):
        return
    op.create_table(
        TABLE,
        # worker 的稳定标识，与 compose 服务名一致（k-worker / geo-worker / …）。
        sa.Column("worker_name", sa.String(length=64), primary_key=True),
        # 这个 worker 归哪个模块管，用于在控制台里分组显示。
        sa.Column("module_key", sa.String(length=64), nullable=False, server_default=""),
        # **最重要的一列**：最近一次真的干成一件活的时间。
        # 「多久没成功」= now() - last_success_at，这就是心跳要回答的问题。
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        # 最近一次尝试（不论成败）。与 last_success_at 拉开距离 = 一直在试但一直失败。
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        # 连续失败次数；成功一次即归零。
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        # 该 worker 正常情况下多久应该成功一次（秒）。读取方据此判断是否超时，
        # 因为各 worker 差异很大：key-health 一小时一次，k-worker 三秒一轮。
        sa.Column(
            "expected_interval_seconds",
            sa.Integer(),
            nullable=False,
            server_default="900",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        f"ix_{TABLE}_last_success_at", TABLE, ["last_success_at"]
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, TABLE):
        return
    op.drop_index(f"ix_{TABLE}_last_success_at", table_name=TABLE)
    op.drop_table(TABLE)
