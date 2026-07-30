"""产品页 B2B 小窗的串行派单队列。

`geo_series/content/backlink_jobs.py` 的忠实镜像——那套语义是生产事故换来
的,这里不重新推导:

1. **同时最多一单在飞**
2. **发 webhook 前必须先 commit**——n8n 毫秒级回来拉包,没提交它拿到的
   token 查不到行,直接 401
3. **15 分钟没回报按失联处理**,否则一单卡死整个队列
4. **回调对终态幂等**——n8n 重试不该把成功改成失败

爆炸半径刻意做小:只在已存在的 Woo 产品上写一个 `_kp_b2b` meta。永不建
产品、永不改价、永不碰图片、永不动描述。
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

from .models import B2BWidgetJob

logger = logging.getLogger(__name__)

N8N_WEBHOOK_ENV = "N8N_B2B_WIDGET_WEBHOOK"
IN_FLIGHT_TIMEOUT_MINUTES = 15


def _now() -> datetime:
    return datetime.now(UTC)


def enqueue_widget_job(
    db: Session,
    *,
    targets: list[dict[str, Any]],
    user: Any | None = None,
    channel: str = "woocommerce",
) -> B2BWidgetJob:
    """只建行,永不发送。发送统一由 kick_queue 决定,保证串行。"""
    job = B2BWidgetJob(
        job_id=uuid4().hex,
        channel=channel,
        status="queued",
        token=secrets.token_urlsafe(32),
        targets_json=targets,
        requested_by_username=getattr(user, "username", None),
    )
    db.add(job)
    db.flush()
    return job


def _send_to_n8n(job: B2BWidgetJob, *, public_base: str) -> None:
    webhook = (os.getenv(N8N_WEBHOOK_ENV) or "").strip()
    if not webhook:
        raise RuntimeError(f"{N8N_WEBHOOK_ENV} 未配置")
    # P_CALLBACK_BASE 是容器内主机名,n8n → 控制台不出网、不过 nginx。
    base = (os.getenv("P_CALLBACK_BASE") or public_base).rstrip("/")
    payload = {
        "job_id": job.job_id,
        "channel": job.channel,
        "package_url": f"{base}/b2b/widget-jobs/{job.job_id}/package?token={job.token}",
        "callback_url": f"{base}/b2b/widget-jobs/{job.job_id}/result",
        "token": job.token,
    }
    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(request, timeout=15)


def kick_queue(db: Session, *, public_base: str) -> B2BWidgetJob | None:
    """收割僵尸任务,然后最多放行一单。"""
    deadline = _now() - timedelta(minutes=IN_FLIGHT_TIMEOUT_MINUTES)
    stale = (
        db.execute(
            select(B2BWidgetJob)
            .where(
                B2BWidgetJob.status == "dispatched",
                B2BWidgetJob.dispatched_at < deadline,
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
        select(B2BWidgetJob.id).where(B2BWidgetJob.status == "dispatched").limit(1)
    )
    if in_flight is not None:
        return None

    job = (
        db.execute(
            select(B2BWidgetJob)
            .where(B2BWidgetJob.status == "queued")
            .order_by(B2BWidgetJob.created_at.asc())
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
    # Commit BEFORE sending: n8n 毫秒级回来拉包,没提交就查不到这一行。
    db.commit()
    try:
        _send_to_n8n(job, public_base=public_base)
    except Exception as exc:  # noqa: BLE001 - 死掉的 webhook 不许把队列卡死
        job.status = "failed"
        job.error = f"dispatch failed: {exc}"[:500]
        job.finished_at = _now()
        db.commit()
        return kick_queue(db, public_base=public_base)
    return job


def create_widget_job(
    db: Session,
    *,
    targets: list[dict[str, Any]],
    user: Any | None,
    public_base: str,
) -> B2BWidgetJob:
    job = enqueue_widget_job(db, targets=targets, user=user)
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
) -> B2BWidgetJob | None:
    job = db.scalar(select(B2BWidgetJob).where(B2BWidgetJob.job_id == job_id))
    if job is None:
        return None
    if not token or token != job.token:
        raise PermissionError("invalid job token")
    # 终态上的重复回调是 no-op:n8n 重试不该把成功改成失败。
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


def jobs_recent(db: Session, *, limit: int = 10) -> list[B2BWidgetJob]:
    return list(
        db.execute(
            select(B2BWidgetJob).order_by(B2BWidgetJob.created_at.desc()).limit(limit)
        )
        .scalars()
        .all()
    )


__all__ = [
    "IN_FLIGHT_TIMEOUT_MINUTES",
    "N8N_WEBHOOK_ENV",
    "create_widget_job",
    "enqueue_widget_job",
    "jobs_recent",
    "kick_queue",
    "record_result",
]
