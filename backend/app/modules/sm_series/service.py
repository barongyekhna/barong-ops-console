"""编排层：排期 → 选图/缺口 → 写手 → 审计 → 落帖子；驳回 / 指定 / 手发回填。

所有函数**不 commit**（router / worker 统一收尾），除了标注「出网前先 commit」的地方。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..content_core.facts.models import CraftFact
from ..geo_series.content.models import GeoContentItem
from ..k_series.product_knowledge.models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
)
from ..k_series.product_knowledge.scope_shim import KScopeContext, apply_scope_filters
from . import audits, gaps, layout_render, planner, writer
from .constants import (
    LANE_LAYOUT,
    PILLAR_BRAND,
    PILLAR_FACTORY,
    PILLAR_GUIDE,
    PILLAR_LABELS,
    PLATFORM_FACEBOOK,
    PLATFORM_INSTAGRAM,
    POST_KIND_MIRROR,
    REJECT_AI_ARTIFACT,
    REJECT_BRAND,
    REJECT_REASONS,
    REJECT_WRONG_SCENE,
    SM_POST_SKILL_VERSION,
    SOURCE_CRAFT_FACT,
    SOURCE_GEO_ITEM,
    SOURCE_K_PRODUCT,
    SOURCE_NONE,
)
from .models import SmCalendarSlot, SmImageRequest, SmMediaUsage, SmPost, SmRejection
from .profiles import image_requirement, profile
from .selector import candidate_assets, select_images

logger = logging.getLogger(__name__)


class SmServiceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400, code: str = "SM_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


# ---------------------------------------------------------------- 源头装载


def _product(db: Session, scope: KScopeContext, product_id: UUID | None) -> KProductKnowledgeProduct | None:
    if product_id is None:
        return None
    return db.execute(
        apply_scope_filters(select(KProductKnowledgeProduct), KProductKnowledgeProduct, scope).where(
            KProductKnowledgeProduct.id == product_id
        )
    ).scalars().first()


def _guide(db: Session, scope: KScopeContext, item_id: UUID | None) -> GeoContentItem | None:
    if item_id is None:
        return None
    return db.execute(
        apply_scope_filters(select(GeoContentItem), GeoContentItem, scope).where(GeoContentItem.id == item_id)
    ).scalars().first()


def _facts(db: Session, scope: KScopeContext, *, fact_id: UUID | None, product_id: UUID | None) -> list[CraftFact]:
    query = apply_scope_filters(select(CraftFact), CraftFact, scope).where(CraftFact.status == "approved")
    rows = list(db.execute(query).scalars())
    if fact_id is not None:
        exact = [f for f in rows if f.id == fact_id]
        if exact:
            return exact
    if product_id is not None:
        related = [f for f in rows if str(product_id) in {str(x) for x in (f.product_ids_json or [])}]
        if related:
            return related
    return rows[:5]


def _public_url(db: Session, *, product: KProductKnowledgeProduct | None, guide: GeoContentItem | None) -> str | None:
    if guide is not None and guide.published_url:
        return str(guide.published_url)
    if product is not None:
        from ..geo_series.content.product_links import latest_public_url

        return latest_public_url(db, [product.id]).get(str(product.id))
    return None


def with_utm(url: str | None, *, platform: str, pillar: str, post_id: UUID) -> str | None:
    if not url:
        return None
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query))
    query.update(
        {
            "utm_source": platform,
            "utm_medium": "social",
            "utm_campaign": pillar.lower(),
            "utm_content": str(post_id),
        }
    )
    return urlunparse(parts._replace(query=urlencode(query)))


# ---------------------------------------------------------------- 排期 + 选图


def plan_calendar(db: Session, scope: KScopeContext, *, today: date | None = None, days: int | None = None) -> planner.PlanResult:
    today = today or date.today()
    reserved: set[UUID] = set()

    def media_planner(spec: planner.SlotSpec, row: SmCalendarSlot) -> dict[str, Any] | None:
        product = _product(db, scope, spec.seed_product_id)
        selection = select_images(
            db, scope, pillar=spec.pillar, platform=spec.platform, product=product, reserved=reserved
        )
        reserved.update(selection.asset_ids)
        plan = selection.to_media_plan()
        if selection.gap_lane:
            gap = gaps.open_gap(
                db,
                scope,
                slot=row,
                product=product,
                pillar=spec.pillar,
                platform=spec.platform,
                role=selection.gap_role or "scene",
                count=selection.gap_count,
                lane=selection.gap_lane,
                due_day=spec.day,
                source_label=spec.source_label,
            )
            plan["gap"] = {**(plan.get("gap") or {}), "request_id": str(gap.id), "lane": gap.lane, "k_position": gap.k_position}
        return plan

    kwargs: dict[str, Any] = {"start_day": today, "media_planner": media_planner}
    if days is not None:
        kwargs["days"] = days
    return planner.plan(db, scope, **kwargs)


# ---------------------------------------------------------------- 写手


def _keyword_hints(product: KProductKnowledgeProduct | None, guide: GeoContentItem | None) -> dict[str, Any]:
    hints: dict[str, Any] = {}
    if product is not None:
        hints["primary_keyword"] = product.primary_keyword
        hints["secondary_keywords"] = product.secondary_keywords_json
        hints["long_tail_keywords"] = product.long_tail_keywords_json
        hints["risk_keywords"] = product.risk_keywords_json
        hints["category_path"] = product.category_path
    if guide is not None:
        hints["guide_title"] = guide.title
        seo = guide.seo_json if isinstance(guide.seo_json, dict) else {}
        hints["guide_seo_title"] = seo.get("title")
    return hints


def _source_snapshot(
    db: Session,
    scope: KScopeContext,
    slot: SmCalendarSlot,
) -> tuple[dict[str, Any], KProductKnowledgeProduct | None, GeoContentItem | None, list[CraftFact]]:
    product = _product(db, scope, slot.seed_product_id)
    guide = _guide(db, scope, slot.source_id) if slot.source_type == SOURCE_GEO_ITEM else None
    fact_id = slot.source_id if slot.source_type == SOURCE_CRAFT_FACT else None
    facts = _facts(db, scope, fact_id=fact_id, product_id=slot.seed_product_id) if slot.pillar in (PILLAR_FACTORY, PILLAR_GUIDE) or fact_id else []
    snapshot: dict[str, Any] = {
        "source_type": slot.source_type,
        "k": audits.product_snapshot(product),
        "geo": audits.guide_snapshot(guide),
        "craft_facts": audits.facts_snapshot(facts),
        "public_url": _public_url(db, product=product, guide=guide),
        "brand": {
            "name": "Barong Yekhna",
            "seller": "Guangzhou Longjie E-Commerce Co., Ltd.",
            "factory": "our own factory in Jilin, China",
            "team": "Los Angeles",
        },
    }
    if product is not None:
        from ..k_series.product_knowledge.brand_guard import sanitize_snapshot_for_generation

        snapshot["k"] = sanitize_snapshot_for_generation(snapshot["k"], product)
    return snapshot, product, guide, facts


def _mirror_source_post(db: Session, scope: KScopeContext, slot: SmCalendarSlot) -> SmPost | None:
    plan = slot.media_plan_json if isinstance(slot.media_plan_json, dict) else {}
    mirror_slot_id = plan.get("mirror_of_slot")
    if not mirror_slot_id:
        return None
    mirror_slot = db.get(SmCalendarSlot, UUID(str(mirror_slot_id)))
    if mirror_slot is None or mirror_slot.post_id is None:
        return None
    return db.get(SmPost, mirror_slot.post_id)


def _record_usage(db: Session, scope: KScopeContext, *, asset_ids: list[UUID], platform: str, post_id: UUID) -> None:
    for asset_id in asset_ids:
        exists = db.execute(
            apply_scope_filters(select(SmMediaUsage.id), SmMediaUsage, scope).where(
                SmMediaUsage.asset_id == asset_id, SmMediaUsage.platform == platform
            )
        ).scalar()
        if exists is None:
            db.add(
                SmMediaUsage(
                    workspace_key=scope.workspace_key,
                    business_context=scope.business_context,
                    scope_mode=scope.scope_mode,
                    asset_id=asset_id,
                    platform=platform,
                    post_id=post_id,
                )
            )


def _build_media_refs(
    db: Session,
    scope: KScopeContext,
    *,
    slot: SmCalendarSlot,
    product: KProductKnowledgeProduct | None,
    guide: GeoContentItem | None,
    facts: list[CraftFact],
    output: dict[str, Any],
    user_id: int | None,
) -> tuple[list[dict[str, Any]], list[UUID]]:
    """按 media_plan 出图：需要版式就渲染成新资产；返回 (media_refs, 用掉的资产 id)。"""
    plan = slot.media_plan_json if isinstance(slot.media_plan_json, dict) else {}
    asset_ids = [UUID(str(a)) for a in plan.get("asset_ids") or []]
    req = image_requirement(slot.pillar, slot.platform)
    ratio = req.ratio if req is not None else "2:3"
    overlays = list(output.get("overlay_texts") or [])
    refs: list[dict[str, Any]] = []
    used: list[UUID] = []
    if not asset_ids and plan.get("text_card") and product is not None:
        headline = overlays[0] if overlays else (output.get("title") or output.get("first_line") or "")
        lines: list[str] = []
        if guide is not None:
            body = guide.body_json if isinstance(guide.body_json, dict) else {}
            lines = [str(s.get("heading") or "") for s in body.get("sections") or [] if isinstance(s, dict)][:5]
        elif facts:
            lines = [str(f.claim or f.topic) for f in facts][:5]
        try:
            card = layout_render.render_text_card(
                db, product=product, platform=slot.platform, pillar=slot.pillar, ratio=ratio,
                headline=headline, lines=lines, user_id=user_id,
            )
            refs.append({"asset_id": str(card.id), "slot": 1, "overlay_text": headline, "kind": "text_card"})
            used.append(card.id)
        except layout_render.LayoutError as exc:
            logger.warning("text card render failed: %s", exc)
        return refs, used
    for index, asset_id in enumerate(asset_ids, start=1):
        asset = db.get(KProductKnowledgeMediaAsset, asset_id)
        if asset is None:
            continue
        overlay = overlays[index - 1] if (req is not None and req.overlay and index - 1 < len(overlays)) else ""
        ref: dict[str, Any] = {"asset_id": str(asset_id), "slot": index, "overlay_text": overlay or None, "kind": "source"}
        if plan.get("needs_layout") and product is not None:
            try:
                card = layout_render.render_from_asset(
                    db, product=product, source_asset=asset, platform=slot.platform, pillar=slot.pillar,
                    ratio=ratio, headline=overlay, user_id=user_id,
                )
                ref["layout_asset_id"] = str(card.id)
                used.append(card.id)
            except layout_render.LayoutError as exc:
                ref["layout_error"] = str(exc)
        refs.append(ref)
        used.append(asset_id)
    return refs, used


def _apply_output_to_post(
    post: SmPost,
    *,
    output: dict[str, Any],
    audit: dict[str, Any],
    skill: dict[str, Any],
    media_refs: list[dict[str, Any]],
    link_url: str | None,
) -> None:
    post.title = (output.get("title") or output.get("first_line") or "")[:512]
    post.first_line = (output.get("first_line") or None)
    post.caption = output.get("caption") or None
    post.alt_text = (output.get("alt_text") or None)
    post.hashtags_json = output.get("hashtags") or []
    post.board = output.get("board") or None
    post.link_url = link_url
    post.media_refs_json = media_refs
    post.keyword_primary = output.get("keyword_primary") or None
    post.keywords_secondary_json = output.get("keywords_secondary") or []
    post.cta = output.get("cta") or None
    post.facts_used_json = output.get("facts_used") or []
    item = audits.desk_item(output)
    post.body_json = {"sections": item["sections"], "answer_blocks": []}
    post.seo_json = {"title": post.title, "meta_description": post.cta or "", "url_slug": None}
    post.brand_audit_json = audit
    post.skill_version = skill.get("version") or SM_POST_SKILL_VERSION
    post.provider = "deepseek"
    post.generation_status = "generated"


def write_slot(db: Session, scope: KScopeContext, slot: SmCalendarSlot, *, user: Any | None) -> SmPost:
    """填一格。Facebook 镜像不调模型；其余调写手 → 审计 → 落库。**内部会 commit 一次**（出网前放事务）。"""
    if slot.status not in ("planned", "swapped", "writing"):
        raise SmServiceError(f"这一格状态是 {slot.status}，不能写。", status_code=409, code="SLOT_NOT_WRITABLE")
    if slot.source_type == SOURCE_NONE and slot.pillar != PILLAR_BRAND:
        raise SmServiceError("这一格没有源头，先排期或手动换源头。", status_code=409, code="SLOT_NO_SOURCE")
    prof = profile(slot.platform)
    plan = slot.media_plan_json if isinstance(slot.media_plan_json, dict) else {}
    post_kind = str(plan.get("post_kind") or "")
    user_id = getattr(user, "id", None)

    if slot.platform == PLATFORM_FACEBOOK or post_kind == POST_KIND_MIRROR:
        source_post = _mirror_source_post(db, scope, slot)
        if source_post is None or source_post.generation_status != "generated":
            raise SmServiceError("镜像的 Instagram 那条还没写出来。", status_code=409, code="MIRROR_NOT_READY")
        post = SmPost(
            id=uuid4(), workspace_key=scope.workspace_key, business_context=scope.business_context,
            scope_mode=scope.scope_mode, slot_id=slot.id, platform=slot.platform, post_kind=POST_KIND_MIRROR,
            pillar=slot.pillar, source_type=slot.source_type, source_id=slot.source_id,
            seed_product_id=slot.seed_product_id, created_by_user_id=user_id,
        )
        post.title = source_post.title
        post.first_line = source_post.first_line
        # 正文不带链接：链接进第一条评论（cta 字段承载）
        post.caption = source_post.caption
        post.alt_text = source_post.alt_text
        post.hashtags_json = (source_post.hashtags_json or [])[: prof.hashtags_max]
        post.link_url = with_utm(source_post.link_url, platform=slot.platform, pillar=slot.pillar, post_id=post.id) if source_post.link_url else None
        post.cta = f"First comment: {post.link_url}" if post.link_url else source_post.cta
        post.media_refs_json = source_post.media_refs_json
        post.keyword_primary = source_post.keyword_primary
        post.keywords_secondary_json = source_post.keywords_secondary_json
        post.facts_used_json = source_post.facts_used_json
        post.body_json = source_post.body_json
        post.seo_json = source_post.seo_json
        post.brand_audit_json = source_post.brand_audit_json
        post.skill_version = source_post.skill_version
        post.provider = "mirror"
        post.generation_status = "generated"
        db.add(post)
        slot.status, slot.post_id = "filled", post.id
        db.flush()
        return post

    snapshot, product, guide, facts = _source_snapshot(db, scope, slot)
    media_plan = [
        {"slot": i + 1, "asset_id": a, "allows_overlay": bool(image_requirement(slot.pillar, slot.platform) and image_requirement(slot.pillar, slot.platform).overlay)}
        for i, a in enumerate(plan.get("asset_ids") or [])
    ]
    hints = _keyword_hints(product, guide)
    slot.status = "writing"
    # 🔴 出网前放掉事务（8 秒 idle-in-transaction 收割器）。
    slot_id = slot.id
    db.commit()

    output, skill = writer.generate(
        db, profile=prof, pillar=slot.pillar, post_kind=post_kind or "pinterest_pin",
        source_snapshot=snapshot, media_plan=media_plan, keyword_hints=hints, user=user,
    )

    slot = db.get(SmCalendarSlot, slot_id)
    if slot is None:  # pragma: no cover - 并发删格
        raise SmServiceError("格子在写的过程中被删了。", status_code=409)
    snapshot, product, guide, facts = _source_snapshot(db, scope, slot)
    post = SmPost(
        id=uuid4(), workspace_key=scope.workspace_key, business_context=scope.business_context,
        scope_mode=scope.scope_mode, slot_id=slot.id, platform=slot.platform, post_kind=post_kind or "pinterest_pin",
        pillar=slot.pillar, source_type=slot.source_type, source_id=slot.source_id,
        seed_product_id=slot.seed_product_id, created_by_user_id=user_id,
    )
    if output.get("blocked_reason"):
        post.generation_status = "failed"
        post.revision_json = {"blocked_reason": output["blocked_reason"], "skill_version": skill.get("version")}
        post.title = f"[blocked] {output['blocked_reason'][:200]}"
        db.add(post)
        slot.status = "planned"
        slot.swap_reason = f"写手拒写：{output['blocked_reason'][:200]}"
        db.flush()
        return post

    audit = audits.audit_post(
        db, post_fields=output, pillar=slot.pillar, profile=prof, product=product, guide=guide,
        facts=facts, previous_audit=None, user=user,
    )
    media_refs, used_assets = _build_media_refs(
        db, scope, slot=slot, product=product, guide=guide, facts=facts, output=output, user_id=user_id
    )
    link = with_utm(snapshot.get("public_url"), platform=slot.platform, pillar=slot.pillar, post_id=post.id)
    if prof.link_mode == "bio_only":
        # Instagram 链接不可点：留在 link_url 供简介/记录，文案里由 skill 写「link in bio」
        pass
    _apply_output_to_post(post, output=output, audit=audit, skill=skill, media_refs=media_refs, link_url=link)
    db.add(post)
    _record_usage(db, scope, asset_ids=used_assets, platform=slot.platform, post_id=post.id)
    slot.status, slot.post_id = "filled", post.id
    db.flush()
    return post


def revise_post(db: Session, scope: KScopeContext, post: SmPost, *, user: Any | None) -> SmPost:
    """按批评重写（内容台 revise_fn）。**内部 commit 一次**。"""
    analysis = post.analysis_json if isinstance(post.analysis_json, dict) else {}
    risks = [str(r) for r in analysis.get("risks") or [] if str(r).strip()]
    slot = db.get(SmCalendarSlot, post.slot_id) if post.slot_id else None
    if slot is None:
        raise SmServiceError("这条帖子没有对应的格子，无法重写。", status_code=409, code="POST_NO_SLOT")
    if post.post_kind == POST_KIND_MIRROR:
        raise SmServiceError("镜像帖跟着 Instagram 那条走，去改源帖。", status_code=409, code="MIRROR_READONLY")
    prof = profile(post.platform)
    snapshot, product, guide, facts = _source_snapshot(db, scope, slot)
    plan = slot.media_plan_json if isinstance(slot.media_plan_json, dict) else {}
    previous = {
        "title": post.title, "caption": post.caption, "first_line": post.first_line, "alt_text": post.alt_text,
        "hashtags": post.hashtags_json, "board": post.board, "cta": post.cta, "keyword_primary": post.keyword_primary,
        "keywords_secondary": post.keywords_secondary_json, "facts_used": post.facts_used_json,
    }
    previous_audit = post.brand_audit_json if isinstance(post.brand_audit_json, dict) else None
    round_no = int((post.revision_json or {}).get("round") or 0) + 1 if isinstance(post.revision_json, dict) else 1
    post_id = post.id
    db.commit()
    output, skill = writer.generate(
        db, profile=prof, pillar=slot.pillar, post_kind=post.post_kind, source_snapshot=snapshot,
        media_plan=[{"slot": i + 1, "asset_id": a} for i, a in enumerate(plan.get("asset_ids") or [])],
        keyword_hints=_keyword_hints(product, guide), user=user, critique=risks, previous_output=previous,
    )
    post = db.get(SmPost, post_id)
    if post is None:  # pragma: no cover
        raise SmServiceError("帖子在重写过程中被删了。", status_code=409)
    snapshot, product, guide, facts = _source_snapshot(db, scope, slot)
    if output.get("blocked_reason"):
        post.revision_json = {"round": round_no, "addressed": [], "unaddressed": [{"critique": r, "needs_data": True} for r in risks], "blocked_reason": output["blocked_reason"]}
        db.flush()
        return post
    audit = audits.audit_post(
        db, post_fields=output, pillar=slot.pillar, profile=prof, product=product, guide=guide,
        facts=facts, previous_audit=previous_audit, user=user,
    )
    _apply_output_to_post(post, output=output, audit=audit, skill=skill, media_refs=post.media_refs_json or [], link_url=post.link_url)
    post.revision_json = {"round": round_no, "addressed": risks, "unaddressed": []}
    post.review_status = "pending"
    db.flush()
    return post


# ---------------------------------------------------------------- 驳回 / 指定 / 手发


def reject_image(
    db: Session,
    scope: KScopeContext,
    post: SmPost,
    *,
    asset_id: UUID,
    reason_code: str,
    replacement_asset_id: UUID | None,
    note: str | None,
    user: Any | None,
) -> SmPost:
    if reason_code not in REJECT_REASONS:
        raise SmServiceError("未知驳回原因。", status_code=400, code="REJECT_REASON")
    db.add(
        SmRejection(
            workspace_key=scope.workspace_key, business_context=scope.business_context, scope_mode=scope.scope_mode,
            post_id=post.id, object="image", asset_id=asset_id, platform=post.platform, pillar=post.pillar,
            reason_code=reason_code, replacement_asset_id=replacement_asset_id, note=note,
            by_user_id=getattr(user, "id", None),
        )
    )
    refs = [dict(r) for r in (post.media_refs_json or []) if isinstance(r, dict)]
    slot = db.get(SmCalendarSlot, post.slot_id) if post.slot_id else None
    product = _product(db, scope, post.seed_product_id)
    replacement = replacement_asset_id
    if replacement is None and product is not None:
        req = image_requirement(post.pillar, post.platform)
        roles = req.roles if req is not None else ("main", "gallery", "description")
        reserved = {UUID(str(r.get("asset_id"))) for r in refs if r.get("asset_id")}
        pick = candidate_assets(db, scope, product=product, roles=roles, platform=post.platform, pillar=post.pillar, reserved=reserved)
        replacement = pick[0].id if pick else None
    if reason_code in (REJECT_WRONG_SCENE, REJECT_AI_ARTIFACT) and slot is not None and product is not None:
        req = image_requirement(post.pillar, post.platform)
        gaps.open_gap(
            db, scope, slot=slot, product=product, pillar=post.pillar, platform=post.platform,
            role=(req.roles[0] if req else "description"), count=1, lane="mcp", due_day=slot.day,
            source_label=(note or REJECT_WRONG_SCENE),
        )
    if reason_code == REJECT_BRAND:
        # 全站封禁：直接把资产标 removed（品牌门漏了一条，不只是社媒的事）
        asset = db.get(KProductKnowledgeMediaAsset, asset_id)
        if asset is not None:
            asset.status = "removed"
            meta = dict(asset.metadata_json or {})
            meta["removed_reason"] = f"sm_reject:{reason_code}"
            asset.metadata_json = meta
    new_refs: list[dict[str, Any]] = []
    for ref in refs:
        if str(ref.get("asset_id")) == str(asset_id) or str(ref.get("layout_asset_id")) == str(asset_id):
            if replacement is not None:
                new_refs.append({"asset_id": str(replacement), "slot": ref.get("slot"), "overlay_text": ref.get("overlay_text"), "kind": "replacement"})
            continue
        new_refs.append(ref)
    post.media_refs_json = new_refs
    if replacement is not None:
        _record_usage(db, scope, asset_ids=[replacement], platform=post.platform, post_id=post.id)
    if slot is not None and not new_refs:
        slot.swap_reason = f"图被驳回（{reason_code}），暂无替代"
    db.flush()
    return post


def pick_image(db: Session, scope: KScopeContext, post: SmPost, *, asset_id: UUID, slot_index: int, user: Any | None) -> SmPost:
    asset = db.get(KProductKnowledgeMediaAsset, asset_id)
    if asset is None or asset.status != "available":
        raise SmServiceError("这张图不存在或不可用。", status_code=404, code="ASSET_NOT_FOUND")
    product = _product(db, scope, asset.product_id)
    if product is None:
        raise SmServiceError("这张图不属于本组织的产品。", status_code=403, code="ASSET_SCOPE")
    refs = [dict(r) for r in (post.media_refs_json or []) if isinstance(r, dict)]
    replaced = False
    for ref in refs:
        if int(ref.get("slot") or 0) == slot_index:
            ref.update({"asset_id": str(asset_id), "kind": "manual_pick", "layout_asset_id": None})
            replaced = True
    if not replaced:
        refs.append({"asset_id": str(asset_id), "slot": slot_index, "overlay_text": None, "kind": "manual_pick"})
    post.media_refs_json = sorted(refs, key=lambda r: int(r.get("slot") or 0))
    _record_usage(db, scope, asset_ids=[asset_id], platform=post.platform, post_id=post.id)
    db.flush()
    return post


def mark_posted(db: Session, post: SmPost, *, permalink: str, external_id: str | None, user: Any | None) -> SmPost:
    if post.review_status != "approved":
        raise SmServiceError("没批准的帖子不能标记已发布。", status_code=409, code="POST_NOT_APPROVED")
    post.publish_status = "posted"
    post.permalink = permalink.strip()
    post.published_url = post.permalink
    post.external_id = external_id
    now = datetime.now(UTC)
    post.posted_at = now
    post.published_at = now
    slot = db.get(SmCalendarSlot, post.slot_id) if post.slot_id else None
    if slot is not None:
        slot.status = "posted"
    db.flush()
    return post


def swap_slot(
    db: Session,
    scope: KScopeContext,
    slot: SmCalendarSlot,
    *,
    pillar: str | None,
    source_type: str | None,
    source_id: UUID | None,
    seed_product_id: UUID | None,
    reason: str,
) -> SmCalendarSlot:
    if slot.post_id is not None:
        raise SmServiceError("已经写出帖子的格子不能换源头，先在内容台驳回。", status_code=409, code="SLOT_HAS_POST")
    if pillar:
        slot.pillar = pillar
    if source_type:
        slot.source_type = source_type
        slot.source_id = source_id
        slot.seed_product_id = seed_product_id
    label_src = ""
    if slot.source_type == SOURCE_K_PRODUCT:
        product = _product(db, scope, slot.seed_product_id)
        label_src = product.sku if product else ""
    elif slot.source_type == SOURCE_GEO_ITEM:
        guide = _guide(db, scope, slot.source_id)
        label_src = (guide.title[:60] if guide else "")
    slot.label = f"{slot.day.isoformat()} · {slot.platform} · {PILLAR_LABELS.get(slot.pillar, slot.pillar)}" + (f" · {label_src}" if label_src else "")
    slot.status = "swapped"
    slot.swap_reason = reason
    product = _product(db, scope, slot.seed_product_id)
    selection = select_images(db, scope, pillar=slot.pillar, platform=slot.platform, product=product)
    plan = dict(slot.media_plan_json or {})
    plan.update(selection.to_media_plan())
    plan["post_kind"] = planner._post_kind_for(slot.pillar, slot.platform)
    if selection.gap_lane:
        gap = gaps.open_gap(
            db, scope, slot=slot, product=product, pillar=slot.pillar, platform=slot.platform,
            role=selection.gap_role or "scene", count=selection.gap_count, lane=selection.gap_lane, due_day=slot.day,
        )
        plan["gap"] = {**(plan.get("gap") or {}), "request_id": str(gap.id), "lane": gap.lane, "k_position": gap.k_position}
    slot.media_plan_json = plan
    db.flush()
    return slot


__all__ = [
    "SmServiceError",
    "mark_posted",
    "pick_image",
    "plan_calendar",
    "reject_image",
    "revise_post",
    "swap_slot",
    "with_utm",
    "write_slot",
]
