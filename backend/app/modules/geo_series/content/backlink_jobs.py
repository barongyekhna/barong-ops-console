"""Serial queue for the product-page backlink refresh (rail 2).

A faithful mirror of ``publish_jobs`` — which is itself a mirror of
``p_series/upload/jobs.py``. The semantics there were paid for in production
incidents and are not re-derived here: one dispatch in flight, **commit before
send** (n8n fetches the package within milliseconds), 15-minute stale reaping,
terminal-state idempotency.

What is different is the blast radius, deliberately: this workflow writes exactly
one Woo field (``description``) on products that already exist. It never creates,
never prices, never touches images.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....services import n8n_dispatch

from ...k_series.product_knowledge.scope_shim import (
    KScopeContext,
    apply_scope_filters,
)
from .models import GeoBacklinkJob

logger = logging.getLogger(__name__)

N8N_WEBHOOK_ENV = "N8N_GEO_BACKLINK_WEBHOOK"
IN_FLIGHT_TIMEOUT_MINUTES = 15


def _now() -> datetime:
    return datetime.now(UTC)


def enqueue_backlink_job(
    db: Session,
    *,
    scope_context: KScopeContext,
    targets: list[dict[str, Any]],
    user: Any | None = None,
    channel: str = "woocommerce",
) -> GeoBacklinkJob:
    """Create the row only — never sends."""
    job = GeoBacklinkJob(
        job_id=uuid4().hex,
        channel=channel,
        status="queued",
        token=secrets.token_urlsafe(32),
        targets_json=targets,
        requested_by_username=getattr(user, "username", None),
        workspace_key=scope_context.workspace_key,
        business_context=scope_context.business_context,
        scope_mode=scope_context.scope_mode,
    )
    db.add(job)
    db.flush()
    return job


def _build_payload(job: GeoBacklinkJob, base: str) -> dict[str, object]:
    """这一单发给 n8n 的载荷。传输层在 `services/n8n_dispatch.py`。"""
    return {
        "job_id": job.job_id,
        "channel": job.channel,
        "package_url": f"{base}/geo/backlinks/{job.job_id}/package?token={job.token}",
        "callback_url": f"{base}/geo/backlinks/{job.job_id}/result",
        "token": job.token,
    }


_QUEUE = n8n_dispatch.QueueSpec(
    model=GeoBacklinkJob,
    webhook_env=N8N_WEBHOOK_ENV,
    build_payload=_build_payload,
    stale_error="n8n 超过 15 分钟未回传，按失联处理（检查 n8n 执行记录后可重试）",
    in_flight_timeout_minutes=IN_FLIGHT_TIMEOUT_MINUTES,
)

def kick_queue(db: Session, *, public_base: str) -> GeoBacklinkJob | None:
    """收僵尸，然后在「无 in-flight」时派下一单。

    实现在 `services/n8n_dispatch.py` —— 收口前这套逻辑在五个模块里各有一份，
    四条不变量（收僵尸 / 严格串行 / 先提交再发送 / 失败递归）由
    `tests/backend/test_n8n_queue_contract.py` 行为验证。
    """
    return n8n_dispatch.kick_queue(db, _QUEUE, public_base=public_base)

def create_backlink_job(
    db: Session,
    *,
    scope_context: KScopeContext,
    targets: list[dict[str, Any]],
    user: Any | None,
    public_base: str,
) -> GeoBacklinkJob:
    job = enqueue_backlink_job(
        db, scope_context=scope_context, targets=targets, user=user
    )
    kick_queue(db, public_base=public_base)
    db.refresh(job)
    return job


def record_result(
    db: Session,
    *,
    job_id: str,
    token: str | None,
    status: str,
    updated_items: list[dict[str, Any]] | None,
    error: str | None,
    public_base: str = "",
) -> GeoBacklinkJob | None:
    job = db.scalar(select(GeoBacklinkJob).where(GeoBacklinkJob.job_id == job_id))
    if job is None:
        return None
    if not token or token != job.token:
        raise PermissionError("invalid job token")
    # A repeated callback on a finished job is a no-op.
    if job.status in {"success", "failed"}:
        return job

    job.status = "success" if status == "success" else "failed"
    job.updated_items_json = updated_items or []
    job.error = (error or None) if job.status == "failed" else None
    job.finished_at = _now()
    db.add(job)

    if job.status == "success":
        # 落指纹:下次收集目标时零 WP 调用就能算出"哪些产品页过期了"。
        # **updated: false 也要写**——那说明线上本来就是这个状态。
        try:
            from .backlink_targets import write_fingerprints

            by_product = {
                str(t.get("product_id")): str(t.get("fingerprint") or "")
                for t in (job.targets_json or [])
                if isinstance(t, dict) and t.get("fingerprint")
            }
            updates: dict[str, str] = {}
            for row in updated_items or []:
                if not isinstance(row, dict):
                    continue
                woo_id = str(row.get("woo_product_id") or "").strip()
                fingerprint = str(row.get("fingerprint") or "") or by_product.get(
                    str(row.get("product_id")), ""
                )
                if woo_id and fingerprint:
                    updates[woo_id] = fingerprint
            write_fingerprints(db, updates)
        except Exception:  # noqa: BLE001 - 台账记不上不该毁掉这次回报
            logger.exception("backlink fingerprint write failed")

    db.commit()
    kick_queue(db, public_base=public_base)
    return job


def jobs_recent(
    db: Session,
    *,
    limit: int = 10,
    scope_context: KScopeContext | None = None,
) -> list[GeoBacklinkJob]:
    # 只回调用者自己 workspace 的派单流水——绝不把别的组织的作业泄漏出去。
    query = apply_scope_filters(select(GeoBacklinkJob), GeoBacklinkJob, scope_context)
    return list(
        db.execute(
            query.order_by(GeoBacklinkJob.created_at.desc()).limit(limit)
        )
        .scalars()
        .all()
    )


__all__ = [
    "N8N_WEBHOOK_ENV",
    "create_backlink_job",
    "enqueue_backlink_job",
    "jobs_recent",
    "kick_queue",
    "record_result",
]
