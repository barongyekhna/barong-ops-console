"""SEO 内容引擎控制台 API——本期只有工艺事实库。

事实库本体在 ``content_core.facts``(共享给 GEO/B2B),这里是它的人工入口:
列表 / 新增 / 编辑 / 批准 / 停用 / 版本历史 / **需复核清单**。

权限与 P/F/GEO 同规:owner / super_admin 直通,否则要有对应 ``seo.content.*``;
execute / manage 蕴含 read。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.roles import is_super_admin_role
from ...db.session import get_db
from ...models.user import User
from ...services.permission_service import resolve_current_user_permission_info
from ..content_core.facts import service as facts
from ..content_core.facts.models import CraftFact, CraftFactRevision
from ..k_series.product_knowledge.constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_WORKSPACE_KEY,
)
from ..k_series.product_knowledge.scope_shim import KScopeContext

router = APIRouter(prefix="/seo", tags=["seo-content"])

_IMPLIED_BY = {
    "seo.content.read": ("seo.content.read", "seo.content.execute", "seo.content.manage"),
    "seo.content.execute": ("seo.content.execute", "seo.content.manage"),
    "seo.content.manage": ("seo.content.manage",),
}


def _require_seo_permission(permission_key: str):
    """owner / super_admin 直通;execute / manage 蕴含 read。"""

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        permissions = resolve_current_user_permission_info(db, user, request=request)
        if (
            permissions.is_owner_full_access
            or is_super_admin_role(getattr(user, "role", None))
            or set(_IMPLIED_BY[permission_key]).intersection(
                permissions.permission_keys
            )
        ):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"缺少权限 {permission_key}。",
        )

    return dependency


def _scope(request: Request | None) -> KScopeContext:
    """与 GEO 同一套 scope 推导,好让两边写出来的行落在同一个工作区。"""
    org_id = None
    if request is not None:
        org_id = getattr(request.state, "org_id", None)
        if org_id is None:
            org_context = getattr(request.state, "org_context", None)
            org_id = getattr(org_context, "org_id", None)
    return KScopeContext(
        workspace_key=str(org_id).strip() if org_id else DEFAULT_WORKSPACE_KEY,
        business_context=DEFAULT_BUSINESS_CONTEXT,
        scope_mode="production",
    )


class FactIn(BaseModel):
    topic: str = Field(min_length=1, max_length=64)
    claim: str = Field(min_length=1)
    detail: str | None = None
    value: str | None = None
    unit: str | None = None
    basis: str | None = None
    product_ids: list[str] | None = None


class FactPatch(BaseModel):
    topic: str | None = None
    claim: str | None = None
    detail: str | None = None
    value: str | None = None
    unit: str | None = None
    basis: str | None = None
    product_ids: list[str] | None = None
    change_reason: str | None = None


def _serialize(fact: CraftFact) -> dict[str, Any]:
    return {
        "id": str(fact.id),
        "topic": fact.topic,
        "claim": fact.claim,
        "detail": fact.detail,
        "value": fact.value,
        "unit": fact.unit,
        "basis": fact.basis,
        "status": fact.status,
        "version": fact.version,
        "product_ids": fact.product_ids_json or [],
        "approved_at": fact.approved_at.isoformat() if fact.approved_at else None,
        "updated_at": fact.updated_at.isoformat() if fact.updated_at else None,
    }


@router.get("/facts")
def list_facts(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.read")),
) -> dict[str, Any]:
    """全部事实 + 需复核清单。

    ``stale`` 是这套设计的意义所在:工艺一改,引用旧版的内容立刻在这里显形——
    **过期的真话和编造一样有害**,而且没有任何输出护栏会报警。
    """
    from sqlalchemy import select

    from ..k_series.product_knowledge.scope_shim import apply_scope_filters

    query = apply_scope_filters(select(CraftFact), CraftFact, _scope(request))
    rows = list(
        db.execute(query.order_by(CraftFact.topic, CraftFact.created_at)).scalars()
    )
    return {
        "facts": [_serialize(f) for f in rows],
        "topics": sorted({f.topic for f in rows}),
        "approved_count": sum(1 for f in rows if f.status == "approved"),
        "stale": facts.stale_content(db),
    }


@router.post("/facts", status_code=status.HTTP_201_CREATED)
def create_fact(
    request: Request,
    payload: FactIn,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.manage")),
) -> dict[str, Any]:
    try:
        fact = facts.create_fact(
            db,
            topic=payload.topic,
            claim=payload.claim,
            detail=payload.detail,
            value=payload.value,
            unit=payload.unit,
            basis=payload.basis,
            product_ids=payload.product_ids,
            scope_context=_scope(request),
            user=user,
        )
    except facts.CraftFactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return _serialize(fact)


@router.patch("/facts/{fact_id}")
def update_fact(
    fact_id: UUID,
    payload: FactPatch,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.manage")),
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_none=True)
    reason = changes.pop("change_reason", None)
    if "product_ids" in changes:
        changes["product_ids_json"] = changes.pop("product_ids")
    try:
        fact, bumped = facts.update_fact(
            db, fact_id=fact_id, changes=changes, change_reason=reason, user=user
        )
    except facts.CraftFactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return {
        **_serialize(fact),
        "version_bumped": bumped,
        # 实质修改会退回 draft,这句是给前端提示用户「改完要重新批准」。
        "note": (
            "实质内容已变更，版本升至 v%d 并退回待批准。"
            "引用旧版的内容已进入需复核清单。" % fact.version
        )
        if bumped
        else None,
    }


@router.post("/facts/{fact_id}/approve")
def approve_fact(
    fact_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.manage")),
) -> dict[str, Any]:
    try:
        fact = facts.approve_fact(db, fact_id=fact_id, user=user)
    except facts.CraftFactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return _serialize(fact)


@router.post("/facts/{fact_id}/retire")
def retire_fact(
    fact_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.manage")),
) -> dict[str, Any]:
    """停用一条事实——不删除,因为已发布内容还引用着它,历史要查得到。"""
    fact = db.get(CraftFact, fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="这条工艺事实不存在。")
    fact.status = "retired"
    db.commit()
    return _serialize(fact)


@router.get("/facts/{fact_id}/revisions")
def fact_revisions(
    fact_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.read")),
) -> dict[str, Any]:
    from sqlalchemy import select

    rows = list(
        db.execute(
            select(CraftFactRevision)
            .where(CraftFactRevision.fact_id == fact_id)
            .order_by(CraftFactRevision.version.desc())
        ).scalars()
    )
    return {
        "revisions": [
            {
                "version": r.version,
                "snapshot": r.snapshot_json or {},
                "change_reason": r.change_reason,
                "changed_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }




# ============================================================ 选题（关键词雷达）


class RadarRunIn(BaseModel):
    extra_keywords: list[str] = Field(default_factory=list)


@router.get("/topics")
def list_topics(
    request: Request,
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.read")),
) -> dict[str, Any]:
    """选题队列。按分数倒序——分数已经把"有没有事实支撑"算进去了。"""
    from sqlalchemy import select

    from .content.models import SeoRadarRun, SeoTopic

    query = select(SeoTopic)
    if status_filter:
        query = query.where(SeoTopic.status == status_filter)
    rows = list(
        db.execute(query.order_by(SeoTopic.score.desc(), SeoTopic.created_at)).scalars()
    )
    last_run = db.execute(
        select(SeoRadarRun).order_by(SeoRadarRun.created_at.desc()).limit(1)
    ).scalars().first()
    return {
        "topics": [
            {
                "id": str(t.id),
                "keyword": t.keyword,
                "source": t.source,
                "audience": t.audience,
                "destination": t.destination,
                "category_path": t.category_path,
                "store_type_key": t.store_type_key,
                "craft_topic": t.craft_topic,
                "avg_monthly_searches": t.avg_monthly_searches,
                "attackability": t.attackability,
                "terrain": t.terrain,
                "fact_support": t.fact_support_json or {},
                "score": t.score,
                "status": t.status,
                "geo_reason": t.geo_reason,
            }
            for t in rows
        ],
        "last_run": (
            {
                "status": last_run.status,
                "seed_count": last_run.seed_count,
                "planner_calls": last_run.planner_calls,
                "candidate_count": last_run.candidate_count,
                "geo_blocked_count": last_run.geo_blocked_count,
                "notes": last_run.notes_json or {},
                "finished_at": (
                    last_run.finished_at.isoformat() if last_run.finished_at else None
                ),
            }
            if last_run
            else None
        ),
    }


@router.post("/topics/radar")
def run_radar_endpoint(
    request: Request,
    payload: RadarRunIn,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.execute")),
) -> dict[str, Any]:
    from .content.topic_radar import SeoRadarError, run_radar

    try:
        run = run_radar(
            db,
            scope_context=_scope(request),
            extra_keywords=payload.extra_keywords,
            username=getattr(user, "username", None),
        )
    except SeoRadarError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": run.status,
        "seed_count": run.seed_count,
        "planner_calls": run.planner_calls,
        "candidate_count": run.candidate_count,
        "geo_blocked_count": run.geo_blocked_count,
        "notes": run.notes_json or {},
    }


@router.post("/topics/{topic_id}/terrain")
def probe_topic_terrain(
    request: Request,
    topic_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.execute")),
) -> dict[str, Any]:
    """给单个选题打可攻度（一发 Serper，走 GEO 的台账）。"""
    from .content.topic_radar import SeoRadarError, attach_terrain

    try:
        topic = attach_terrain(
            db, topic_id=topic_id, scope_context=_scope(request), user=user
        )
    except SeoRadarError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "attackability": topic.attackability,
        "terrain": topic.terrain,
        "score": topic.score,
    }


class TopicPatch(BaseModel):
    status: str
    rejected_reason: str | None = None


@router.patch("/topics/{topic_id}")
def update_topic(
    topic_id: UUID,
    payload: TopicPatch,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.manage")),
) -> dict[str, Any]:
    from .content import constants as C
    from .content.models import SeoTopic

    if payload.status not in C.TOPIC_STATUSES:
        raise HTTPException(status_code=400, detail=f"未知状态 {payload.status}。")
    topic = db.get(SeoTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="这个选题不存在。")
    topic.status = payload.status
    topic.rejected_reason = payload.rejected_reason
    if payload.status == "picked":
        topic.picked_by_user_id = getattr(user, "id", None)
    db.commit()
    return {"id": str(topic.id), "status": topic.status}


# ============================================================ 内容


@router.post("/topics/{topic_id}/generate")
def generate_article(
    request: Request,
    topic_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.execute")),
) -> dict[str, Any]:
    """排队生成。真正的生成在 seo-worker 里跑（AI 调用一分钟起步）。"""
    from ..k_series.product_knowledge.scope_shim import KScopeContext
    from .content.generation_jobs import enqueue_seo_jobs
    from .content.models import SeoTopic

    topic = db.get(SeoTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="这个选题不存在。")
    scope = _scope(request)
    created = enqueue_seo_jobs(
        db,
        topic_ids=[topic_id],
        user=user,
        scope_context=KScopeContext(
            workspace_key=scope.workspace_key,
            business_context=scope.business_context,
            scope_mode=scope.scope_mode,
        ),
    )
    if topic.status == "candidate":
        topic.status = "picked"
    db.commit()
    return {"queued": created}


@router.get("/items")
def list_items(
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.read")),
) -> dict[str, Any]:
    from sqlalchemy import select

    from .content.generation_jobs import jobs_status
    from .content.models import SeoContentItem, SeoTopic

    rows = list(
        db.execute(
            select(SeoContentItem).order_by(SeoContentItem.created_at.desc())
        ).scalars()
    )
    topics = {
        t.id: t for t in db.execute(select(SeoTopic)).scalars()
    }
    return {
        "items": [
            {
                "id": str(i.id),
                "topic": getattr(topics.get(i.topic_id), "keyword", None),
                "item_kind": i.item_kind,
                "destination": i.destination,
                "title": i.title,
                "sections": (i.body_json or {}).get("sections") or [],
                "seo": i.seo_json or {},
                "links": i.links_json or {},
                "brand_audit": i.brand_audit_json or {},
                "analysis": i.analysis_json or {},
                "revision": i.revision_json or {},
                "review_status": i.review_status,
                "wp_post_id": i.wp_post_id,
                "wp_status": i.wp_status,
                "published_url": i.published_url,
            }
            for i in rows
        ],
        "jobs": jobs_status(db),
    }


class ReviewIn(BaseModel):
    review_status: str


@router.post("/items/{item_id}/review")
def review_item(
    item_id: UUID,
    payload: ReviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.manage")),
) -> dict[str, Any]:
    from .content.models import SeoContentItem

    if payload.review_status not in ("pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="未知审核状态。")
    item = db.get(SeoContentItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="这篇不存在。")
    audit = item.brand_audit_json or {}
    if payload.review_status == "approved" and not audit.get("clean", True):
        raise HTTPException(
            status_code=409,
            detail="这篇没过品牌/接地审查，不能批准。先按批评重写。",
        )
    item.review_status = payload.review_status
    db.commit()
    return {"id": str(item.id), "review_status": item.review_status}


@router.post("/items/{item_id}/revise")
def revise_item(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.execute")),
) -> dict[str, Any]:
    from ..k_series.product_knowledge.scope_shim import KScopeContext
    from .content.generation_jobs import enqueue_seo_jobs

    scope = _scope(request)
    created = enqueue_seo_jobs(
        db,
        topic_ids=[item_id],  # revise 任务里这一列存的是 item_id
        user=user,
        scope_context=KScopeContext(
            workspace_key=scope.workspace_key,
            business_context=scope.business_context,
            scope_mode=scope.scope_mode,
        ),
        job_kind="revise",
    )
    db.commit()
    return {"queued": created}


# ============================================================ 发布


class PublishIn(BaseModel):
    item_ids: list[UUID]


@router.post("/publishes")
def create_publish(
    request: Request,
    payload: PublishIn,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.manage")),
) -> dict[str, Any]:
    from .content.models import SeoContentItem
    from .content.publish_jobs import create_publish_job

    blockers: list[str] = []
    for item_id in payload.item_ids:
        item = db.get(SeoContentItem, item_id)
        if item is None:
            blockers.append(f"{item_id}：不存在")
        elif item.review_status != "approved":
            blockers.append(f"《{item.title[:30]}》：还没批准")
        elif not (item.brand_audit_json or {}).get("clean", True):
            blockers.append(f"《{item.title[:30]}》：没过品牌/接地审查")
    if blockers:
        raise HTTPException(status_code=409, detail={"ready": False, "blockers": blockers})

    job = create_publish_job(
        db,
        item_ids=payload.item_ids,
        scope_context=_scope(request),
        user=user,
        public_base=_public_base(),
    )
    db.commit()
    return {"job_id": job.job_id, "status": job.status}


@router.get("/publishes")
def list_publishes(
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.read")),
) -> dict[str, Any]:
    from .content.publish_jobs import jobs_recent

    return {"jobs": jobs_recent(db)}


@router.post("/factory-index")
def rebuild_factory_index(
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.manage")),
) -> dict[str, Any]:
    """重建 /factory/ 枢纽页，并把 factory 分类推进博客排除名单。"""
    from .content.factory_index import upsert_factory_index
    from .content.live_state import refresh_item_live_state_safely
    from .content.wp_terms import sync_factory_category_exclusions

    refresh_item_live_state_safely(db)
    page_id, url = upsert_factory_index(db)
    excluded = sync_factory_category_exclusions(db)
    return {"page_id": page_id, "url": url, "excluded_category_ids": excluded}


# ============================================================ 监测


# ============================================================ 内链网


@router.get("/link-net")
def link_net_state(
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.read")),
) -> dict[str, Any]:
    """内链网现状。不出网。"""
    from ..content_links.link_push import state as link_state
    from ..geo_series.content.backlink_targets import collect_backlink_targets

    payload = link_state(db)
    # 产品页那侧:算出「有 N 个产品页的链接已过期」。零 WP 调用——
    # 靠上次真写进去的块指纹比对(见 backlink_targets 的注释)。
    try:
        targets, skipped = collect_backlink_targets(db)
    except Exception:  # noqa: BLE001 - 面板不该因为一处失败整块打不开
        targets, skipped = [], ["产品页状态暂时算不出来"]
    payload["product_pages"] = {
        "stale_count": len(targets),
        "reasons": [str(t.get("reason") or "") for t in targets],
        "skipped": skipped[:10],
    }
    return payload


@router.post("/link-net/refresh")
def link_net_refresh(
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.execute")),
) -> dict[str, Any]:
    """手动刷新文章内链。**绕过 15 分钟间隔护栏**——人明确说了要立刻看效果。

    正常情况下不用点:新文章发布、新产品上架都会自动刷。
    """
    from ..content_links.link_push import refresh_if_due

    return refresh_if_due(db, manual=True)


# ============================================================ 站内入口


@router.get("/site-nav")
def site_nav_state(
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.read")),
) -> dict[str, Any]:
    """枢纽页的内容数——决定它该不该有入口。不出网。"""
    from ..content_links.site_nav import HUBS, hub_item_counts, pinned_hubs

    counts = hub_item_counts(db)
    pinned = pinned_hubs(db)
    return {
        "hubs": [
            {
                "key": h.key,
                "label": h.label,
                "path": h.path,
                "count": counts.get(h.key, 0),
                "pinned": h.key in pinned,
            }
            for h in HUBS
        ]
    }


@router.post("/site-nav/pin")
def site_nav_pin(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.execute")),
) -> dict[str, Any]:
    """强制挂上/取消强制。**例外也要记在册上**——手动去 WP 加菜单项会被
    下次同步默默摘掉,用户还不知道是谁干的。"""
    from ..content_links.site_nav import set_hub_pinned, sync_site_nav

    try:
        pinned = set_hub_pinned(
            db, key=str(payload.get("key") or ""), pinned=bool(payload.get("pinned"))
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 改完立刻生效，不用人再点一次同步。
    return {"pinned": sorted(pinned), **sync_site_nav(db)}


@router.post("/site-nav/sync")
def site_nav_sync(
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.execute")),
) -> dict[str, Any]:
    """把主导航和主页入口区同步成枢纽的真实状态。"""
    from ..content_links.site_nav import sync_site_nav

    return sync_site_nav(db)


# ============================================================ 内容自检


# 自检覆盖 GEO 和 SEO 两边,但只挂一个端点、挂在 seo 下——沿用
# /seo/link-net 的既有做法(GeoContentDeck 调的也是那个)。内链网和自检
# 本来就是跨 GEO/SEO 的东西,拆两份必然分叉。


@router.get("/content-health")
def content_health(
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.read")),
) -> dict[str, Any]:
    """「标了完成却没有产物」的记录。只读,不出网。"""
    from ..content_core.consistency import find_stranded

    stranded = find_stranded(db)
    return {"stranded": stranded, "count": len(stranded)}


@router.post("/content-health/reset")
def content_health_reset(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.execute")),
) -> dict[str, Any]:
    """把卡死的记录复位,让它重新能被派单。"""
    from ..content_core.consistency import ConsistencyError, reset_stranded

    kind = str(payload.get("kind") or "").strip()
    ids = [str(i) for i in (payload.get("ids") or [])]
    try:
        reset = reset_stranded(db, kind=kind, record_ids=ids)
    except ConsistencyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"reset": reset}


@router.get("/monitor")
def seo_monitor(
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.read")),
) -> dict[str, Any]:
    from .content.rank_monitor import monitor_state

    return monitor_state(db)


@router.post("/monitor/seed")
def seo_monitor_seed(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.execute")),
) -> dict[str, Any]:
    from .content.rank_monitor import apply_terrain_to_topics, seed_from_picked_topics

    added = seed_from_picked_topics(db, scope_context=_scope(request))
    applied = apply_terrain_to_topics(db)
    return {"added": added, "topics_rescored": applied}


def _public_base() -> str:
    import os

    return os.getenv("PUBLIC_BASE_URL", "https://ops.barongyekhna.com").rstrip("/")


__all__ = ["router"]
