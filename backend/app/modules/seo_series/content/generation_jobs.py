"""SEO 生成队列(由 ``seo-worker`` 容器排空)。

与 GEO 队列同构:``FOR UPDATE SKIP LOCKED`` 领单、线程池跑、卡死单自愈重排。
**刻意不合并成一个通用队列**——两边的 worker 是两个独立容器,合并之后
一边挂掉会拖住另一边的排队,而且 GEO 的长任务(一次生成整簇)和 SEO 的短任务
(一次一篇)并发度天然不同。共享的是模式,不是运行时。

死规矩:worker 有**自己的镜像**。改了这个文件或 orchestrator,必须
``docker-compose build seo-worker`` 并重建容器,``--service backend`` 碰不到它。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from ....db.session import SessionLocal
from ....models.user import User
from ...k_series.product_knowledge.scope_shim import KScopeContext
from .orchestrator import SeoContentOrchestrator

logger = logging.getLogger(__name__)

_TABLE = "seo_generation_jobs"


def _worker_concurrency(value: int | None = None) -> int:
    if value is not None:
        return max(1, value)
    try:
        return max(1, int(os.getenv("SEO_GENERATION_CONCURRENCY", "2")))
    except (TypeError, ValueError):
        return 2


def _poll_seconds() -> float:
    try:
        return max(0.5, float(os.getenv("SEO_GENERATION_POLL_SECONDS", "3")))
    except (TypeError, ValueError):
        return 3.0


def enqueue_seo_jobs(
    db: Session,
    *,
    topic_ids: Sequence[UUID],
    user: User | None,
    scope_context: KScopeContext,
    job_kind: str = "generate",
) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    for topic_id in topic_ids:
        job_id = uuid4()
        db.execute(
            text(
                f"""
                INSERT INTO {_TABLE}
                    (id, topic_id, job_kind, status, requested_by_user_id,
                     requested_by_username, workspace_key, business_context,
                     scope_mode, created_at, updated_at)
                VALUES
                    (:id, :topic_id, :job_kind, 'queued', :user_id, :username,
                     :workspace_key, :business_context, :scope_mode, now(), now())
                """
            ),
            {
                "id": job_id,
                "topic_id": topic_id,
                "job_kind": job_kind,
                "user_id": getattr(user, "id", None),
                "username": getattr(user, "username", None),
                "workspace_key": scope_context.workspace_key,
                "business_context": scope_context.business_context,
                "scope_mode": scope_context.scope_mode,
            },
        )
        created.append({"job_id": str(job_id), "topic_id": str(topic_id)})
    return created


def jobs_status(db: Session, *, limit: int = 50) -> list[dict[str, Any]]:
    """最近的任务。失败的会标 ``superseded``——**同一个选题后来跑成功了**。

    为什么需要这个:失败记录是历史,不该永远在面板上显示成报错。
    2026-07-31 用户看到「生成失败：'SeoContentItem' object has no attribute
    'item_type'」以为是新问题,其实那是前一天的记录,bug 一分钟后就修了、
    后面两次都成功了。**修好的东西一直红着,比不显示更糟——它会让人对
    真正的报错脱敏。**

    判据不是"多久以前",而是"这个选题后来成没成"——一个三天前失败、至今
    没成功过的任务,仍然该显示。
    """
    rows = db.execute(
        text(
            f"""
            SELECT id, topic_id, job_kind, status, error, started_at, finished_at,
                   created_at
            FROM {_TABLE}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).mappings().all()

    # 每个选题最近一次成功的时间;比它早的失败都已经被覆盖了。
    last_success: dict[Any, Any] = {}
    for r in rows:
        if r["status"] == "success":
            key = r["topic_id"]
            if key not in last_success or (r["created_at"] or 0) > last_success[key]:
                last_success[key] = r["created_at"]

    out: list[dict[str, Any]] = []
    for r in rows:
        superseded = (
            r["status"] == "failed"
            and r["topic_id"] in last_success
            and (r["created_at"] or 0) < last_success[r["topic_id"]]
        )
        out.append(
            {
                "job_id": str(r["id"]),
                "topic_id": str(r["topic_id"]),
                "job_kind": r["job_kind"],
                "status": r["status"],
                "error": r["error"],
                "superseded": superseded,
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "finished_at": (
                    r["finished_at"].isoformat() if r["finished_at"] else None
                ),
            }
        )
    return out


def _claim_queued(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            SELECT id, topic_id, job_kind, requested_by_username,
                   workspace_key, business_context, scope_mode
            FROM {_TABLE}
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"limit": limit},
    ).mappings().all()
    if not rows:
        return []
    db.execute(
        text(
            f"""
            UPDATE {_TABLE}
            SET status = 'running', started_at = now(), updated_at = now()
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": [r["id"] for r in rows]},
    )
    db.commit()
    return [dict(r) for r in rows]


def _finish(job_id: Any, status: str, *, error: str | None = None) -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                f"""
                UPDATE {_TABLE}
                SET status = :status, error = :error,
                    finished_at = now(), updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": job_id, "status": status, "error": error},
        )
        db.commit()


def _process(job: dict[str, Any]) -> None:
    job_id = job["id"]
    try:
        with SessionLocal() as db:
            username = job.get("requested_by_username")
            user = (
                db.query(User).filter(User.username == username).first()
                if username
                else None
            )
            scope = KScopeContext(
                workspace_key=job["workspace_key"],
                business_context=job["business_context"],
                scope_mode=job["scope_mode"],
            )
            orchestrator = SeoContentOrchestrator(db)
            if job.get("job_kind") == "revise":
                orchestrator.revise(
                    item_id=job["topic_id"], scope_context=scope, user=user
                )
            else:
                orchestrator.generate(
                    topic_id=job["topic_id"], scope_context=scope, user=user
                )
        _finish(job_id, "success")
    except Exception as exc:  # noqa: BLE001 - 一单失败不该毁掉整个 worker
        logger.exception("SEO generation job failed")
        _finish(job_id, "failed", error=str(exc)[:1000])


class SeoGenerationJobWorker:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        concurrency: int | None = None,
        poll_seconds: float | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.concurrency = _worker_concurrency(concurrency)
        self.poll_seconds = (
            poll_seconds if poll_seconds is not None else _poll_seconds()
        )

    def run_once(self, *, log: Callable[[str], None] | None = None) -> bool:
        with self.session_factory() as db:
            jobs = _claim_queued(db, self.concurrency)
        if not jobs:
            return False
        if log:
            log(f"SEO: claimed {len(jobs)} job(s)")
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            for future in [executor.submit(_process, job) for job in jobs]:
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001
                    if log:
                        log(f"SEO job crashed: {exc}")
        return True

    def run_forever(
        self,
        *,
        should_stop: Callable[[], bool],
        log: Callable[[str], None] | None = None,
    ) -> None:
        if log:
            log(
                f"SEO content worker started concurrency={self.concurrency} "
                f"poll={self.poll_seconds:g}s"
            )
        while not should_stop():
            try:
                did_work = self.run_once(log=log)
            except Exception as exc:  # noqa: BLE001
                if log:
                    log(f"SEO worker loop error: {exc}")
                did_work = False
            if not did_work:
                time.sleep(self.poll_seconds)


def requeue_stale_running(db: Session, *, older_than_seconds: int = 900) -> int:
    """发版会把跑到一半的单留成孤儿——启动时自愈,不用人来捞。"""
    result = db.execute(
        text(
            f"""
            UPDATE {_TABLE}
            SET status = 'queued', updated_at = now()
            WHERE status = 'running'
              AND started_at < now() - (:secs || ' seconds')::interval
            """
        ),
        {"secs": str(older_than_seconds)},
    )
    db.commit()
    return result.rowcount or 0


__all__ = [
    "SeoGenerationJobWorker",
    "enqueue_seo_jobs",
    "jobs_status",
    "requeue_stale_running",
]
