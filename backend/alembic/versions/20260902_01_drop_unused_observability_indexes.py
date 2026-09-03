"""删掉两张观测表上 14 条从没被查过的二级索引。

`event_streams` 与 `storage_events` 是全库写得最频繁的两张表
（各约 107 万行，每小时各涨约 2,400 行），身上却挂着十几条二级索引。
2026-09-01 与 09-02 两次采样，下面这些的 `idx_scan` **一直是 0**
——不是「用得少」，是从统计开始至今一次都没被查询计划选中过。
每一条 INSERT 都要为它们各维护一棵 B-tree，纯是白付。

**保留**了同批里被扫到过的四条（org_id+created_at / org_id+timestamp /
org_id+event_type，以及 storage_events 的 org_id+created_at）——
哪怕只被扫过两三次，也说明确有查询在用。

主键与唯一约束一条没动。降级会把它们原样建回来（定义取自生产库
pg_get_indexdef 原文），重建 100 万行大约要几分钟。

Revision ID: 20260902_01_drop_unused_observability_indexes
Revises: 20260901_04_drop_redundant_indexes
"""

from __future__ import annotations

from alembic import op

revision = "20260902_01_drop_unused_observability_indexes"
down_revision = "20260901_04_drop_redundant_indexes"
branch_labels = None
depends_on = None


UNUSED_INDEXES: tuple[tuple[str, str], ...] = (
    # event_streams
    ("ix_event_streams_module_id", "CREATE INDEX ix_event_streams_module_id ON public.event_streams USING btree (module_id)"),
    # event_streams
    ("ix_event_streams_org_id_actor_id", "CREATE INDEX ix_event_streams_org_id_actor_id ON public.event_streams USING btree (org_id, actor_id)"),
    # event_streams
    ("ix_event_streams_org_id_context_id", "CREATE INDEX ix_event_streams_org_id_context_id ON public.event_streams USING btree (org_id, context_id)"),
    # event_streams
    ("ix_event_streams_org_id_job_id", "CREATE INDEX ix_event_streams_org_id_job_id ON public.event_streams USING btree (org_id, job_id)"),
    # event_streams
    ("ix_event_streams_org_id_module_id", "CREATE INDEX ix_event_streams_org_id_module_id ON public.event_streams USING btree (org_id, module_id)"),
    # event_streams
    ("ix_event_streams_org_id_status", "CREATE INDEX ix_event_streams_org_id_status ON public.event_streams USING btree (org_id, status)"),
    # event_streams
    ("ix_event_streams_org_id_trace_id", "CREATE INDEX ix_event_streams_org_id_trace_id ON public.event_streams USING btree (org_id, trace_id)"),
    # event_streams
    ("ix_event_streams_org_id_workflow_id", "CREATE INDEX ix_event_streams_org_id_workflow_id ON public.event_streams USING btree (org_id, workflow_id)"),
    # event_streams
    ("ix_event_streams_processing_status_next_retry_at", "CREATE INDEX ix_event_streams_processing_status_next_retry_at ON public.event_streams USING btree (processing_status, next_retry_at)"),
    # event_streams
    ("ix_event_streams_trace_id", "CREATE INDEX ix_event_streams_trace_id ON public.event_streams USING btree (trace_id)"),
    # storage_events
    ("ix_storage_events_org_id_context_id", "CREATE INDEX ix_storage_events_org_id_context_id ON public.storage_events USING btree (org_id, context_id)"),
    # storage_events
    ("ix_storage_events_org_id_operation", "CREATE INDEX ix_storage_events_org_id_operation ON public.storage_events USING btree (org_id, operation)"),
    # storage_events
    ("ix_storage_events_org_id_status", "CREATE INDEX ix_storage_events_org_id_status ON public.storage_events USING btree (org_id, status)"),
    # storage_events
    ("ix_storage_events_org_id_trace_id", "CREATE INDEX ix_storage_events_org_id_trace_id ON public.storage_events USING btree (org_id, trace_id)"),
)


def upgrade() -> None:
    # IF EXISTS：这两张表是 event_collector._ensure_tables() 在运行时建的，
    # 不同环境的索引集合不一定一致。缺一条不该让整条迁移链停住。
    for name, _ in UNUSED_INDEXES:
        op.execute(f'DROP INDEX IF EXISTS public."{name}"')


def downgrade() -> None:
    for _, create_sql in UNUSED_INDEXES:
        op.execute(create_sql.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1))
