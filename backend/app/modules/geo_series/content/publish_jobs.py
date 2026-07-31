"""Serial publish queue for GEO guide clusters.

A faithful mirror of ``p_series/upload/jobs.py`` — the semantics there were paid
for in production incidents and should not be re-derived:

* **strictly one dispatch in flight**, so n8n is never asked to write two clusters
  to WordPress at once (rate limits, and interleaved runs are unreadable);
* **commit before sending** — n8n fetches the package within milliseconds, so the
  ``dispatched`` row must already be committed or the package GET 401s on an
  unknown token (2026-07-23 race, fixed there, inherited here);
* **15-minute stale reaping**, because a workflow that dies never calls back;
* **terminal-state idempotency**, so a repeated callback is a no-op.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...k_series.product_knowledge.scope_shim import KScopeContext
from .models import GeoContentItem, GeoPublishJob

logger = logging.getLogger(__name__)

N8N_WEBHOOK_ENV = "N8N_GEO_PUBLISH_WEBHOOK"
IN_FLIGHT_TIMEOUT_MINUTES = 15


def _now() -> datetime:
    return datetime.now(UTC)


def enqueue_publish_job(
    db: Session,
    *,
    cluster_id: UUID,
    scope_context: KScopeContext,
    user: Any | None = None,
    channel: str = "wordpress",
) -> GeoPublishJob:
    """Create the row only — never sends."""
    job = GeoPublishJob(
        job_id=uuid4().hex,
        cluster_id=cluster_id,
        channel=channel,
        status="queued",
        token=secrets.token_urlsafe(32),
        requested_by_username=getattr(user, "username", None),
        workspace_key=scope_context.workspace_key,
        business_context=scope_context.business_context,
        scope_mode=scope_context.scope_mode,
    )
    db.add(job)
    db.flush()
    return job


def _send_to_n8n(job: GeoPublishJob, *, public_base: str) -> None:
    webhook = (os.getenv(N8N_WEBHOOK_ENV) or "").strip()
    if not webhook:
        raise RuntimeError(f"{N8N_WEBHOOK_ENV} 未配置")
    base = (os.getenv("P_CALLBACK_BASE") or public_base).rstrip("/")
    payload = {
        "job_id": job.job_id,
        "cluster_id": str(job.cluster_id),
        "channel": job.channel,
        "package_url": (
            f"{base}/geo/clusters/{job.cluster_id}/publish-package?token={job.token}"
        ),
        "callback_url": f"{base}/geo/publishes/{job.job_id}/result",
        "token": job.token,
    }
    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(request, timeout=15)


def kick_queue(db: Session, *, public_base: str) -> GeoPublishJob | None:
    """Reap stale runs, then release at most one queued job. Safe from anywhere."""
    deadline = _now() - timedelta(minutes=IN_FLIGHT_TIMEOUT_MINUTES)
    stale = db.execute(
        select(GeoPublishJob)
        .where(
            GeoPublishJob.status == "dispatched",
            GeoPublishJob.dispatched_at < deadline,
        )
        .with_for_update(skip_locked=True)
    ).scalars().all()
    if stale:
        for job in stale:
            job.status = "failed"
            job.error = (
                "n8n 超过 15 分钟未回传，按失联处理"
                "（检查 n8n 执行记录后可重新发布）"
            )
            job.finished_at = _now()
        db.flush()

    in_flight = db.scalar(
        select(GeoPublishJob.id).where(GeoPublishJob.status == "dispatched").limit(1)
    )
    if in_flight is not None:
        return None

    job = db.execute(
        select(GeoPublishJob)
        .where(GeoPublishJob.status == "queued")
        .order_by(GeoPublishJob.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalars().first()
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


def create_publish_job(
    db: Session,
    *,
    cluster_id: UUID,
    scope_context: KScopeContext,
    user: Any | None,
    public_base: str,
) -> GeoPublishJob:
    job = enqueue_publish_job(
        db, cluster_id=cluster_id, scope_context=scope_context, user=user
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
    published_items: list[dict[str, Any]] | None,
    error: str | None,
    public_base: str = "",
) -> GeoPublishJob | None:
    job = db.scalar(select(GeoPublishJob).where(GeoPublishJob.job_id == job_id))
    if job is None:
        return None
    if not token or token != job.token:
        raise PermissionError("invalid job token")
    # A repeated callback on a finished job is a no-op.
    if job.status in ("success", "failed"):
        return job

    job.status = "success" if status == "success" else "failed"
    job.published_items_json = published_items or []
    job.error = error
    job.finished_at = _now()
    db.flush()

    if job.status == "success":
        _record_published_items(db, published_items or [])
        # 新指南上线 → 相关文章和产品卡片的推荐里立刻多一条。
        from ...content_links.link_push import refresh_link_map_safely

        refresh_link_map_safely(db)

    if public_base:
        try:
            kick_queue(db, public_base=public_base)
        except Exception:  # noqa: BLE001 - reporting this run wins
            logger.exception("GEO publish queue kick failed after callback")
    return job


def _record_published_items(
    db: Session, published_items: list[dict[str, Any]]
) -> None:
    """Stamp each piece with where it now lives, so re-publishing updates in place."""
    now = _now()
    for entry in published_items:
        if not isinstance(entry, dict):
            continue
        raw_id = str(entry.get("item_id") or "").strip()
        if not raw_id:
            continue
        try:
            item = db.get(GeoContentItem, UUID(raw_id))
        except (TypeError, ValueError):
            continue
        if item is None:
            continue
        try:
            post_id = int(entry.get("wp_post_id"))
        except (TypeError, ValueError):
            post_id = None
        if post_id:
            item.wp_post_id = post_id
        url = str(entry.get("url") or "").strip()
        if url:
            item.published_url = url[:2048]
        item.published_at = now
    db.flush()


def jobs_for_cluster(
    db: Session, *, cluster_id: UUID, limit: int = 20
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(GeoPublishJob)
        .where(GeoPublishJob.cluster_id == cluster_id)
        .order_by(GeoPublishJob.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        {
            "job_id": job.job_id,
            "status": job.status,
            "error": job.error,
            "published_items": job.published_items_json or [],
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        }
        for job in rows
    ]


__all__ = [
    "enqueue_publish_job",
    "kick_queue",
    "create_publish_job",
    "record_result",
    "jobs_for_cluster",
    "N8N_WEBHOOK_ENV",
]
