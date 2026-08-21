"""K generation jobs: per-stage progress + enqueue de-duplication

卖点生成从"一个同步请求跑完两次串行 DeepSeek 调用"改成三阶段异步 job
(bullets → zh → copy),运营点一次就能先看到卖点、中文和整段文案随后追加。
进度必须落在 job 行上而不是塞进 selling_points_candidates_json,因为
GET /selling-points 走 _selling_points_response_from_payload 按固定字段清单
重建响应,未知键会被整个剥掉;而且 approve 一覆写 candidates,进度就没了。

顺带补上入队去重:此前 enqueue_generation_jobs 没有任何去重,连点两次生成
按钮就是两条 pending,worker 并发跑两遍同一个产品、都写回同一行(后写的赢),
AI 费用翻倍。partial unique index 让"同产品同类型同时只能有一个未完成任务"
成为数据库层面的保证,而不是只靠前端按钮 disable(刷新页面/双标签页就绕过去)。

Revision ID: 20260803_01_k_gen_jobs_stage
Revises: 20260802_01_content_desk_permissions
Create Date: 2026-08-03
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260803_01_k_gen_jobs_stage"
down_revision: str | Sequence[str] | None = "20260802_01_content_desk_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "k_generation_jobs"
ACTIVE_UNIQUE_INDEX = "uq_k_gen_jobs_active_product_type"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("stage", sa.String(length=32), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "stage_errors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # 先清理历史遗留的重复未完成任务,否则唯一索引建不起来。
    # 每个 (product_id, job_type) 只保留最新的一条,其余标记为 failed。
    op.execute(
        sa.text(
            f"""
            UPDATE {TABLE} AS j
            SET status = 'failed',
                error = COALESCE(j.error, 'superseded by newer job (dedup migration)'),
                finished_at = COALESCE(j.finished_at, now()),
                updated_at = now()
            WHERE j.status IN ('pending', 'running')
              AND EXISTS (
                  SELECT 1 FROM {TABLE} AS newer
                  WHERE newer.product_id = j.product_id
                    AND newer.job_type = j.job_type
                    AND newer.status IN ('pending', 'running')
                    AND (newer.created_at, newer.id) > (j.created_at, j.id)
              )
            """
        )
    )

    op.create_index(
        ACTIVE_UNIQUE_INDEX,
        TABLE,
        ["product_id", "job_type"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(ACTIVE_UNIQUE_INDEX, table_name=TABLE)
    op.drop_column(TABLE, "stage_errors")
    op.drop_column(TABLE, "stage")
