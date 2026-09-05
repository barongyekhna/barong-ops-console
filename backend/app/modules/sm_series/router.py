"""SM 系列人用端点。全部挂 ``/api/app/sm``（只挂一次，没有机器端点）。

门禁照 GEO：owner / super_admin 直通；execute / manage 蕴含 read。
每个读端点带 ``_scope_context(request)`` 过 ``apply_scope_filters``。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.roles import is_super_admin_role
from ...db.session import get_db
from ...models.user import User
from ...services.permission_service import resolve_current_user_permission_info
from ..k_series.product_knowledge.constants import DEFAULT_BUSINESS_CONTEXT, DEFAULT_WORKSPACE_KEY
from ..k_series.product_knowledge.models import KProductKnowledgeMediaAsset, KProductKnowledgeProduct
from ..k_series.product_knowledge.scope_shim import KScopeContext, apply_scope_filters
from . import jobs, service
from .constants import (
    LANES,
    PERMISSION_EXECUTE,
    PERMISSION_MANAGE,
    PERMISSION_READ,
    PILLAR_LABELS,
    PILLARS,
    PLAN_HORIZON_DAYS,
    PLATFORMS,
    POST_KIND_LABELS,
    PROFILE_VERSION,
    REJECT_REASON_LABELS,
    REJECT_REASONS,
    SOURCE_TYPES,
)
from .inventory import load_inventory
from .models import SmCalendarSlot, SmChannel, SmImageRequest, SmPost
from .profiles import PLATFORM_PROFILES, image_requirements_view

router = APIRouter(prefix="/sm", tags=["sm-social"])


def _require_sm_permission(permission_key: str):
    """owner / super_admin 直通；execute / manage 蕴含 read。"""

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        permissions = resolve_current_user_permission_info(db, user, request=request)
        allowed = {permission_key}
        if permission_key == PERMISSION_READ:
            allowed.update({PERMISSION_EXECUTE, PERMISSION_MANAGE})
        elif permission_key == PERMISSION_EXECUTE:
            allowed.add(PERMISSION_MANAGE)
        if (
            permissions.is_owner_full_access
            or is_super_admin_role(user.role)
            or allowed.intersection(permissions.permission_keys)
        ):
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {permission_key}")

    return dependency


def _scope_context(request: Request | None) -> KScopeContext:
    org_id = None
    if request is not None:
        org_id = getattr(request.state, "org_id", None)
        if org_id is None:
            org_context = getattr(request.state, "org_context", None)
            org_id = getattr(org_context, "org_id", None)
    workspace_key = str(org_id).strip() if org_id else DEFAULT_WORKSPACE_KEY
    return KScopeContext(workspace_key=workspace_key, business_context=DEFAULT_BUSINESS_CONTEXT, scope_mode="production")


def _raise(exc: service.SmServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


# ---------------------------------------------------------------- 序列化


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") and value is not None else None


def _thumb(asset_id: str | None) -> str | None:
    return f"/k/media/{asset_id}/thumbnail" if asset_id else None


def _post_summary(post: SmPost | None) -> dict[str, Any] | None:
    if post is None:
        return None
    refs = [r for r in (post.media_refs_json or []) if isinstance(r, dict)]
    audit = post.brand_audit_json if isinstance(post.brand_audit_json, dict) else {}
    return {
        "id": str(post.id),
        "platform": post.platform,
        "post_kind": post.post_kind,
        "post_kind_label": POST_KIND_LABELS.get(post.post_kind, post.post_kind),
        "pillar": post.pillar,
        "title": post.title,
        "first_line": post.first_line,
        "review_status": post.review_status,
        "generation_status": post.generation_status,
        "publish_status": post.publish_status,
        "audit_clean": bool(audit.get("clean")) if audit else None,
        "audit_unresolved": int(audit.get("unresolved_count") or 0) if audit else None,
        "media": [
            {
                "slot": r.get("slot"),
                "asset_id": r.get("asset_id"),
                "layout_asset_id": r.get("layout_asset_id"),
                "overlay_text": r.get("overlay_text"),
                "kind": r.get("kind"),
                "thumbnail_url": _thumb(r.get("layout_asset_id") or r.get("asset_id")),
            }
            for r in refs
        ],
        "permalink": post.permalink,
        "updated_at": _iso(post.updated_at),
    }


def _post_detail(post: SmPost) -> dict[str, Any]:
    base = _post_summary(post) or {}
    base.update(
        {
            "slot_id": str(post.slot_id) if post.slot_id else None,
            "source_type": post.source_type,
            "source_id": str(post.source_id) if post.source_id else None,
            "seed_product_id": str(post.seed_product_id) if post.seed_product_id else None,
            "caption": post.caption,
            "alt_text": post.alt_text,
            "hashtags": post.hashtags_json or [],
            "board": post.board,
            "link_url": post.link_url,
            "keyword_primary": post.keyword_primary,
            "keywords_secondary": post.keywords_secondary_json or [],
            "cta": post.cta,
            "facts_used": post.facts_used_json or [],
            "brand_audit": post.brand_audit_json,
            "analysis": post.analysis_json,
            "revision": post.revision_json,
            "skill_version": post.skill_version,
            "provider": post.provider,
            "external_id": post.external_id,
            "posted_at": _iso(post.posted_at),
            "created_at": _iso(post.created_at),
            "reject_reasons": [{"code": c, "label": REJECT_REASON_LABELS[c]} for c in REJECT_REASONS],
        }
    )
    return base


def _gap_view(req: SmImageRequest) -> dict[str, Any]:
    return {
        "id": str(req.id),
        "slot_id": str(req.slot_id) if req.slot_id else None,
        "source_type": req.source_type,
        "source_id": str(req.source_id) if req.source_id else None,
        "seed_product_id": str(req.seed_product_id) if req.seed_product_id else None,
        "pillar": req.pillar,
        "pillar_label": PILLAR_LABELS.get(req.pillar, req.pillar),
        "platform": req.platform,
        "role": req.role,
        "count": req.count,
        "ratio": req.ratio,
        "lane": req.lane,
        "k_position": req.k_position,
        "due_day": req.due_day.isoformat(),
        "status": req.status,
        "brief_text": req.brief_text,
        "prompt_text": req.prompt_text,
        "filled_asset_id": str(req.filled_asset_id) if req.filled_asset_id else None,
        "created_at": _iso(req.created_at),
    }


def _slot_view(slot: SmCalendarSlot, post: SmPost | None, gap: SmImageRequest | None, product_sku: str | None) -> dict[str, Any]:
    plan = slot.media_plan_json if isinstance(slot.media_plan_json, dict) else {}
    asset_ids = [str(a) for a in plan.get("asset_ids") or []]
    return {
        "id": str(slot.id),
        "day": slot.day.isoformat(),
        "weekday": slot.day.weekday(),
        "platform": slot.platform,
        "slot_index": slot.slot_index,
        "window_pt": slot.window_pt,
        "pillar": slot.pillar,
        "pillar_label": PILLAR_LABELS.get(slot.pillar, slot.pillar),
        "label": slot.label,
        "source_type": slot.source_type,
        "source_id": str(slot.source_id) if slot.source_id else None,
        "seed_product_id": str(slot.seed_product_id) if slot.seed_product_id else None,
        "seed_product_sku": product_sku,
        "status": slot.status,
        "swap_reason": slot.swap_reason,
        "post_kind": plan.get("post_kind"),
        "media_plan": {
            "asset_ids": asset_ids,
            "thumbnail_urls": [_thumb(a) for a in asset_ids],
            "needs_layout": bool(plan.get("needs_layout")),
            "text_card": bool(plan.get("text_card")),
            "mirror_of_slot": plan.get("mirror_of_slot"),
            "gap": plan.get("gap"),
        },
        "gap": _gap_view(gap) if gap is not None else None,
        "post": _post_summary(post),
        "planner_version": slot.planner_version,
    }


# ---------------------------------------------------------------- 档案 / 渠道


@router.get("/profiles")
def get_profiles(user: User = Depends(_require_sm_permission(PERMISSION_READ))) -> dict[str, Any]:
    del user
    return {
        "version": PROFILE_VERSION,
        "profiles": [prof.to_dict() for prof in PLATFORM_PROFILES.values()],
        "image_requirements": image_requirements_view(),
        "pillars": [{"key": p, "label": PILLAR_LABELS[p]} for p in PILLARS],
        "reject_reasons": [{"code": c, "label": REJECT_REASON_LABELS[c]} for c in REJECT_REASONS],
    }


class ChannelIn(BaseModel):
    platform: str = Field(pattern="^(pinterest|instagram|facebook)$")
    handle: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class ChannelPatch(BaseModel):
    handle: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, pattern="^(active|paused)$")
    notes: str | None = None
    mode: str | None = Field(default=None, pattern="^(manual)$")  # mock 期只允许 manual


def _channel_view(row: SmChannel) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "platform": row.platform,
        "handle": row.handle,
        "mode": row.mode,
        "status": row.status,
        "profile_version": row.profile_version,
        "notes": row.notes,
        "created_at": _iso(row.created_at),
    }


@router.get("/channels")
def list_channels(
    request: Request, db: Session = Depends(get_db), user: User = Depends(_require_sm_permission(PERMISSION_READ))
) -> dict[str, Any]:
    del user
    rows = db.execute(apply_scope_filters(select(SmChannel), SmChannel, _scope_context(request)).order_by(SmChannel.platform)).scalars()
    return {"channels": [_channel_view(r) for r in rows]}


@router.post("/channels", status_code=status.HTTP_201_CREATED)
def create_channel(
    payload: ChannelIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_sm_permission(PERMISSION_MANAGE)),
) -> dict[str, Any]:
    del user
    scope = _scope_context(request)
    exists = db.execute(
        apply_scope_filters(select(SmChannel), SmChannel, scope).where(SmChannel.platform == payload.platform)
    ).scalars().first()
    if exists is not None:
        raise HTTPException(status_code=409, detail="这个平台的渠道已经存在。")
    row = SmChannel(
        workspace_key=scope.workspace_key, business_context=scope.business_context, scope_mode=scope.scope_mode,
        platform=payload.platform, handle=payload.handle, mode="manual", status="active",
        profile_version=PROFILE_VERSION, notes=payload.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _channel_view(row)


@router.patch("/channels/{channel_id}")
def patch_channel(
    channel_id: UUID,
    payload: ChannelPatch,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_sm_permission(PERMISSION_MANAGE)),
) -> dict[str, Any]:
    del user
    row = db.execute(
        apply_scope_filters(select(SmChannel), SmChannel, _scope_context(request)).where(SmChannel.id == channel_id)
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="渠道不存在。")
    for field_name in ("handle", "status", "notes", "mode"):
        value = getattr(payload, field_name)
        if value is not None:
            setattr(row, field_name, value)
    db.commit()
    db.refresh(row)
    return _channel_view(row)


# ---------------------------------------------------------------- 库存 / 日历


@router.get("/inventory")
def get_inventory(
    request: Request, db: Session = Depends(get_db), user: User = Depends(_require_sm_permission(PERMISSION_READ))
) -> dict[str, Any]:
    del user
    inv = load_inventory(db, _scope_context(request))
    return {
        "summary": inv.summary(),
        "products": [
            {
                "product_id": str(p.product_id), "sku": p.sku, "name": p.name, "public_url": p.public_url,
                "in_stock": p.in_stock, "brand_clean": p.brand_clean, "asset_counts": p.asset_counts,
                "last_posted": {k: _iso(v) for k, v in p.last_posted.items()},
            }
            for p in inv.products
        ],
        "guides": [
            {
                "item_id": str(g.item_id), "title": g.title, "item_type": g.item_type, "public_url": g.public_url,
                "seed_product_id": str(g.seed_product_id) if g.seed_product_id else None,
                "section_count": g.section_count, "last_posted": {k: _iso(v) for k, v in g.last_posted.items()},
            }
            for g in inv.guides
        ],
        "facts": [{"fact_id": str(f.fact_id), "topic": f.topic, "claim": f.claim} for f in inv.facts],
    }


class PlanIn(BaseModel):
    days: int = Field(default=PLAN_HORIZON_DAYS, ge=1, le=56)


@router.post("/calendar/plan")
def plan_calendar(
    payload: PlanIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_sm_permission(PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    del user
    scope = _scope_context(request)
    channels = db.execute(
        apply_scope_filters(select(SmChannel), SmChannel, scope).where(SmChannel.status == "active")
    ).scalars().all()
    if not channels:
        raise HTTPException(status_code=409, detail="先在「渠道档案」里登记至少一个平台渠道（mock 期 mode=manual）。")
    result = service.plan_calendar(db, scope, days=payload.days)
    db.commit()
    return {
        "run_id": str(result.run_id),
        "created": result.created,
        "blocked": result.blocked,
        "per_platform": result.per_platform,
        "start_day": result.start_day.isoformat(),
        "days": result.days,
    }


@router.get("/calendar")
def get_calendar(
    request: Request,
    from_day: date | None = Query(default=None, alias="from"),
    to_day: date | None = Query(default=None, alias="to"),
    platform: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(_require_sm_permission(PERMISSION_READ)),
) -> dict[str, Any]:
    del user
    scope = _scope_context(request)
    start = from_day or date.today()
    end = to_day or (start + timedelta(days=PLAN_HORIZON_DAYS - 1))
    query = apply_scope_filters(select(SmCalendarSlot), SmCalendarSlot, scope).where(
        SmCalendarSlot.day >= start, SmCalendarSlot.day <= end
    )
    if platform:
        query = query.where(SmCalendarSlot.platform == platform)
    slots = list(db.execute(query.order_by(SmCalendarSlot.day, SmCalendarSlot.platform, SmCalendarSlot.slot_index)).scalars())
    post_ids = [s.post_id for s in slots if s.post_id]
    posts = {p.id: p for p in db.execute(select(SmPost).where(SmPost.id.in_(post_ids))).scalars()} if post_ids else {}
    slot_ids = [s.id for s in slots]
    gap_rows = (
        db.execute(
            apply_scope_filters(select(SmImageRequest), SmImageRequest, scope).where(
                SmImageRequest.slot_id.in_(slot_ids), SmImageRequest.status == "open"
            )
        ).scalars()
        if slot_ids
        else []
    )
    gaps_by_slot = {g.slot_id: g for g in gap_rows}
    product_ids = {s.seed_product_id for s in slots if s.seed_product_id}
    skus = (
        {
            p.id: p.sku
            for p in db.execute(
                select(KProductKnowledgeProduct).where(KProductKnowledgeProduct.id.in_(list(product_ids)))
            ).scalars()
        }
        if product_ids
        else {}
    )
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "platforms": list(PLATFORMS),
        "slots": [_slot_view(s, posts.get(s.post_id), gaps_by_slot.get(s.id), skus.get(s.seed_product_id)) for s in slots],
    }


def _load_slot(db: Session, request: Request, slot_id: UUID) -> SmCalendarSlot:
    slot = db.execute(
        apply_scope_filters(select(SmCalendarSlot), SmCalendarSlot, _scope_context(request)).where(SmCalendarSlot.id == slot_id)
    ).scalars().first()
    if slot is None:
        raise HTTPException(status_code=404, detail="这一格不存在。")
    return slot


@router.post("/slots/{slot_id}/write")
def write_slot(
    slot_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_sm_permission(PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    slot = _load_slot(db, request, slot_id)
    if slot.status not in ("planned", "swapped"):
        raise HTTPException(status_code=409, detail=f"这一格状态是 {slot.status}，不能写。")
    if jobs.pending_or_running_for_slot(db, slot.id):
        raise HTTPException(status_code=409, detail="这一格已经在队列里。")
    job_id = jobs.enqueue(db, scope=_scope_context(request), job_type=jobs.JOB_WRITE, slot_id=slot.id, user=user)
    db.commit()
    return {"job_id": str(job_id), "slot_id": str(slot.id), "status": "queued"}


class SwapIn(BaseModel):
    pillar: str | None = Field(default=None, pattern="^(P1|P2|P3|P4|P5)$")
    source_type: str | None = None
    source_id: UUID | None = None
    seed_product_id: UUID | None = None
    reason: str = Field(default="手动换源头", max_length=255)


@router.post("/slots/{slot_id}/swap")
def swap_slot(
    slot_id: UUID,
    payload: SwapIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_sm_permission(PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    del user
    if payload.source_type is not None and payload.source_type not in SOURCE_TYPES:
        raise HTTPException(status_code=400, detail="未知源头类型。")
    slot = _load_slot(db, request, slot_id)
    try:
        service.swap_slot(
            db, _scope_context(request), slot, pillar=payload.pillar, source_type=payload.source_type,
            source_id=payload.source_id, seed_product_id=payload.seed_product_id, reason=payload.reason,
        )
    except service.SmServiceError as exc:
        _raise(exc)
    db.commit()
    db.refresh(slot)
    return _slot_view(slot, None, None, None)


# ---------------------------------------------------------------- 帖子


def _load_post(db: Session, request: Request, post_id: UUID) -> SmPost:
    post = db.execute(
        apply_scope_filters(select(SmPost), SmPost, _scope_context(request)).where(SmPost.id == post_id)
    ).scalars().first()
    if post is None:
        raise HTTPException(status_code=404, detail="帖子不存在。")
    return post


@router.get("/posts")
def list_posts(
    request: Request,
    review_status: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(_require_sm_permission(PERMISSION_READ)),
) -> dict[str, Any]:
    del user
    query = apply_scope_filters(select(SmPost), SmPost, _scope_context(request))
    if review_status:
        query = query.where(SmPost.review_status == review_status)
    if platform:
        query = query.where(SmPost.platform == platform)
    rows = db.execute(query.order_by(SmPost.created_at.desc()).limit(limit)).scalars()
    return {"posts": [_post_summary(p) for p in rows]}


@router.get("/posts/{post_id}")
def get_post(
    post_id: UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(_require_sm_permission(PERMISSION_READ))
) -> dict[str, Any]:
    del user
    post = _load_post(db, request, post_id)
    detail = _post_detail(post)
    # 候选替代图（同源头、未用过、未被驳回）
    product = service._product(db, _scope_context(request), post.seed_product_id)
    if product is not None:
        from .selector import candidate_assets
        from .profiles import image_requirement

        req = image_requirement(post.pillar, post.platform)
        roles = req.roles if req is not None else ("main", "gallery", "description")
        detail["candidates"] = [
            {"asset_id": str(a.id), "asset_role": a.asset_role, "thumbnail_url": _thumb(str(a.id))}
            for a in candidate_assets(db, _scope_context(request), product=product, roles=roles, platform=post.platform, pillar=post.pillar)[:12]
        ]
    else:
        detail["candidates"] = []
    return detail


class RejectImageIn(BaseModel):
    asset_id: UUID
    reason_code: str
    replacement_asset_id: UUID | None = None
    note: str | None = Field(default=None, max_length=500)


@router.post("/posts/{post_id}/reject-image")
def reject_image(
    post_id: UUID,
    payload: RejectImageIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_sm_permission(PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    post = _load_post(db, request, post_id)
    try:
        service.reject_image(
            db, _scope_context(request), post, asset_id=payload.asset_id, reason_code=payload.reason_code,
            replacement_asset_id=payload.replacement_asset_id, note=payload.note, user=user,
        )
    except service.SmServiceError as exc:
        _raise(exc)
    db.commit()
    db.refresh(post)
    return _post_detail(post)


class PickImageIn(BaseModel):
    asset_id: UUID
    slot_index: int = Field(default=1, ge=1, le=10)


@router.post("/posts/{post_id}/pick-image")
def pick_image(
    post_id: UUID,
    payload: PickImageIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_sm_permission(PERMISSION_EXECUTE)),
) -> dict[str, Any]:
    post = _load_post(db, request, post_id)
    try:
        service.pick_image(db, _scope_context(request), post, asset_id=payload.asset_id, slot_index=payload.slot_index, user=user)
    except service.SmServiceError as exc:
        _raise(exc)
    db.commit()
    db.refresh(post)
    return _post_detail(post)


class MarkPostedIn(BaseModel):
    permalink: str = Field(min_length=8, max_length=2048)
    external_id: str | None = Field(default=None, max_length=255)


@router.post("/posts/{post_id}/mark-posted")
def mark_posted(
    post_id: UUID,
    payload: MarkPostedIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_sm_permission(PERMISSION_MANAGE)),
) -> dict[str, Any]:
    post = _load_post(db, request, post_id)
    try:
        service.mark_posted(db, post, permalink=payload.permalink, external_id=payload.external_id, user=user)
    except service.SmServiceError as exc:
        _raise(exc)
    db.commit()
    db.refresh(post)
    return _post_detail(post)


# ---------------------------------------------------------------- 缺口单 / 任务


@router.get("/image-requests")
def list_image_requests(
    request: Request,
    lane: str | None = Query(default=None),
    status_filter: str | None = Query(default="open", alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(_require_sm_permission(PERMISSION_READ)),
) -> dict[str, Any]:
    del user
    if lane is not None and lane not in LANES:
        raise HTTPException(status_code=400, detail="未知缺口道。")
    query = apply_scope_filters(select(SmImageRequest), SmImageRequest, _scope_context(request))
    if lane:
        query = query.where(SmImageRequest.lane == lane)
    if status_filter and status_filter != "all":
        query = query.where(SmImageRequest.status == status_filter)
    rows = db.execute(query.order_by(SmImageRequest.due_day.asc(), SmImageRequest.created_at.asc())).scalars()
    return {"requests": [_gap_view(r) for r in rows]}


@router.post("/image-requests/{image_request_id}/dismiss")
def dismiss_image_request(
    image_request_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_sm_permission(PERMISSION_MANAGE)),
) -> dict[str, Any]:
    del user
    row = db.execute(
        apply_scope_filters(select(SmImageRequest), SmImageRequest, _scope_context(request)).where(SmImageRequest.id == image_request_id)
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="缺口单不存在。")
    row.status = "dormant"
    db.commit()
    db.refresh(row)
    return _gap_view(row)


@router.get("/jobs")
def list_jobs(
    request: Request, db: Session = Depends(get_db), user: User = Depends(_require_sm_permission(PERMISSION_READ))
) -> dict[str, Any]:
    del user
    return {"jobs": jobs.jobs_status(db, scope=_scope_context(request))}


__all__ = ["router"]
