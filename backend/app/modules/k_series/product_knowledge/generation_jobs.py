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

JOB_TYPES = ("marketing_copy", "image_brief", "brand_audit")
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
            if job["job_type"] == "brand_audit":
                skill_version = _run_brand_audit_job(db, job=job, user=user, scope=scope)
                db.commit()
                _set_job_status(job_id, "completed", skill_version=skill_version)
                return
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


def _run_brand_audit_job(
    db: Session,
    *,
    job: dict[str, Any],
    user: User | None,
    scope: KScopeContext,
) -> str:
    """品牌审查 + 自动闭环：检出图像违规（且无文本违规、轮数未耗尽）时自动
    重渲染违规图（带检出位置强化提示），渲染批次收尾会再次入队审查。"""
    from ....modules.notifications.service import create_notification
    from .brand_guard import run_brand_audit
    from .image_render_jobs import enqueue_image_render_jobs
    from .models import KProductKnowledgeProduct

    from .models import KProductKnowledgeMediaAsset

    product = db.get(KProductKnowledgeProduct, job["product_id"])
    if product is None:
        raise RuntimeError("product not found for brand audit")
    prev = product.brand_audit_json if isinstance(product.brand_audit_json, dict) else {}
    attempt = int(prev.get("attempt") or 0)
    audit = run_brand_audit(db, product=product, user=user, attempt=attempt)

    image_violations = audit.get("image_violations") or []
    text_violations = audit.get("text_violations") or []
    rerender_started = False
    if (
        not audit["clean"]
        and image_violations
        and not text_violations
        and not audit.get("errors")
        and attempt < 2
    ):
        # 违规图分两类：position 还在当前作图指令里的 → 重渲染；
        # 不在的（指令改小后残留的孤儿旧图）→ 直接归档，渲染不了它。
        instruction = product.image_instruction_json
        images = (
            instruction.get("images")
            if isinstance(instruction, dict)
            else None
        ) or []
        brief_positions = set()
        for index, spec in enumerate(images, start=1):
            if isinstance(spec, dict):
                try:
                    brief_positions.add(int(spec.get("position") or index))
                except (TypeError, ValueError):
                    brief_positions.add(index)
        hints: dict[int, str] = {}
        orphans_archived = 0
        for violation in image_violations:
            if violation.get("position") is None:
                continue
            position = int(violation["position"])
            if position in brief_positions:
                hints[position] = str(violation.get("finding") or "")
                continue
            asset = db.get(KProductKnowledgeMediaAsset, violation.get("asset_id"))
            if asset is not None:
                asset.status = "removed"
                db.add(asset)
                orphans_archived += 1
        try:
            if hints:
                enqueue_image_render_jobs(
                    db,
                    product=product,
                    user=user,
                    scope_context=scope,
                    positions=sorted(hints.keys()),
                    brand_removal_hints=hints,
                )
                rerender_started = True
            elif orphans_archived:
                # 只清了孤儿没有可渲染的 → 直接补一轮审查（内容已变）
                enqueue_generation_jobs(
                    db,
                    product_ids=[product.id],
                    job_type="brand_audit",
                    user=user,
                    scope_context=scope,
                )
                rerender_started = True
            if rerender_started:
                audit["attempt"] = attempt + 1
                product.brand_audit_json = dict(audit)
                db.add(product)
        except Exception:  # noqa: BLE001 - 渲染在跑等场景；审查结果照常落库
            rerender_started = False

    if audit["clean"]:
        title = f"品牌审查通过：{product.sku or product.product_key}"
        level = "success"
        body = None
    elif rerender_started:
        title = f"品牌审查检出图像品牌标识，已自动重渲染 {len(image_violations)} 张图"
        level = "warning"
        body = "; ".join(
            f"第{violation.get('position')}张: {str(violation.get('finding'))[:80]}"
            for violation in image_violations
        )
    else:
        title = f"品牌审查未通过：{product.sku or product.product_key}"
        level = "error"
        body = "; ".join(
            [
                f"{violation.get('term')}({violation.get('surface')})"
                for violation in text_violations[:6]
            ]
            + [
                f"第{violation.get('position')}张图有品牌标识"
                for violation in image_violations[:6]
            ]
            + ([f"{len(audit['errors'])} 步审查失败(fail-closed)"] if audit.get("errors") else [])
        )
    try:
        create_notification(
            db,
            event_type="k.brand_audit.finished",
            title=title,
            body=body,
            level=level,
            source="k.brand_guard",
            product_id=product.id,
            payload={
                "clean": audit["clean"],
                "text_violations": len(text_violations),
                "image_violations": len(image_violations),
                "attempt": audit.get("attempt"),
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return "brand-guard-v1"


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
