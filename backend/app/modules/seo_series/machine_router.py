"""SEO 发布的机器端点——token 鉴权,不走会话。

n8n 拿不到控制台会话,所以这两条路由用一次性任务令牌鉴权(和 P/GEO 完全同规)。
单独一个模块,免得人面向的 router 哪天不小心多出一条免鉴权路由。
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.session import get_db
from .content.models import SeoContentItem, SeoPublishJob

router = APIRouter(prefix="/seo", tags=["seo-publish-machine"])


def _callback_base() -> str:
    public = os.getenv("PUBLIC_BASE_URL", "https://ops.barongyekhna.com").rstrip("/")
    return (os.getenv("P_CALLBACK_BASE") or public).rstrip("/")


def _require_job(db: Session, job_id: str, token: str) -> SeoPublishJob:
    job = db.scalar(select(SeoPublishJob).where(SeoPublishJob.job_id == job_id))
    if job is None or not token or token != job.token:
        # 不区分"任务不存在"和"令牌不对"——对外一律 401,不泄漏哪个任务存在。
        raise HTTPException(status_code=401, detail="invalid job token")
    return job


@router.get("/publishes/{job_id}/package")
def publish_package(
    job_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """n8n 取发布包。分类拿不到 → 整单失败,**绝不发成无类目**。"""
    from .content.assemble import assemble_seo_package
    from .content.wp_terms import SeoCategoryError

    job = _require_job(db, job_id, token)
    item_ids: list[UUID] = []
    for raw in job.item_ids_json or []:
        try:
            item_ids.append(UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    items = [
        item
        for item in (db.get(SeoContentItem, i) for i in item_ids)
        if item is not None and item.review_status == "approved"
    ]
    if not items:
        raise HTTPException(status_code=409, detail="这一单里没有已批准的文章。")
    try:
        return assemble_seo_package(db, items=items, job_id=job.job_id)
    except SeoCategoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class PublishedItem(BaseModel):
    item_id: str
    wp_post_id: int | None = None
    url: str | None = None


class PublishResultIn(BaseModel):
    status: str = "success"
    published_items: list[PublishedItem] = Field(default_factory=list)
    error: str | None = None


@router.post("/publishes/{job_id}/result")
def publish_result(
    job_id: str,
    payload: PublishResultIn,
    token: str = Query(default=""),
    x_job_token: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from .content.publish_jobs import record_result

    supplied = (token or x_job_token or "").strip()
    try:
        job = record_result(
            db,
            job_id=job_id,
            token=supplied,
            status=payload.status,
            published_items=[p.model_dump() for p in payload.published_items],
            error=payload.error,
            public_base=_callback_base(),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="invalid job token") from exc
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    db.commit()
    return {"job_id": job.job_id, "status": job.status}


__all__ = ["router"]
