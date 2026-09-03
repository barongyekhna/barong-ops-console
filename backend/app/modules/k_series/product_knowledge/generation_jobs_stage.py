"""多阶段 job 的进度写入。

单独成模块是为了打断循环依赖:``generation_jobs`` 需要 import
``selling_points_jobs`` 来分发卖点任务,而后者又要回写进度。这里只依赖
数据库 session,谁都可以安全 import。

进度落在 ``k_generation_jobs`` 行上而不是塞进产品的候选卖点 JSON,因为
``GET /selling-points`` 走 ``_selling_points_response_from_payload``,它按固定
字段清单重建响应、未知键会被整个剥掉;而且运营一提交审核,候选就被覆写,
塞在里面的进度会跟着消失。
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ....db.session import SessionLocal
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION

_TABLE = "k_generation_jobs"


def set_job_stage(
    job_id: UUID,
    stage: str,
    *,
    stage_errors: dict[str, Any] | None = None,
) -> None:
    """记录多阶段任务当前进行到哪一步。

    独立开一个 session(与 ``_set_job_status`` 同款姿势),这样即使业务 session
    正卡在长 AI 调用前后的 commit/rollback 之间,进度也照样能落库——前端的
    进度条不该受业务事务边界影响。
    """

    with SessionLocal() as db:
        db.execute(
            text(
                f"""
                UPDATE {_TABLE}
                SET stage = :stage,
                    stage_errors = COALESCE(
                        CAST(:stage_errors AS jsonb), stage_errors
                    ),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": job_id,
                "stage": stage,
                "stage_errors": (
                    json.dumps(stage_errors) if stage_errors is not None else None
                ),
            },
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )
        db.commit()
