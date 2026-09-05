"""写手 / 重写任务队列 + sm-worker 循环。照 GEO generation_jobs 的形状：
``FOR UPDATE SKIP LOCKED`` 领单、失败不拖垮别人、僵尸重排。

worker 每轮做三件事：① 有活跃渠道的每个 workspace 保证日历排到 28 天后
（每 6 小时一次）② 领写手任务 ③ 扫缺口单（每小时一次）。
**只在真做了事时刷心跳，并记本轮做了多少**（acceptance-must-be-implementation-independent）。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...db.session import SessionLocal
from ...models.user import User
from ...services.data_isolation import SKIP_ORG_DATA_ISOLATION, without_org_data_isolation
from ...services.worker_heartbeat import record_failure, record_success
from ..k_series.product_knowledge.scope_shim import KScopeContext, apply_scope_filters
from . import gaps, service
from .constants import MODULE_KEY, WORKER_HEARTBEAT_INTERVAL_SECONDS, WORKER_NAME
from .models import SmCalendarSlot, SmChannel, SmPost
from .writer import QuotaExhausted

logger = logging.getLogger("sm-worker")

_TABLE = "sm_generation_jobs"
JOB_WRITE = "write"
JOB_REVISE = "revise"
PLAN_EVERY_SECONDS = 6 * 3600
SWEEP_EVERY_SECONDS = 3600


def _poll_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("SM_WORKER_POLL_SECONDS", "5")))
    except ValueError:
        return 5.0


def _concurrency() -> int:
    try:
        return max(1, int(os.getenv("SM_WRITER_CONCURRENCY", "1")))
    except ValueError:
        return 1


# ---------------------------------------------------------------- 入队 / 状态


def enqueue(
    db: Session,
    *,
    scope: KScopeContext,
    job_type: str,
    slot_id: UUID | None = None,
    post_id: UUID | None = None,
    user: Any | None = None,
) -> UUID:
    job_id = uuid4()
    db.execute(
        text(
            f"""
            INSERT INTO {_TABLE}
                (id, slot_id, post_id, job_type, status, requested_by_username,
                 workspace_key, business_context, scope_mode, created_at, updated_at)
            VALUES
                (:id, :slot_id, :post_id, :job_type, 'pending', :username,
                 :workspace_key, :business_context, :scope_mode, now(), now())
            """
        ),
        {
            "id": job_id,
            "slot_id": slot_id,
            "post_id": post_id,
            "job_type": job_type,
            "username": getattr(user, "username", None),
            "workspace_key": scope.workspace_key,
            "business_context": scope.business_context,
            "scope_mode": scope.scope_mode,
        },
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    return job_id


def jobs_status(db: Session, *, scope: KScopeContext, limit: int = 50) -> list[dict[str, Any]]:
    with without_org_data_isolation():
        rows = db.execute(
            text(
                f"""
                SELECT id, slot_id, post_id, job_type, status, attempts, error, started_at, finished_at, created_at
                FROM {_TABLE}
                WHERE workspace_key = :workspace_key
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"workspace_key": scope.workspace_key, "limit": limit},
        ).mappings().all()
    return [
        {
            "job_id": str(r["id"]),
            "slot_id": str(r["slot_id"]) if r["slot_id"] else None,
            "post_id": str(r["post_id"]) if r["post_id"] else None,
            "job_type": r["job_type"],
            "status": r["status"],
            "attempts": r["attempts"],
            "error": r["error"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


def pending_or_running_for_slot(db: Session, slot_id: UUID) -> bool:
    with without_org_data_isolation():
        row = db.execute(
            text(f"SELECT 1 FROM {_TABLE} WHERE slot_id = :slot_id AND status IN ('pending','running') LIMIT 1"),
            {"slot_id": slot_id},
        ).first()
    return row is not None


def requeue_stale_running(db: Session, *, older_than_seconds: int = 900) -> int:
    result = db.execute(
        text(
            f"""
            UPDATE {_TABLE}
            SET status = 'pending', updated_at = now()
            WHERE status = 'running'
              AND started_at < now() - (:secs || ' seconds')::interval
            """
        ),
        {"secs": str(older_than_seconds)},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    db.commit()
    return result.rowcount or 0


# ---------------------------------------------------------------- worker 侧


def _claim(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            SELECT id, slot_id, post_id, job_type, requested_by_username,
                   workspace_key, business_context, scope_mode
            FROM {_TABLE}
            WHERE status = 'pending'
            ORDER BY created_at ASC
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
            SET status = 'running', started_at = now(), attempts = attempts + 1, updated_at = now()
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": ids},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    db.commit()
    return [dict(r) for r in rows]


def _finish(job_id: Any, status: str, *, error: str | None = None) -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                f"""
                UPDATE {_TABLE}
                SET status = :status, error = :error, finished_at = now(), updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": job_id, "status": status, "error": error},
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )
        db.commit()


def process_job(job: dict[str, Any]) -> None:
    job_id = job["id"]
    scope = KScopeContext(
        workspace_key=job["workspace_key"], business_context=job["business_context"], scope_mode=job["scope_mode"]
    )
    try:
        with SessionLocal() as db:
            username = job.get("requested_by_username")
            user = db.query(User).filter(User.username == username).first() if username else None
            if job["job_type"] == JOB_WRITE:
                slot = db.get(SmCalendarSlot, job["slot_id"])
                if slot is None:
                    raise RuntimeError("格子不存在")
                service.write_slot(db, scope, slot, user=user)
            elif job["job_type"] == JOB_REVISE:
                post = db.get(SmPost, job["post_id"])
                if post is None:
                    raise RuntimeError("帖子不存在")
                service.revise_post(db, scope, post, user=user)
            else:
                raise RuntimeError(f"未知任务类型 {job['job_type']}")
            db.commit()
        _finish(job_id, "done")
    except QuotaExhausted as exc:
        _reset_slot_status(job.get("slot_id"))
        _finish(job_id, "failed", error=f"quota: {exc.message}"[:1000])
    except Exception as exc:  # noqa: BLE001 - 隔离单个任务的失败
        logger.exception("SM job %s failed", job_id)
        _reset_slot_status(job.get("slot_id"))
        _finish(job_id, "failed", error=str(exc)[:1000])


def _reset_slot_status(slot_id: Any) -> None:
    if not slot_id:
        return
    try:
        with SessionLocal() as db:
            slot = db.get(SmCalendarSlot, slot_id)
            if slot is not None and slot.status == "writing":
                slot.status = "planned"
                db.commit()
    except Exception:  # noqa: BLE001 - best-effort
        logger.exception("failed to reset slot status")


def _active_scopes(db: Session) -> list[KScopeContext]:
    with without_org_data_isolation():
        rows = db.execute(
            select(SmChannel.workspace_key, SmChannel.business_context, SmChannel.scope_mode)
            .where(SmChannel.status == "active")
            .distinct()
        ).all()
    return [KScopeContext(workspace_key=r[0], business_context=r[1], scope_mode=r[2]) for r in rows]


class SmWorker:
    def __init__(self, *, session_factory: Callable[[], Session] = SessionLocal, poll_seconds: float | None = None) -> None:
        self.session_factory = session_factory
        self.poll_seconds = poll_seconds if poll_seconds is not None else _poll_seconds()
        self.concurrency = _concurrency()
        self._last_plan: dict[str, datetime] = {}
        self._last_sweep: dict[str, datetime] = {}

    # -- 排日历 / 扫缺口 -----------------------------------------------------
    def _housekeeping(self, *, log: Callable[[str], None] | None) -> int:
        did = 0
        now = datetime.now(UTC)
        with self.session_factory() as db:
            scopes = _active_scopes(db)
        for scope in scopes:
            key = scope.workspace_key
            try:
                if now - self._last_plan.get(key, datetime.min.replace(tzinfo=UTC)) >= timedelta(seconds=PLAN_EVERY_SECONDS):
                    with self.session_factory() as db, without_org_data_isolation():
                        result = service.plan_calendar(db, scope)
                        db.commit()
                    self._last_plan[key] = now
                    if result.created:
                        did += result.created
                        if log:
                            log(f"SM plan {key}: +{result.created} slots ({result.blocked} blocked)")
                if now - self._last_sweep.get(key, datetime.min.replace(tzinfo=UTC)) >= timedelta(seconds=SWEEP_EVERY_SECONDS):
                    with self.session_factory() as db, without_org_data_isolation():
                        counts = gaps.sweep(db, scope)
                        db.commit()
                    self._last_sweep[key] = now
                    moved = sum(counts.values())
                    if moved:
                        did += moved
                        if log:
                            log(f"SM gaps {key}: {counts}")
            except Exception as exc:  # noqa: BLE001
                logger.exception("SM housekeeping failed for %s", key)
                self._heartbeat(success=False, error=f"housekeeping {key}: {exc}")
        return did

    def _heartbeat(self, *, success: bool, error: str | None = None) -> None:
        try:
            with self.session_factory() as db:
                if success:
                    record_success(
                        db, worker_name=WORKER_NAME, module_key=MODULE_KEY,
                        expected_interval_seconds=WORKER_HEARTBEAT_INTERVAL_SECONDS,
                    )
                else:
                    record_failure(
                        db, worker_name=WORKER_NAME, error=error or "unknown", module_key=MODULE_KEY,
                        expected_interval_seconds=WORKER_HEARTBEAT_INTERVAL_SECONDS,
                    )
        except Exception:  # noqa: BLE001 - 心跳绝不拖垮业务
            logger.exception("SM heartbeat write failed")

    def run_once(self, *, log: Callable[[str], None] | None = None) -> bool:
        did_work = self._housekeeping(log=log) > 0
        with self.session_factory() as db:
            jobs = _claim(db, self.concurrency)
        for job in jobs:
            process_job(job)
            did_work = True
            if log:
                log(f"SM job {job['id']} ({job['job_type']}) processed")
        if did_work:
            self._heartbeat(success=True)
        return did_work

    def run_forever(self, *, should_stop: Callable[[], bool], log: Callable[[str], None] | None = None) -> None:
        if log:
            log(f"SM worker started poll={self.poll_seconds:g}s concurrency={self.concurrency}")
        # 起步先刷一次心跳，让「刚起来还没活干」和「根本没起来」分得开。
        self._heartbeat(success=True)
        while not should_stop():
            try:
                did = self.run_once(log=log)
            except Exception as exc:  # noqa: BLE001
                logger.exception("SM worker loop error")
                self._heartbeat(success=False, error=str(exc)[:500])
                did = False
            if not did:
                time.sleep(self.poll_seconds)


__all__ = [
    "JOB_REVISE",
    "JOB_WRITE",
    "SmWorker",
    "enqueue",
    "jobs_status",
    "pending_or_running_for_slot",
    "process_job",
    "requeue_stale_running",
]
