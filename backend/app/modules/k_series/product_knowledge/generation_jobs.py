"""Async, parallel copy / image-brief generation for K product knowledge.

Endpoints enqueue rows into ``k_generation_jobs``; ``KGenerationJobWorker`` polls
the queue and runs the (~80-100s) orchestrator generate methods concurrently in a
thread pool -- so a batch of N products finishes in ~one generation instead of N
serial ones. The generated content lands on the product itself
(marketing_copy_json / image_instruction_json); this queue only tracks lifecycle
so the UI can poll and the operator can review when done.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any
from uuid import UUID, uuid4

from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import text
from sqlalchemy.orm import Session

from ....db.session import SessionLocal
from ....models.user import User
from .scope_shim import KScopeContext
from .workflow_engine import KWorkflowOrchestratorV2

JOB_TYPES = ("marketing_copy", "image_brief")
_TABLE = "k_generation_jobs"


def _worker_concurrency(value: int | None = None) -> int:
    if value is None:
        value = int(os.getenv("K_GENERATION_CONCURRENCY", "5"))
    return max(1, min(value, 16))


def _poll_seconds() -> float:
    return max(1.0, float(os.getenv("K_GENERATION_POLL_SECONDS", "3")))


# --- enqueue + status (called from the request path) -----------------------

def enqueue_generation_jobs(
    db: Session,
    *,
    product_ids: Sequence[UUID],
    job_type: str,
    user: User | None,
    scope_context: KScopeContext,
    batch_id: UUID | None = None,
) -> tuple[UUID, list[dict[str, Any]]]:
    if job_type not in JOB_TYPES:
        raise ValueError(f"unknown_job_type:{job_type}")
    batch_id = batch_id or uuid4()
    created: list[dict[str, Any]] = []
    for product_id in product_ids:
        job_id = uuid4()
        db.execute(
            text(
                f"""
                INSERT INTO {_TABLE}
                    (id, product_id, job_type, status, batch_id,
                     requested_by_username, workspace_key, business_context, scope_mode)
                VALUES
                    (:id, :product_id, :job_type, 'pending', :batch_id,
                     :username, :workspace_key, :business_context, :scope_mode)
                """
            ),
            {
                "id": job_id,
                "product_id": product_id,
                "job_type": job_type,
                "batch_id": batch_id,
                "username": user.username if user is not None else None,
                "workspace_key": scope_context.workspace_key,
                "business_context": scope_context.business_context,
                "scope_mode": scope_context.scope_mode,
            },
        )
        created.append({"job_id": str(job_id), "product_id": str(product_id), "job_type": job_type, "status": "pending"})
    return batch_id, created


def jobs_status(
    db: Session,
    *,
    batch_id: UUID | None = None,
    product_id: UUID | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses = []
    params: dict[str, Any] = {"limit": max(1, min(limit, 500))}
    if batch_id is not None:
        clauses.append("batch_id = :batch_id")
        params["batch_id"] = batch_id
    if product_id is not None:
        clauses.append("product_id = :product_id")
        params["product_id"] = product_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(
        text(
            f"""
            SELECT id, product_id, job_type, status, error, skill_version,
                   started_at, finished_at, created_at
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
            "product_id": str(r["product_id"]),
            "job_type": r["job_type"],
            "status": r["status"],
            "error": r["error"],
            "skill_version": r["skill_version"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
        }
        for r in rows
    ]


# --- worker side -----------------------------------------------------------

def _claim_pending_jobs(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            SELECT id, product_id, job_type, requested_by_username,
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


def _set_job_status(
    job_id: UUID,
    status: str,
    *,
    error: str | None = None,
    skill_version: str | None = None,
) -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                f"""
                UPDATE {_TABLE}
                SET status = :status, error = :error, skill_version = :skill_version,
                    finished_at = now(), updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": job_id, "status": status, "error": error, "skill_version": skill_version},
        )
        db.commit()


def _process_generation_job(job: dict[str, Any]) -> None:
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
            orchestrator = KWorkflowOrchestratorV2(db)
            if job["job_type"] == "marketing_copy":
                product = orchestrator.generate_marketing_copy(
                    product_id=job["product_id"], scope_context=scope, request=None, user=user
                )
                skill_version = product.marketing_copy_skill_version
            else:
                product = orchestrator.generate_image_brief(
                    product_id=job["product_id"], scope_context=scope, request=None, user=user
                )
                skill_version = product.image_instruction_skill_version
            db.commit()
        _set_job_status(job_id, "completed", skill_version=skill_version)
    except Exception as exc:  # noqa: BLE001 - isolate one job's failure
        _set_job_status(job_id, "failed", error=str(exc)[:1000])


class KGenerationJobWorker:
    """Polls k_generation_jobs and runs claimed jobs in a thread pool."""

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
            log(f"K generation: claimed {len(jobs)} job(s), concurrency={self.concurrency}")
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = [executor.submit(_process_generation_job, job) for job in jobs]
            for future in futures:
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001
                    if log:
                        log(f"K generation job crashed: {exc}")
        return True

    def run_forever(
        self,
        *,
        should_stop: Callable[[], bool],
        log: Callable[[str], None] | None = None,
    ) -> None:
        if log:
            log(f"K generation worker started concurrency={self.concurrency} poll={self.poll_seconds:g}s")
        while not should_stop():
            try:
                did_work = self.run_once(log=log)
            except Exception as exc:  # noqa: BLE001
                if log:
                    log(f"K generation worker loop error: {exc}")
                did_work = False
            if not did_work:
                time.sleep(self.poll_seconds)


def requeue_stale_running(db: Session, *, older_than_seconds: int = 900) -> int:
    """Reset jobs stuck in 'running' (e.g. after a worker restart) back to pending."""
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
