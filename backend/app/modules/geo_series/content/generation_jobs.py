"""Standalone GEO content generation queue (drained by the geo-worker).

Mirrors ``k_series...generation_jobs`` (pending → running → completed/failed,
``FOR UPDATE SKIP LOCKED`` claim, thread-pool run loop, stale-running requeue),
but is fully decoupled from the k-worker: its own table, worker class, and
container.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from ....db.session import SessionLocal
from ....models.user import User
from ...k_series.product_knowledge.scope_shim import KScopeContext
from .constants import JOB_TYPE_CONTENT
from .orchestrator import GeoContentOrchestrator

logger = logging.getLogger(__name__)

_TABLE = "geo_generation_jobs"


def _worker_concurrency(value: int | None = None) -> int:
    if value is not None:
        return max(1, value)
    raw = os.getenv("GEO_GENERATION_CONCURRENCY", "2")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 2


def _poll_seconds() -> float:
    raw = os.getenv("GEO_GENERATION_POLL_SECONDS", "3")
    try:
        return max(0.5, float(raw))
    except (TypeError, ValueError):
        return 3.0


# --- enqueue / status -------------------------------------------------------

def enqueue_geo_jobs(
    db: Session,
    *,
    cluster_ids: Sequence[UUID],
    user: User | None,
    scope_context: KScopeContext,
    batch_id: UUID | None = None,
) -> tuple[UUID, list[dict[str, Any]]]:
    batch_id = batch_id or uuid4()
    username = getattr(user, "username", None)
    created: list[dict[str, Any]] = []
    for cluster_id in cluster_ids:
        job_id = uuid4()
        db.execute(
            text(
                f"""
                INSERT INTO {_TABLE}
                    (id, cluster_id, job_type, status, batch_id,
                     requested_by_username, workspace_key, business_context, scope_mode)
                VALUES
                    (:id, :cluster_id, :job_type, 'pending', :batch_id,
                     :username, :workspace_key, :business_context, :scope_mode)
                """
            ),
            {
                "id": job_id,
                "cluster_id": cluster_id,
                "job_type": JOB_TYPE_CONTENT,
                "batch_id": batch_id,
                "username": username,
                "workspace_key": scope_context.workspace_key,
                "business_context": scope_context.business_context,
                "scope_mode": scope_context.scope_mode,
            },
        )
        created.append({"job_id": str(job_id), "cluster_id": str(cluster_id)})
    return batch_id, created


def jobs_status(
    db: Session, *, cluster_id: UUID | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    where = "WHERE cluster_id = :cluster_id" if cluster_id is not None else ""
    params: dict[str, Any] = {"limit": limit}
    if cluster_id is not None:
        params["cluster_id"] = cluster_id
    rows = db.execute(
        text(
            f"""
            SELECT id, cluster_id, job_type, status, error, started_at, finished_at
            FROM {_TABLE}
            {where}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [
        {
            "job_id": str(r["id"]),
            "cluster_id": str(r["cluster_id"]),
            "job_type": r["job_type"],
            "status": r["status"],
            "error": r["error"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
        }
        for r in rows
    ]


# --- worker side ------------------------------------------------------------

def _claim_pending_jobs(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            SELECT id, cluster_id, requested_by_username,
                   workspace_key, business_context, scope_mode
            FROM {_TABLE}
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"limit": limit},
    ).mappings().all()
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    db.execute(
        text(
            f"""
            UPDATE {_TABLE}
            SET status = 'running', started_at = now(), attempts = attempts + 1,
                updated_at = now()
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": ids},
    )
    db.commit()
    return [dict(r) for r in rows]


def _set_job_status(job_id: Any, status: str, *, error: str | None = None) -> None:
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


def _reset_cluster_after_failure(cluster_id: Any) -> None:
    """A failed generation must not strand the cluster in 'generating'."""
    try:
        with SessionLocal() as db:
            db.execute(
                text(
                    "UPDATE geo_content_clusters SET status = 'draft', "
                    "updated_at = now() WHERE id = :id AND status = 'generating'"
                ),
                {"id": cluster_id},
            )
            db.commit()
    except Exception:  # noqa: BLE001 - best-effort recovery
        logger.exception("failed to reset cluster status after job failure")


def _process_geo_job(job: dict[str, Any]) -> None:
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
            GeoContentOrchestrator(db).generate_cluster(
                cluster_id=job["cluster_id"], scope_context=scope, user=user
            )
            db.commit()
        _set_job_status(job_id, "completed")
    except Exception as exc:  # noqa: BLE001 - isolate one job's failure
        _reset_cluster_after_failure(job.get("cluster_id"))
        _set_job_status(job_id, "failed", error=str(exc)[:1000])


class GeoGenerationJobWorker:
    """Polls geo_generation_jobs and runs claimed jobs in a thread pool."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        concurrency: int | None = None,
        poll_seconds: float | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.concurrency = _worker_concurrency(concurrency)
        self.poll_seconds = poll_seconds if poll_seconds is not None else _poll_seconds()

    def run_once(self, *, log: Callable[[str], None] | None = None) -> bool:
        with self.session_factory() as db:
            jobs = _claim_pending_jobs(db, self.concurrency)
        if not jobs:
            return False
        if log:
            log(f"GEO content: claimed {len(jobs)} job(s), concurrency={self.concurrency}")
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = [executor.submit(_process_geo_job, job) for job in jobs]
            for future in futures:
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001
                    if log:
                        log(f"GEO content job crashed: {exc}")
        return True

    def run_forever(
        self,
        *,
        should_stop: Callable[[], bool],
        log: Callable[[str], None] | None = None,
    ) -> None:
        if log:
            log(
                f"GEO content worker started concurrency={self.concurrency} "
                f"poll={self.poll_seconds:g}s"
            )
        while not should_stop():
            try:
                did_work = self.run_once(log=log)
            except Exception as exc:  # noqa: BLE001
                if log:
                    log(f"GEO content worker loop error: {exc}")
                did_work = False
            if not did_work:
                time.sleep(self.poll_seconds)


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
    )
    db.commit()
    return result.rowcount or 0


__all__ = [
    "enqueue_geo_jobs",
    "jobs_status",
    "GeoGenerationJobWorker",
    "requeue_stale_running",
]
