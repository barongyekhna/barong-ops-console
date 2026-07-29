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

from ...k_series.product_knowledge.scope_shim import KScopeContext
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


def _send_to_n8n(job: GeoBacklinkJob, *, public_base: str) -> None:
    webhook = (os.getenv(N8N_WEBHOOK_ENV) or "").strip()
    if not webhook:
        raise RuntimeError(f"{N8N_WEBHOOK_ENV} 未配置")
    base = (os.getenv("P_CALLBACK_BASE") or public_base).rstrip("/")
    payload = {
        "job_id": job.job_id,
        "channel": job.channel,
        "package_url": f"{base}/geo/backlinks/{job.job_id}/package?token={job.token}",
        "callback_url": f"{base}/geo/backlinks/{job.job_id}/result",
        "token": job.token,
    }
    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(request, timeout=15)


def kick_queue(db: Session, *, public_base: str) -> GeoBacklinkJob | None:
    """Reap stale runs, then release at most one queued job."""
    deadline = _now() - timedelta(minutes=IN_FLIGHT_TIMEOUT_MINUTES)
    stale = (
        db.execute(
            select(GeoBacklinkJob)
            .where(
                GeoBacklinkJob.status == "dispatched",
                GeoBacklinkJob.dispatched_at < deadline,
            )
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    if stale:
        for job in stale:
            job.status = "failed"
            job.error = (
                "n8n 超过 15 分钟未回传，按失联处理（检查 n8n 执行记录后可重试）"
            )
            job.finished_at = _now()
        db.flush()

    in_flight = db.scalar(
        select(GeoBacklinkJob.id).where(GeoBacklinkJob.status == "dispatched").limit(1)
    )
    if in_flight is not None:
        return None

    job = (
        db.execute(
            select(GeoBacklinkJob)
            .where(GeoBacklinkJob.status == "queued")
            .order_by(GeoBacklinkJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .first()
    )
    if job is None:
        return None

    job.status = "dispatched"
    job.dispatched_at = _now()
    db.add(job)
    # Commit BEFORE sending: n8n calls back for the package within milliseconds.
    db.commit()
    try:
        _send_to_n8n(job, public_base=public_base)
    except Exception as exc:  # noqa: BLE001 - a dead webhook must not wedge the queue
        job.status = "failed"
        job.error = f"dispatch failed: {exc}"[:500]
        job.finished_at = _now()
        db.commit()
        return kick_queue(db, public_base=public_base)
    return job


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
    db.commit()
    kick_queue(db, public_base=public_base)
    return job


def jobs_recent(db: Session, *, limit: int = 10) -> list[GeoBacklinkJob]:
    return list(
        db.execute(
            select(GeoBacklinkJob)
            .order_by(GeoBacklinkJob.created_at.desc())
            .limit(limit)
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
