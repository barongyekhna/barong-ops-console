"""选图器：按「支柱 × 平台」需求单从 K 资产里筛图；筛不到就说缺什么。

全是确定性条件（报告 03.7 第二步）：
源头关联资产 → asset_role 匹配 → 产品品牌门 clean（或人工放行）→ 该资产不在
产品品牌审计的 image_violations 里（除非已被放行）→ 这个平台没用过这个文件
（sm_media_usage）→ 没被驳回给同平台同支柱（sm_rejections）→ 比例：K 成品图是
方图，需要竖图/4:5 时交给版式渲染补，不硬裁。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..k_series.product_knowledge.models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
)
from ..k_series.product_knowledge.scope_shim import KScopeContext, apply_scope_filters
from .constants import (
    ASSET_ROLE_BRAND,
    ASSET_ROLE_FACTORY,
    ASSET_ROLE_SOCIAL_LAYOUT,
    LANE_LAYOUT,
    LANE_MCP,
    LANE_PHOTO,
    LAYOUT_PIPELINE_TAG,
    PILLAR_BRAND,
    PILLAR_FACTORY,
    PILLAR_GUIDE,
    REAL_PHOTO_ROLES,
)
from .models import SmMediaUsage, SmRejection
from .profiles import ImageRequirement, image_requirement


@dataclass
class Selection:
    asset_ids: list[UUID] = field(default_factory=list)
    # 需要版式渲染（补成竖图 / 叠字 / 字卡）
    needs_layout: bool = False
    text_card: bool = False
    # 缺口：lane + 说明；None = 够用
    gap_lane: str | None = None
    gap_role: str | None = None
    gap_count: int = 0
    gap_reason: str | None = None
    requirement: ImageRequirement | None = None

    def to_media_plan(self) -> dict[str, Any]:
        return {
            "asset_ids": [str(a) for a in self.asset_ids],
            "needs_layout": self.needs_layout,
            "text_card": self.text_card,
            "gap": (
                {"lane": self.gap_lane, "role": self.gap_role, "count": self.gap_count, "reason": self.gap_reason}
                if self.gap_lane
                else None
            ),
        }


def _used_asset_ids(db: Session, scope: KScopeContext, platform: str) -> set[UUID]:
    rows = db.execute(
        apply_scope_filters(select(SmMediaUsage.asset_id), SmMediaUsage, scope).where(
            SmMediaUsage.platform == platform
        )
    ).scalars()
    return set(rows)


def _rejected_asset_ids(db: Session, scope: KScopeContext, platform: str, pillar: str) -> set[UUID]:
    rows = db.execute(
        apply_scope_filters(select(SmRejection.asset_id), SmRejection, scope).where(
            SmRejection.platform == platform,
            SmRejection.pillar == pillar,
            SmRejection.asset_id.is_not(None),
        )
    ).scalars()
    return set(rows)


def _violating_asset_ids(product: KProductKnowledgeProduct | None) -> set[str]:
    """产品品牌审计里被判违规、且没被放行的图。"""
    if product is None:
        return set()
    audit = product.brand_audit_json if isinstance(product.brand_audit_json, dict) else {}
    override = audit.get("operator_override")
    if isinstance(override, dict) and override.get("enabled"):
        return set()
    ignored = {str(x) for x in (audit.get("ignored_findings") or [])}
    out: set[str] = set()
    for finding in audit.get("image_violations") or []:
        if not isinstance(finding, dict):
            continue
        asset_id = str(finding.get("asset_id") or "")
        position = str(finding.get("position") or "")
        category = str(finding.get("category") or finding.get("finding") or "")
        fingerprint = f"image::{asset_id}::{position}::{category}".lower()
        if asset_id and fingerprint not in ignored:
            out.add(asset_id)
    return out


def candidate_assets(
    db: Session,
    scope: KScopeContext,
    *,
    product: KProductKnowledgeProduct | None,
    roles: tuple[str, ...],
    platform: str,
    pillar: str,
    reserved: set[UUID] | None = None,
    include_layouts: bool = False,
) -> list[KProductKnowledgeMediaAsset]:
    """按需求单过滤后的候选，稳定排序（角色顺序 → 位号 → 创建时间）。"""
    if product is None and ASSET_ROLE_FACTORY not in roles and ASSET_ROLE_BRAND not in roles:
        return []
    query = select(KProductKnowledgeMediaAsset).where(
        KProductKnowledgeMediaAsset.status == "available",
        KProductKnowledgeMediaAsset.asset_type == "image",
        KProductKnowledgeMediaAsset.asset_role.in_(list(roles)),
    )
    if product is not None:
        query = query.where(KProductKnowledgeMediaAsset.product_id == product.id)
    else:
        # 工厂 / 品牌图不绑具体产品：只在本 workspace 的产品下找
        scoped_products = apply_scope_filters(
            select(KProductKnowledgeProduct.id), KProductKnowledgeProduct, scope
        )
        query = query.where(KProductKnowledgeMediaAsset.product_id.in_(scoped_products))
    rows = list(db.execute(query.order_by(KProductKnowledgeMediaAsset.created_at.asc())).scalars())
    used = _used_asset_ids(db, scope, platform)
    rejected = _rejected_asset_ids(db, scope, platform, pillar)
    violating = _violating_asset_ids(product)
    reserved = reserved or set()
    role_order = {role: idx for idx, role in enumerate(roles)}
    out = []
    for row in rows:
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        if not include_layouts and meta.get("render_pipeline") == LAYOUT_PIPELINE_TAG:
            continue
        if row.id in used or row.id in rejected or row.id in reserved or str(row.id) in violating:
            continue
        if row.asset_role in REAL_PHOTO_ROLES and meta.get("ai_generated"):
            continue
        out.append(row)
    out.sort(
        key=lambda r: (
            role_order.get(r.asset_role, 99),
            int((r.metadata_json or {}).get("position") or 0) if isinstance(r.metadata_json, dict) else 0,
            r.created_at or 0,
        )
    )
    return out


def select_images(
    db: Session,
    scope: KScopeContext,
    *,
    pillar: str,
    platform: str,
    product: KProductKnowledgeProduct | None,
    reserved: set[UUID] | None = None,
) -> Selection:
    req = image_requirement(pillar, platform)
    if req is None:
        return Selection(gap_lane=LANE_PHOTO, gap_reason="no_requirement", requirement=None)
    candidates = candidate_assets(
        db, scope, product=product, roles=req.roles, platform=platform, pillar=pillar, reserved=reserved
    )
    chosen = [row.id for row in candidates[: req.count_max]]
    selection = Selection(asset_ids=chosen, requirement=req)
    # K 成品图是方图；Pinterest 2:3 / IG 4:5 一律走版式渲染补白 + 叠字。
    selection.needs_layout = bool(chosen) and (req.ratio != "1:1" or req.overlay)
    if len(chosen) >= req.count_min:
        return selection
    missing = req.count_min - len(chosen)
    if req.text_card_ok and pillar in (PILLAR_GUIDE, PILLAR_FACTORY) and not req.must_be_real:
        # 导购没有场景图时用纯字卡顶上（版式道，当场自动填）
        selection.text_card = True
        selection.needs_layout = True
        return selection
    if req.must_be_real or pillar == PILLAR_BRAND:
        selection.gap_lane = LANE_PHOTO
        selection.gap_reason = "需要真照片，AI 不许画"
    else:
        selection.gap_lane = LANE_MCP
        selection.gap_reason = "缺场景图，交 Codex 精修通道"
    selection.gap_role = req.roles[0]
    selection.gap_count = missing
    if pillar == PILLAR_FACTORY and req.text_card_ok and product is None:
        # 没照片也没产品挂：只登记缺口，写手可用工艺事实配字卡
        selection.text_card = True
        selection.needs_layout = True
    return selection


__all__ = ["Selection", "candidate_assets", "select_images"]
