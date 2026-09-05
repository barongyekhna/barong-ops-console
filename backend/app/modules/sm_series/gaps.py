"""缺口单（报告 03.7 第三步）：筛不到图就说缺什么，分三条道。

- layout：版式渲染当场自动填（writer 里做，这里不管）
- mcp：登记成 K 简报里的社媒位号（201+），Codex 经 K 的 MCP 通道交稿；
  交回来的图 staged → 审查 → 人保存 → 这里的 sweep 扫到 available 就关单
- photo：只登记 + 拍摄清单，等吉林的人拍；上传后 sweep 关单

两条护栏：截止日前 2 天没填上 → 格子换支柱（不让日历断）；30 天没人理 →
降成长期缺口（dormant），不再天天提。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..content_core.facts.models import CraftFact
from ..k_series.product_knowledge.models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
)
from ..k_series.product_knowledge.scope_shim import KScopeContext, apply_scope_filters
from .constants import (
    ASSET_ROLE_FACTORY,
    GAP_DORMANT_AFTER_DAYS,
    GAP_SWAP_LEAD_DAYS,
    LANE_MCP,
    LANE_PHOTO,
    PILLAR_FACTORY,
    PILLAR_LABELS,
    PILLAR_SCENE,
    SOCIAL_POSITION_BASE,
)
from .models import SmCalendarSlot, SmImageRequest
from .profiles import image_requirement

logger = logging.getLogger(__name__)

# 家规风格块（与 K 家规同源的措辞，社媒位号提示词专用）。
HOUSE_SCENE_STYLE = (
    "Warm, bright, soft daylight; the product is the only subject; realistic use scene; "
    "no third-party logos, no text, no people's faces in focus; the product's pixels must "
    "match the attached reference exactly (shape, color, ports, hose)."
)

SCENE_MOTIFS: dict[str, str] = {
    PILLAR_SCENE: "real-world use scene (campsite, van, backyard, dock) at golden hour",
    "guide": "a decision-support scene that illustrates the guide's question",
}


def next_social_position(db: Session, *, product_id: UUID) -> int:
    """产品简报里下一个空的社媒位号（201+）。同产品的缺口单与已有资产都算占用。"""
    taken: set[int] = set()
    for (pos,) in db.execute(
        select(SmImageRequest.k_position).where(
            SmImageRequest.seed_product_id == product_id, SmImageRequest.k_position.is_not(None)
        )
    ).all():
        taken.add(int(pos))
    rows = db.execute(
        select(KProductKnowledgeMediaAsset.metadata_json).where(
            KProductKnowledgeMediaAsset.product_id == product_id,
            KProductKnowledgeMediaAsset.status != "removed",
        )
    ).scalars()
    for meta in rows:
        if isinstance(meta, dict):
            try:
                pos = int(meta.get("position") or 0)
            except (TypeError, ValueError):
                continue
            if pos > SOCIAL_POSITION_BASE:
                taken.add(pos)
    position = SOCIAL_POSITION_BASE + 1
    while position in taken:
        position += 1
    return position


def mcp_prompt(
    *,
    product: KProductKnowledgeProduct,
    pillar: str,
    platform: str,
    ratio: str,
    source_label: str,
) -> str:
    name = (product.product_name_en or product.primary_keyword or product.sku or "the product").strip()
    motif = SCENE_MOTIFS.get(pillar, SCENE_MOTIFS[PILLAR_SCENE])
    if pillar not in SCENE_MOTIFS:
        motif = SCENE_MOTIFS["guide"]
    return (
        f"Social {platform} image ({ratio}) for pillar {PILLAR_LABELS.get(pillar, pillar)}: "
        f"{name} in a {motif}. Context: {source_label}. {HOUSE_SCENE_STYLE}"
    )


def shot_list(
    db: Session,
    *,
    scope: KScopeContext,
    product: KProductKnowledgeProduct | None,
    pillar: str,
) -> str:
    """给拍照的人看的一句话清单：拍什么、怎么拍。从工艺事实推出来。"""
    facts = list(
        db.execute(
            apply_scope_filters(select(CraftFact), CraftFact, scope).where(CraftFact.status == "approved").limit(3)
        ).scalars()
    )
    subject = "水泵测试台 / 装配工位 / 老化架"
    if facts:
        subject = "；".join(str(f.claim or f.topic) for f in facts if (f.claim or f.topic))[:200]
    who = f"（{product.sku}）" if product is not None else ""
    if pillar == PILLAR_FACTORY:
        return (
            f"工厂位缺 1 张真照片{who}：拍 {subject}。手机横拍，白天开灯，画面里有人手在操作，"
            "不要摆拍、不要露第三方品牌标识。从 K 媒体上传口传上来，角色选 factory。"
        )
    return f"缺 1 张真实使用照片{who}：产品在真实环境里被使用，自然光，不加滤镜。上传后角色选 description。"


def open_gap(
    db: Session,
    scope: KScopeContext,
    *,
    slot: SmCalendarSlot | None,
    product: KProductKnowledgeProduct | None,
    pillar: str,
    platform: str,
    role: str,
    count: int,
    lane: str,
    due_day: date,
    source_label: str = "",
) -> SmImageRequest:
    """开一张缺口单；同源头同平台同支柱同角色已有 open 单就复用。"""
    seed_product_id = product.id if product is not None else None
    existing = db.execute(
        apply_scope_filters(select(SmImageRequest), SmImageRequest, scope).where(
            SmImageRequest.status == "open",
            SmImageRequest.platform == platform,
            SmImageRequest.pillar == pillar,
            SmImageRequest.role == role,
            SmImageRequest.seed_product_id == seed_product_id,
        )
    ).scalars().first()
    if existing is not None:
        if slot is not None and existing.slot_id is None:
            existing.slot_id = slot.id
        if existing.due_day > due_day:
            existing.due_day = due_day
        return existing
    req = image_requirement(pillar, platform)
    ratio = req.ratio if req is not None else "2:3"
    row = SmImageRequest(
        workspace_key=scope.workspace_key,
        business_context=scope.business_context,
        scope_mode=scope.scope_mode,
        slot_id=slot.id if slot is not None else None,
        source_type=slot.source_type if slot is not None else "manual",
        source_id=slot.source_id if slot is not None else None,
        seed_product_id=seed_product_id,
        pillar=pillar,
        platform=platform,
        role=role,
        count=max(1, count),
        ratio=ratio,
        lane=lane,
        due_day=due_day,
        status="open",
    )
    if lane == LANE_MCP and product is not None:
        row.k_position = next_social_position(db, product_id=product.id)
        row.prompt_text = mcp_prompt(product=product, pillar=pillar, platform=platform, ratio=ratio, source_label=source_label)
        row.brief_text = (
            f"K 简报社媒位 {row.k_position}（{product.sku}）：在 Codex 里取 {product.sku} 的简报出这一位，交稿后到控制台保存。"
        )
    else:
        row.brief_text = shot_list(db, scope=scope, product=product, pillar=pillar)
        if lane == LANE_MCP:
            # 没有产品可挂的 AI 缺口没法走 K 简报——退到 photo 道让人决定
            row.lane = LANE_PHOTO
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------- 扫描


def _filled_by_k_asset(db: Session, req: SmImageRequest) -> UUID | None:
    if req.seed_product_id is None:
        return None
    rows = db.execute(
        select(KProductKnowledgeMediaAsset).where(
            KProductKnowledgeMediaAsset.product_id == req.seed_product_id,
            KProductKnowledgeMediaAsset.status == "available",
            KProductKnowledgeMediaAsset.asset_type == "image",
        )
    ).scalars()
    for row in rows:
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        if req.lane == LANE_MCP and req.k_position is not None:
            try:
                if int(meta.get("position") or 0) == int(req.k_position):
                    return row.id
            except (TypeError, ValueError):
                continue
        elif req.lane == LANE_PHOTO and row.asset_role == req.role and row.created_at and row.created_at >= req.created_at:
            return row.id
    return None


def sweep(db: Session, scope: KScopeContext, *, today: date | None = None) -> dict[str, int]:
    """关已填的、临期换柱、久拖降级。**不 commit**。返回本轮动作计数。"""
    today = today or date.today()
    counts = {"filled": 0, "swapped": 0, "dormant": 0}
    open_rows = list(
        db.execute(
            apply_scope_filters(select(SmImageRequest), SmImageRequest, scope).where(SmImageRequest.status == "open")
        ).scalars()
    )
    for req in open_rows:
        asset_id = _filled_by_k_asset(db, req)
        if asset_id is not None:
            req.status = "filled"
            req.filled_asset_id = asset_id
            req.filled_at = datetime.now(UTC)
            counts["filled"] += 1
            if req.slot_id is not None:
                slot = db.get(SmCalendarSlot, req.slot_id)
                if slot is not None and slot.status in ("planned", "swapped"):
                    plan = dict(slot.media_plan_json or {})
                    ids = list(plan.get("asset_ids") or [])
                    if str(asset_id) not in ids:
                        ids.append(str(asset_id))
                    plan["asset_ids"] = ids
                    plan["gap"] = None
                    slot.media_plan_json = plan
                    if slot.status == "swapped":
                        slot.status = "planned"
            continue
        created_day = req.created_at.date() if req.created_at else today
        if (today - created_day).days >= GAP_DORMANT_AFTER_DAYS:
            req.status = "dormant"
            counts["dormant"] += 1
            continue
        if req.slot_id is not None and (req.due_day - today).days <= GAP_SWAP_LEAD_DAYS:
            slot = db.get(SmCalendarSlot, req.slot_id)
            if slot is not None and slot.status == "planned" and slot.post_id is None:
                _swap_slot(db, scope, slot, reason=f"{PILLAR_LABELS.get(req.pillar, req.pillar)}位缺图到期，换支柱")
                counts["swapped"] += 1
                # 缺口单本身保留，让人知道那张图还是缺的
                req.slot_id = None
    return counts


def _swap_slot(db: Session, scope: KScopeContext, slot: SmCalendarSlot, *, reason: str) -> None:
    """临期缺图：换成一个有库存的支柱（用排期器的挑源逻辑）。找不到就 blocked。"""
    from . import planner

    ctx = planner.load_context(db, scope, start_day=slot.day, days=1)
    prof = planner.profile(slot.platform)
    spec = planner.SlotSpec(
        day=slot.day, platform=slot.platform, slot_index=slot.slot_index, window_pt=slot.window_pt,
        pillar=slot.pillar, post_kind=str((slot.media_plan_json or {}).get("post_kind") or ""),
    )
    for pillar in planner.FALLBACK_PILLARS:
        if pillar == slot.pillar or prof.pillar_mix.get(pillar, 0) <= 0:
            continue
        spec.pillar = pillar
        if planner._assign_source(ctx, spec, prof):
            slot.pillar = spec.pillar
            slot.source_type, slot.source_id, slot.seed_product_id = spec.source_type, spec.source_id, spec.seed_product_id
            slot.label = spec.label[:255]
            slot.status = "swapped"
            slot.swap_reason = reason
            plan = dict(slot.media_plan_json or {})
            plan.update({"asset_ids": [], "gap": None, "post_kind": planner._post_kind_for(spec.pillar, slot.platform)})
            slot.media_plan_json = plan
            return
    slot.status = "blocked"
    slot.swap_reason = f"{reason}；无可换支柱"


__all__ = ["mcp_prompt", "next_social_position", "open_gap", "shot_list", "sweep"]
