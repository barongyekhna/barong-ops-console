"""worker 业务心跳：回答「它最近一次真的干成活是什么时候」。

**为什么需要这个**（2026-08-31 体检）：
R-A worker 崩了一个月、白苏婉和霓旌瘫了一周、C19 附件通道断了五周——
三件事全都发生在 `docker ps` 一片 `Up` 的情况下。容器级健康检查回答的是
「进程还在吗」，而运维真正要问的是「它还在干活吗」。这两件事在这套系统里
反复被证明不是一回事。

更麻烦的是数字员工那条：家规要求「出事就说」，但她们上报的通道**就是控制台**，
控制台够不着时，她们没法上报「我够不着控制台」。故障自我遮蔽。
所以这里的数据要能被一个**不依赖控制台 UI** 的脚本读走（见
`scripts/check_worker_heartbeats.py`）。

**设计取舍**：接入成本必须极低，否则没人会去接。所以只有两个调用：
成功了叫一次 `record_success()`，失败了叫一次 `record_failure()`。
心跳写不进去**绝不能影响业务本身** —— 监控挂了是监控的事，不该把干活的 worker 拖下水。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .data_isolation import SKIP_ORG_DATA_ISOLATION

logger = logging.getLogger(__name__)

_TABLE = "worker_heartbeats"

# 判定「失联」时给的宽限倍数：连着 3 个正常间隔没成功才算异常，
# 避免正常抖动（一次网络超时、一次重试）就报警。
STALE_MULTIPLIER = 3


def record_success(
    db: Session,
    *,
    worker_name: str,
    module_key: str = "",
    expected_interval_seconds: int = 900,
) -> None:
    """记一次「真的干成了一件活」。连续失败计数归零。

    注意这里说的是**干成活**，不是「循环转了一圈」。空转一圈不该刷新心跳——
    否则一个一直空转、什么也没处理的 worker 看起来会永远健康。
    """
    _write(
        db,
        worker_name=worker_name,
        module_key=module_key,
        expected_interval_seconds=expected_interval_seconds,
        success=True,
        error=None,
    )


def record_failure(
    db: Session,
    *,
    worker_name: str,
    error: str,
    module_key: str = "",
    expected_interval_seconds: int = 900,
) -> None:
    """记一次失败。刷新 last_attempt_at，但**不动** last_success_at。

    这样「一直在试但一直失败」会表现为两个时间戳越拉越远 —— 正是
    r-w-keepa-daemon 每轮 statement timeout 时的样子。
    """
    _write(
        db,
        worker_name=worker_name,
        module_key=module_key,
        expected_interval_seconds=expected_interval_seconds,
        success=False,
        error=error[:2000],
    )


def _write(
    db: Session,
    *,
    worker_name: str,
    module_key: str,
    expected_interval_seconds: int,
    success: bool,
    error: str | None,
) -> None:
    try:
        db.execute(
            text(
                f"""
                INSERT INTO {_TABLE} (
                    worker_name, module_key, last_success_at, last_attempt_at,
                    consecutive_failures, last_error, expected_interval_seconds,
                    updated_at
                )
                VALUES (
                    :worker_name, :module_key,
                    CASE WHEN :success THEN now() ELSE NULL END,
                    now(),
                    CASE WHEN :success THEN 0 ELSE 1 END,
                    :error, :interval, now()
                )
                ON CONFLICT (worker_name) DO UPDATE SET
                    module_key = EXCLUDED.module_key,
                    last_success_at = CASE
                        WHEN :success THEN now()
                        ELSE {_TABLE}.last_success_at
                    END,
                    last_attempt_at = now(),
                    consecutive_failures = CASE
                        WHEN :success THEN 0
                        ELSE {_TABLE}.consecutive_failures + 1
                    END,
                    last_error = :error,
                    expected_interval_seconds = EXCLUDED.expected_interval_seconds,
                    updated_at = now()
                """
            ),
            {
                "worker_name": worker_name,
                "module_key": module_key,
                "success": success,
                "error": error,
                "interval": max(1, int(expected_interval_seconds)),
            },
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )
        db.commit()
    except Exception:  # noqa: BLE001
        # 心跳写不进去绝不能把业务拖下水。监控是给人看的，不是业务的前置条件。
        db.rollback()
        logger.exception("worker heartbeat write failed: %s", worker_name)


def list_heartbeats(db: Session) -> list[dict[str, Any]]:
    """所有 worker 的心跳 + 是否已经失联。

    失联判据不是「多久没心跳」，而是**多久没成功**：一个一直在重试、
    一直失败的 worker，心跳很新鲜，但它并没有在干活。
    """
    rows = db.execute(
        text(
            f"""
            SELECT worker_name, module_key, last_success_at, last_attempt_at,
                   consecutive_failures, last_error, expected_interval_seconds
            FROM {_TABLE}
            ORDER BY worker_name
            """
        ),
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).mappings().all()

    now = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for row in rows:
        interval = int(row["expected_interval_seconds"] or 900)
        deadline = timedelta(seconds=interval * STALE_MULTIPLIER)
        last_success = row["last_success_at"]
        if last_success is None:
            stale = True
            silent_for = None
        else:
            silent_for = now - last_success
            stale = silent_for > deadline
        out.append(
            {
                "worker_name": row["worker_name"],
                "module_key": row["module_key"],
                "last_success_at": last_success.isoformat() if last_success else None,
                "last_attempt_at": (
                    row["last_attempt_at"].isoformat() if row["last_attempt_at"] else None
                ),
                "consecutive_failures": int(row["consecutive_failures"] or 0),
                "last_error": row["last_error"],
                "expected_interval_seconds": interval,
                "silent_seconds": int(silent_for.total_seconds()) if silent_for else None,
                # 这一列就是「该不该找人」的答案。
                "stale": stale,
            }
        )
    return out
