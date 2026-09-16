"""amz-worker:按 (店铺 × 作业类型) 排队,FOR UPDATE SKIP LOCKED 领活,只在真干成活时写心跳。

A2 期只有一种作业 ``rules_daily``(D 员工规则引擎跑种子数据);A1 接上 API 后往 ``JOB_INTERVALS`` 加同步作业即可。
心跳名 ``amz-worker:{store}:{job}``(String(64)),每店每种作业一条,验收只认它。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...db.session import SessionLocal
from ...services.data_isolation import SKIP_ORG_DATA_ISOLATION
from ...services.worker_heartbeat import record_failure, record_success
from . import rules
from .constants import MODULE_KEY, WORKER_NAME
from .models import AmzJob, AmzStore

logger = logging.getLogger("amz-worker")

JOB_RULES_DAILY = "rules_daily"
# 作业 → 期望间隔(秒)。心跳的 expected_interval 也用它;超过 3 倍没干成活 = stale。
JOB_INTERVALS: dict[str, int] = {JOB_RULES_DAILY: 24 * 3600}
_TABLE = "amz_jobs"


def poll_seconds() -> float:
    try:
        return max(2.0, float(os.getenv("AMZ_WORKER_POLL_SECONDS", "15")))
    except ValueError:
        return 15.0


def heartbeat_name(store_code: str, job_type: str) -> str:
    return f"{WORKER_NAME}:{store_code}:{job_type}"


# ---------------------------------------------------------------- 排队


def schedule_due_jobs(db: Session, *, now: datetime | None = None) -> int:
    """每个活跃店 × 每种作业:没有 pending/running 且距上次完成超过间隔 → 补一条 pending。"""
    now = now or datetime.now(UTC)
    created = 0
    stores = list(db.scalars(select(AmzStore.store_code).where(AmzStore.status == "active")))
    for store_code in stores:
        for job_type, interval in JOB_INTERVALS.items():
            active = db.scalar(
                select(AmzJob.id).where(
                    AmzJob.store_code == store_code,
                    AmzJob.job_type == job_type,
                    AmzJob.status.in_(("pending", "running")),
                ).limit(1)
            )
            if active is not None:
                continue
            last_done = db.scalar(
                select(AmzJob.finished_at)
                .where(AmzJob.store_code == store_code, AmzJob.job_type == job_type, AmzJob.status == "done")
                .order_by(AmzJob.finished_at.desc())
                .limit(1)
            )
            if last_done is not None and (now - last_done) < timedelta(seconds=interval):
                continue
            db.add(AmzJob(store_code=store_code, job_type=job_type, status="pending", run_after=now))
            created += 1
    db.commit()
    return created


def requeue_stale_running(db: Session, *, older_than_seconds: int = 1800) -> int:
    result = db.execute(
        text(
            f"""
            UPDATE {_TABLE}
            SET status = 'pending', updated_at = now(), last_error = 'requeued: stale running'
            WHERE status = 'running' AND started_at < now() - make_interval(secs => :age)
            """
        ),
        {"age": older_than_seconds},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    db.commit()
    return int(result.rowcount or 0)


def claim(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            SELECT id, store_code, job_type
            FROM {_TABLE}
            WHERE status = 'pending' AND run_after <= now()
            ORDER BY run_after ASC
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"limit": limit},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).mappings().all()
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    db.execute(
        text(
            f"""
            UPDATE {_TABLE}
            SET status = 'running', started_at = now(), locked_at = now(), attempts = attempts + 1, updated_at = now()
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": ids},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    db.commit()
    return [dict(r) for r in rows]


def finish(job_id: Any, status: str, *, error: str | None = None, payload: dict[str, Any] | None = None) -> None:
    with SessionLocal() as db:
        row = db.get(AmzJob, job_id)
        if row is None:
            return
        row.status = status
        row.last_error = (error or "")[:2000] or None
        row.finished_at = datetime.now(UTC)
        if payload is not None:
            row.payload_json = payload
        db.add(row)
        db.commit()


# ---------------------------------------------------------------- 执行


def run_rules_daily(store_code: str) -> dict[str, Any]:
    with SessionLocal() as db:
        store = db.get(AmzStore, store_code)
        if store is None:
            raise RuntimeError(f"store {store_code} missing")
        counts = rules.run_rules_for_store(db, store_code=store_code, currency=store.currency)
        db.commit()
        return counts


HANDLERS: dict[str, Callable[[str], dict[str, Any]]] = {JOB_RULES_DAILY: run_rules_daily}


def process_job(job: dict[str, Any]) -> bool:
    store_code, job_type = job["store_code"], job["job_type"]
    handler = HANDLERS.get(job_type)
    if handler is None:
        finish(job["id"], "failed", error=f"no handler for {job_type}")
        return False
    try:
        result = handler(store_code)
    except Exception as exc:  # noqa: BLE001 - 一条作业炸了不能拖死循环
        logger.exception("amz job failed store=%s job=%s", store_code, job_type)
        finish(job["id"], "failed", error=str(exc))
        with SessionLocal() as db:
            record_failure(db, worker_name=heartbeat_name(store_code, job_type), error=str(exc)[:500], module_key=MODULE_KEY, expected_interval_seconds=JOB_INTERVALS[job_type])
        return False
    finish(job["id"], "done", payload=result)
    with SessionLocal() as db:
        record_success(db, worker_name=heartbeat_name(store_code, job_type), module_key=MODULE_KEY, expected_interval_seconds=JOB_INTERVALS[job_type])
    logger.info("amz job done store=%s job=%s result=%s", store_code, job_type, result)
    return True


class AmzWorker:
    def __init__(self, *, session_factory: Callable[[], Session] = SessionLocal, poll: float | None = None, concurrency: int = 2) -> None:
        self.session_factory = session_factory
        self.poll = poll or poll_seconds()
        self.concurrency = concurrency

    def run_once(self, *, log: Callable[[str], None] | None = None) -> bool:
        did_work = False
        with self.session_factory() as db:
            created = schedule_due_jobs(db)
            if created and log:
                log(f"scheduled {created} amz jobs")
            jobs = claim(db, self.concurrency)
        for job in jobs:
            process_job(job)
            did_work = True
        return did_work

    def run_forever(self, *, should_stop: Callable[[], bool], log: Callable[[str], None] | None = None) -> None:
        if log:
            log(f"amz worker started poll={self.poll:g}s concurrency={self.concurrency}")
        # 起步只写一次「进程活着」的总心跳;每店每种作业的心跳只在真干成活时写。
        with self.session_factory() as db:
            record_success(db, worker_name=WORKER_NAME, module_key=MODULE_KEY, expected_interval_seconds=JOB_INTERVALS[JOB_RULES_DAILY])
        while not should_stop():
            try:
                did_work = self.run_once(log=log)
            except Exception as exc:  # noqa: BLE001
                logger.exception("amz worker loop error")
                with self.session_factory() as db:
                    record_failure(db, worker_name=WORKER_NAME, error=str(exc)[:500], module_key=MODULE_KEY, expected_interval_seconds=JOB_INTERVALS[JOB_RULES_DAILY])
                did_work = False
            if not did_work:
                time.sleep(self.poll)


__all__ = ["AmzWorker", "JOB_INTERVALS", "JOB_RULES_DAILY", "claim", "finish", "heartbeat_name", "process_job", "requeue_stale_running", "schedule_due_jobs"]
