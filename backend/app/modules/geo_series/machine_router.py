"""Machine endpoints for the GEO publisher — token-authenticated, no session.

n8n cannot hold a console session, so these two routes authenticate with the
one-time job token instead, exactly like the P upload pair. They are mounted both
under the app prefix and bare (see ``main.py``); only the bare mount is reachable
server-to-server, and the session middleware guards the other.

Kept in their own module so the human-facing router never accidentally acquires an
unauthenticated route.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.session import get_db
from ..k_series.product_knowledge.constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_WORKSPACE_KEY,
)
from ..k_series.product_knowledge.scope_shim import KScopeContext
from .content.assemble import assemble_guide_package, cluster_products, load_cluster_items
from .content.backlink_jobs import record_result as backlink_record_result
from .content.models import GeoBacklinkJob, GeoContentCluster, GeoPublishJob
from .content.publish_gate import publish_blockers
from .content.publish_jobs import record_result
from .content.wp_categories import GeoCategoryError, ensure_cluster_category
from .contract.backlink_package import (
    GEO_BACKLINK_PACKAGE_VERSION,
    BacklinkPackage,
    BacklinkTarget,
    BlockPatch,
)
from .contract.publish_package import GuidePackage

router = APIRouter(prefix="/geo", tags=["geo-publish-machine"])


def _callback_base() -> str:
    public = os.getenv("PUBLIC_BASE_URL", "https://ops.barongyekhna.com").rstrip("/")
    return (os.getenv("P_CALLBACK_BASE") or public).rstrip("/")


def _job_scope(job: GeoPublishJob) -> KScopeContext:
    return KScopeContext(
        workspace_key=job.workspace_key or DEFAULT_WORKSPACE_KEY,
        business_context=job.business_context or DEFAULT_BUSINESS_CONTEXT,
        scope_mode=job.scope_mode or "production",
    )


class PublishedItem(BaseModel):
    item_id: str
    wp_post_id: int | None = None
    url: str | None = None


class PublishResultRequest(BaseModel):
    status: str
    published_items: list[PublishedItem] = Field(default_factory=list)
    error: str | None = None


class PublishResultResponse(BaseModel):
    job_id: str
    status: str


@router.get(
    "/clusters/{cluster_id}/publish-package", response_model=GuidePackage
)
def geo_publish_package(
    cluster_id: UUID,
    token: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> GuidePackage:
    """The package n8n publishes. Token must belong to a job for THIS cluster."""
    if not token:
        raise HTTPException(status_code=401, detail="缺少 token。")
    job = db.scalar(
        select(GeoPublishJob).where(
            GeoPublishJob.token == token, GeoPublishJob.cluster_id == cluster_id
        )
    )
    if job is None:
        raise HTTPException(status_code=401, detail="token 无效。")

    scope = _job_scope(job)
    cluster = db.get(GeoContentCluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="话题簇不存在。")

    items = load_cluster_items(db, cluster_id=cluster_id, scope_context=scope)
    products = cluster_products(db, cluster=cluster, scope_context=scope)
    blockers = publish_blockers(
        db, cluster=cluster, items=items, products=products
    )
    if blockers:
        raise HTTPException(
            status_code=409, detail={"ready": False, "blockers": blockers}
        )

    # 死命令(2026-07-29): 指南必须落在谷歌类目里。建不出分类就整单拒发,
    # 绝不退化成"无类目照发"——那会让文章掉在全站结构之外。
    try:
        wp_category_id = ensure_cluster_category(db, cluster=cluster)
    except GeoCategoryError as exc:
        raise HTTPException(
            status_code=409, detail={"ready": False, "blockers": [str(exc)]}
        ) from exc
    return assemble_guide_package(
        db,
        cluster=cluster,
        items=items,
        scope_context=scope,
        job_id=job.job_id,
        wp_category_id=wp_category_id,
    )


@router.post("/publishes/{job_id}/result", response_model=PublishResultResponse)
def geo_publish_result(
    job_id: str,
    payload: PublishResultRequest,
    x_job_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> PublishResultResponse:
    """n8n reports back which posts it created/updated."""
    published: list[dict[str, Any]] = [
        {
            "item_id": entry.item_id,
            "wp_post_id": entry.wp_post_id,
            "url": entry.url,
        }
        for entry in payload.published_items
    ]
    try:
        job = record_result(
            db,
            job_id=job_id,
            token=x_job_token,
            status=payload.status,
            published_items=published,
            error=payload.error,
            public_base=_callback_base(),
        )
    except PermissionError:
        raise HTTPException(status_code=401, detail="job token 无效。") from None
    if job is None:
        raise HTTPException(status_code=404, detail="job 不存在。")
    db.commit()

    # The hub page only lists live articles, so refresh it after a successful run.
    if job.status == "success":
        # 先记下线上真实状态(草稿还是已发布)。published_url 在草稿期就写库了,
        # 不刷这一次,产品页反链就会链到草稿。
        from .content.live_state import refresh_item_live_state_safely

        refresh_item_live_state_safely(db)

        # 新建过的类目要同步进"排除名单",否则指南会挤进 /posts 博客归档。
        from .content.wp_categories import sync_geo_category_exclusions_safely

        sync_geo_category_exclusions_safely(db)

        from .content.guides_index import refresh_guides_index_safely

        refresh_guides_index_safely(db)

    return PublishResultResponse(job_id=job.job_id, status=job.status)


__all__ = ["router"]


# ------------------------------------------------------------------ rail 2
# Product pages linking back to their guides. Same token handshake; the package is
# fully resolved by the console so the workflow only swaps one marked block.


class BacklinkResultEntry(BaseModel):
    product_id: str
    woo_product_id: int | None = None
    updated: bool = False


class BacklinkResultRequest(BaseModel):
    status: str = Field(default="success")
    updated_items: list[BacklinkResultEntry] = Field(default_factory=list)
    error: str | None = None


class BacklinkResultResponse(BaseModel):
    job_id: str
    status: str


@router.get(
    "/backlinks/{job_id}/package",
    response_model=BacklinkPackage,
    response_model_exclude_none=False,
)
def geo_backlink_package(
    job_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> BacklinkPackage:
    """The finished blocks, keyed by live Woo product id."""
    job = db.scalar(
        select(GeoBacklinkJob).where(
            GeoBacklinkJob.job_id == job_id, GeoBacklinkJob.token == token
        )
    )
    if job is None:
        raise HTTPException(status_code=401, detail="token 无效。")

    raw_targets = job.targets_json if isinstance(job.targets_json, list) else []
    targets = [
        BacklinkTarget(
            product_id=t["product_id"],
            sku=t.get("sku"),
            woo_product_id=int(t["woo_product_id"]),
            # 一条 target 带这个产品的全部块——拆开会互相覆盖(契约 v2 文档)。
            blocks=[
                BlockPatch(
                    block_class=str(b.get("block_class") or ""),
                    html=str(b.get("html") or ""),
                )
                for b in (t.get("blocks") or [])
                if isinstance(b, dict) and b.get("block_class")
            ],
            fingerprint=str(t.get("fingerprint") or ""),
            reason=str(t.get("reason") or ""),
        )
        for t in raw_targets
        if isinstance(t, dict) and t.get("product_id") and t.get("woo_product_id")
    ]
    return BacklinkPackage(
        schema_version=GEO_BACKLINK_PACKAGE_VERSION,
        job_id=job.job_id,
        channel="woocommerce",
        generated_at=datetime.now(UTC),
        targets=targets,
    )


@router.post("/backlinks/{job_id}/result", response_model=BacklinkResultResponse)
def geo_backlink_result(
    job_id: str,
    payload: BacklinkResultRequest,
    x_job_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> BacklinkResultResponse:
    """n8n reports which product descriptions it rewrote."""
    updated: list[dict[str, Any]] = [
        {
            "product_id": entry.product_id,
            "woo_product_id": entry.woo_product_id,
            "updated": entry.updated,
        }
        for entry in payload.updated_items
    ]
    try:
        job = backlink_record_result(
            db,
            job_id=job_id,
            token=x_job_token,
            status=payload.status,
            updated_items=updated,
            error=payload.error,
            public_base=_callback_base(),
        )
    except PermissionError:
        raise HTTPException(status_code=401, detail="job token 无效。") from None
    if job is None:
        raise HTTPException(status_code=404, detail="job 不存在。")
    db.commit()
    return BacklinkResultResponse(job_id=job.job_id, status=job.status)
