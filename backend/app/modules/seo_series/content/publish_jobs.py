"""SEO 文章的串行发布队列。

语义与 GEO / P 完全一致——那套语义是拿生产事故换来的,不重新推导:

* **同一时刻只允许一单在飞**,n8n 不会被要求同时往 WordPress 写两批;
* **先 commit 再发送**,n8n 毫秒级就来取发布包,行没落库会 401;
* **15 分钟收尸**,工作流死了不会自己回调;
* **终态幂等**,重复回调是空操作。

与 GEO 的唯一实质差别:GEO 一单 = 一个话题簇,SEO 一单 = **一批选中的文章**
(它们可能属于不同选题、不同分区)。所以 ``item_ids_json`` 存的是文章 id 列表。
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

from ....services import n8n_dispatch

from ...k_series.product_knowledge.scope_shim import (
    KScopeContext,
    apply_scope_filters,
)
from .models import SeoContentItem, SeoPublishJob

logger = logging.getLogger(__name__)

N8N_WEBHOOK_ENV = "N8N_SEO_PUBLISH_WEBHOOK"
IN_FLIGHT_TIMEOUT_MINUTES = 15


def _now() -> datetime:
    return datetime.now(UTC)


def enqueue_publish_job(
    db: Session,
    *,
    item_ids: list[UUID],
    scope_context: Any,
    user: Any | None = None,
) -> SeoPublishJob:
    job = SeoPublishJob(
        job_id=uuid4().hex,
        token=secrets.token_urlsafe(32),
        channel="wordpress",
        status="queued",
        item_ids_json=[str(i) for i in item_ids],
        requested_by_username=getattr(user, "username", None),
        workspace_key=scope_context.workspace_key,
        business_context=scope_context.business_context,
        scope_mode=scope_context.scope_mode,
    )
    db.add(job)
    db.flush()
    return job


def _build_payload(job: SeoPublishJob, base: str) -> dict[str, object]:
    """这一单发给 n8n 的载荷。传输层在 `services/n8n_dispatch.py`。"""
    return {
        "job_id": job.job_id,
        "channel": job.channel,
        "package_url": f"{base}/seo/publishes/{job.job_id}/package?token={job.token}",
        "callback_url": f"{base}/seo/publishes/{job.job_id}/result",
        "token": job.token,
    }


_QUEUE = n8n_dispatch.QueueSpec(
    model=SeoPublishJob,
    webhook_env=N8N_WEBHOOK_ENV,
    build_payload=_build_payload,
    stale_error="n8n 超过 15 分钟未回传，按失联处理（检查 n8n 执行记录后可重发）",
    in_flight_timeout_minutes=IN_FLIGHT_TIMEOUT_MINUTES,
)

def kick_queue(db: Session, *, public_base: str) -> SeoPublishJob | None:
    """收僵尸，然后在「无 in-flight」时派下一单。

    实现在 `services/n8n_dispatch.py` —— 收口前这套逻辑在五个模块里各有一份，
    四条不变量（收僵尸 / 严格串行 / 先提交再发送 / 失败递归）由
    `tests/backend/test_n8n_queue_contract.py` 行为验证。
    """
    return n8n_dispatch.kick_queue(db, _QUEUE, public_base=public_base)

def create_publish_job(
    db: Session,
    *,
    item_ids: list[UUID],
    scope_context: Any,
    user: Any | None,
    public_base: str,
) -> SeoPublishJob:
    job = enqueue_publish_job(
        db, item_ids=item_ids, scope_context=scope_context, user=user
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
) -> SeoPublishJob | None:
    job = db.scalar(select(SeoPublishJob).where(SeoPublishJob.job_id == job_id))
    if job is None:
        return None
    if not token or token != job.token:
        raise PermissionError("invalid job token")
    if job.status in ("success", "failed"):
        return job  # 重复回调是空操作

    job.status = "success" if status == "success" else "failed"
    job.result_json = {"published_items": published_items or []}
    job.error = error
    job.finished_at = _now()
    db.flush()

    if job.status == "success":
        _record_published_items(db, published_items or [])
        # 新工艺文/博文上线 → 相关文章的推荐里立刻多一条。
        from ...content_links.link_push import refresh_link_map_safely

        refresh_link_map_safely(db)

        # 枢纽从空变成有内容那一刻，导航和主页入口自己长出来——**不用人记得去点**。
        # 这是 2026-08-01 那笔账的根治:工艺文/博文发出去了，但 /guides/、/factory/
        # 全站零入口，有内容的页面没人进得去。
        from ...content_links.site_nav import sync_site_nav_safely

        sync_site_nav_safely(db)

    if public_base:
        try:
            kick_queue(db, public_base=public_base)
        except Exception:  # noqa: BLE001
            logger.exception("SEO publish queue kick failed after callback")
    return job


def _record_published_items(db: Session, published_items: list[dict[str, Any]]) -> None:
    now = _now()
    for entry in published_items:
        if not isinstance(entry, dict):
            continue
        raw_id = str(entry.get("item_id") or "").strip()
        if not raw_id:
            continue
        try:
            item = db.get(SeoContentItem, UUID(raw_id))
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
        # 首推刻意落草稿等人工发布,所以这里**不写 publish**——
        # 真实状态由 live_state 批量刷新回填(published_url 非空 ≠ 线上可见)。
        item.published_at = now
    db.flush()


def jobs_recent(
    db: Session,
    *,
    limit: int = 20,
    scope_context: KScopeContext | None = None,
) -> list[dict[str, Any]]:
    # 只回调用者自己 workspace 的发布流水——跨组织业务数据隔离。
    rows = db.execute(
        apply_scope_filters(select(SeoPublishJob), SeoPublishJob, scope_context)
        .order_by(SeoPublishJob.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        {
            "job_id": job.job_id,
            "status": job.status,
            "error": job.error,
            "item_ids": job.item_ids_json or [],
            "published_items": (job.result_json or {}).get("published_items") or [],
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        }
        for job in rows
    ]


__all__ = [
    "N8N_WEBHOOK_ENV",
    "create_publish_job",
    "enqueue_publish_job",
    "jobs_recent",
    "kick_queue",
    "record_result",
]
