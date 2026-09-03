"""给 storage_events.record_id 补索引 —— 外键子表侧的缺失索引。

`storage_events.record_id` 有外键指向 `event_streams.record_id`（删除规则
NO ACTION），但**子表侧这一列上没有任何索引**。

后果：删 `event_streams` 的每一行，Postgres 都要确认没有子行引用它，
没索引就是全表扫 110 万行。删 5000 行 = 扫 5000 遍，
直接撞上 8 秒的 statement_timeout。

这不是新问题，是建表时就有的：`event_streams` / `storage_events` 是
`event_collector._ensure_tables()` 在运行时建的，只写不删，所以两个多月来
从没暴露。2026-09-02 加观测数据留存清理时才撞上 —— 而清理的异常是被
吞成日志的，如果没有实测这条路径，它会**每小时静默失败一次、表继续涨**，
而且要到留存窗开始生效（约两周后）才发生，届时几乎不可能联想到这里。

代价很小：record_id 是唯一的短字符串，索引约 60 MB，
换掉的是「删父行时全表扫子表」。而且这两张表本来就该能删得动。

Revision ID: 20260902_02_index_storage_events_record_id
Revises: 20260902_01_drop_unused_observability_indexes
"""

from __future__ import annotations

from alembic import op

revision = "20260902_02_index_storage_events_record_id"
down_revision = "20260902_01_drop_unused_observability_indexes"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_storage_events_record_id"


def upgrade() -> None:
    # 这两张表由运行时逻辑建，不同环境不保证一致，所以 IF NOT EXISTS。
    op.execute(
        f'CREATE INDEX IF NOT EXISTS "{INDEX_NAME}" '
        "ON public.storage_events USING btree (record_id)"
    )


def downgrade() -> None:
    op.execute(f'DROP INDEX IF EXISTS public."{INDEX_NAME}"')
