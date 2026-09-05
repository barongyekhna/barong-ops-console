"""排期器：什么时候发什么，由代码从库存和事件推出来，不问人、不靠模型。

四条规则叠加（报告 03.5 / skill §4 Step 8）：
1. 周模板打底（Instagram 按 weekday；Pinterest 按每天钉数混发，工厂钉只在周末）
2. 事件插队（新产品 3 天内 P1、新指南 14 天内 P2、缺货停排、季节加权、14 天无源头报卡住）
3. 轮换与冷却（同源头同平台 7 天；最久没发的优先）
4. 账号阶段（渠道 created_at 起 14 天铺货期：Pinterest 取每日下限）

**确定性**：同一份库存 + 同一份历史 + 同一个日期区间 → 同一张日历。排序键全是
稳定字段（sku / title / id），没有随机数。测试钉住。

纯函数核心 ``compute_slots`` 不碰数据库；``plan`` 负责装载上下文、跑选图器、落表。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..k_series.product_knowledge.scope_shim import KScopeContext, apply_scope_filters
from .constants import (
    ASSET_ROLE_DESCRIPTION,
    ASSET_ROLE_GALLERY,
    ASSET_ROLE_MAIN,
    PILLAR_BRAND,
    PILLAR_FACTORY,
    PILLAR_GUIDE,
    PILLAR_LABELS,
    PILLAR_PRODUCT,
    PILLAR_SCENE,
    PILLARS,
    PLAN_HORIZON_DAYS,
    PLANNER_VERSION,
    PLATFORM_FACEBOOK,
    PLATFORM_INSTAGRAM,
    PLATFORM_PINTEREST,
    PLATFORMS,
    POST_KIND_CAROUSEL,
    POST_KIND_MIRROR,
    POST_KIND_PIN,
    POST_KIND_SINGLE,
    PUNCTUATION_PILLARS,
    SEEDING_PERIOD_DAYS,
    SOURCE_CRAFT_FACT,
    SOURCE_GEO_ITEM,
    SOURCE_K_PRODUCT,
    SOURCE_NONE,
)
from .inventory import InventorySnapshot, load_inventory
from .models import SmCalendarSlot, SmChannel
from .profiles import PlatformProfile, image_requirement, profile
from .seasons_us import season_weights

logger = logging.getLogger(__name__)

# 指南一篇要出 3–6 张不同钉，冷却比产品短。
GUIDE_COOLDOWN_DAYS = 3
NEW_PRODUCT_WINDOW_DAYS = 3
NEW_GUIDE_WINDOW_DAYS = 14
PINS_PER_RESERVE_UNIT = 60
# 找不到模板支柱的源头时的兜底顺序。
FALLBACK_PILLARS: tuple[str, ...] = (PILLAR_GUIDE, PILLAR_PRODUCT, PILLAR_SCENE, PILLAR_FACTORY, PILLAR_BRAND)
_EPOCH = datetime(1970, 1, 1)


@dataclass
class SlotSpec:
    day: date
    platform: str
    slot_index: int
    window_pt: str | None
    pillar: str
    post_kind: str
    source_type: str = SOURCE_NONE
    source_id: UUID | None = None
    seed_product_id: UUID | None = None
    source_label: str = ""
    status: str = "planned"
    swap_reason: str | None = None
    mirror_of: tuple[date, int] | None = None  # Facebook 镜像的 Instagram 格

    @property
    def label(self) -> str:
        base = f"{self.day.isoformat()} · {self.platform} · {PILLAR_LABELS.get(self.pillar, self.pillar)}"
        return f"{base} · {self.source_label}" if self.source_label else base


@dataclass
class PlanContext:
    inventory: InventorySnapshot
    channels: dict[str, datetime]  # platform → created_at（账号阶段起点）
    # (source_type, source_id, platform) → 最近一次排/发的日期
    usage: dict[tuple[str, str, str], date] = field(default_factory=dict)
    # (platform, day) → 已存在的格数（幂等：只补空位）
    existing_counts: dict[tuple[str, date], int] = field(default_factory=dict)
    # platform → 该平台每根支柱在窗口内已排的数量（配额从现状接着算）
    pillar_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    # platform → 最近一次工厂/品牌帖的日期
    punctuation_last: dict[str, date] = field(default_factory=dict)
    # Instagram 在窗口内已存在的格（供 Facebook 镜像）：day → (slot_index, spec-like)
    instagram_slots: dict[date, list[SlotSpec]] = field(default_factory=dict)


# ---------------------------------------------------------------- 源头挑选


def _pick_product(ctx: PlanContext, *, platform: str, day: date, roles: tuple[str, ...], cooldown: int):
    candidates = []
    for p in ctx.inventory.products:
        if not p.in_stock or not p.brand_clean:
            continue
        if not any(p.asset_counts.get(role, 0) > 0 for role in roles):
            continue
        key = (SOURCE_K_PRODUCT, str(p.product_id), platform)
        last = ctx.usage.get(key)
        if last is not None and (day - last).days < cooldown:
            continue
        posted_before = p.last_posted.get(platform)
        is_new = (
            p.approved_at is not None
            and (day - p.approved_at.date()).days <= NEW_PRODUCT_WINDOW_DAYS
            and posted_before is None
        )
        candidates.append(((0 if is_new else 1), last or date.min, p.sku, p))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1], c[2]))
    return candidates[0][3]


def _pick_guide(ctx: PlanContext, *, platform: str, day: date):
    candidates = []
    for g in ctx.inventory.guides:
        key = (SOURCE_GEO_ITEM, str(g.item_id), platform)
        last = ctx.usage.get(key)
        if last is not None and (day - last).days < GUIDE_COOLDOWN_DAYS:
            continue
        is_new = g.published_at is not None and (day - g.published_at.date()).days <= NEW_GUIDE_WINDOW_DAYS
        candidates.append(((0 if is_new else 1), last or date.min, g.title, g))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1], c[2]))
    return candidates[0][3]


def _pick_fact(ctx: PlanContext, *, platform: str, day: date, cooldown: int):
    candidates = []
    for f in ctx.inventory.facts:
        key = (SOURCE_CRAFT_FACT, str(f.fact_id), platform)
        last = ctx.usage.get(key)
        if last is not None and (day - last).days < cooldown:
            continue
        candidates.append((last or date.min, f.topic, f.claim, f))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1], c[2]))
    return candidates[0][3]


def _assign_source(ctx: PlanContext, spec: SlotSpec, prof: PlatformProfile) -> bool:
    """给格子挑源头；挑到返回 True 并登记 usage，挑不到返回 False。"""
    cooldown = prof.cooldown_days_same_source
    if spec.pillar == PILLAR_PRODUCT:
        product = _pick_product(
            ctx, platform=spec.platform, day=spec.day, roles=(ASSET_ROLE_MAIN, ASSET_ROLE_GALLERY), cooldown=cooldown
        )
        if product is None:
            return False
        spec.source_type, spec.source_id, spec.seed_product_id = SOURCE_K_PRODUCT, product.product_id, product.product_id
        spec.source_label = product.sku
    elif spec.pillar == PILLAR_SCENE:
        product = _pick_product(
            ctx, platform=spec.platform, day=spec.day, roles=(ASSET_ROLE_DESCRIPTION,), cooldown=cooldown
        )
        if product is None:
            return False
        spec.source_type, spec.source_id, spec.seed_product_id = SOURCE_K_PRODUCT, product.product_id, product.product_id
        spec.source_label = f"{product.sku} 场景"
    elif spec.pillar == PILLAR_GUIDE:
        guide = _pick_guide(ctx, platform=spec.platform, day=spec.day)
        if guide is None:
            return False
        spec.source_type, spec.source_id, spec.seed_product_id = SOURCE_GEO_ITEM, guide.item_id, guide.seed_product_id
        spec.source_label = guide.title[:60]
    elif spec.pillar == PILLAR_FACTORY:
        fact = _pick_fact(ctx, platform=spec.platform, day=spec.day, cooldown=cooldown)
        if fact is None:
            return False
        spec.source_type, spec.source_id = SOURCE_CRAFT_FACT, fact.fact_id
        spec.seed_product_id = fact.product_ids[0] if fact.product_ids else None
        spec.source_label = fact.topic[:60]
    elif spec.pillar == PILLAR_BRAND:
        if ctx.inventory.brand_asset_count <= 0:
            return False
        spec.source_type, spec.source_id, spec.source_label = SOURCE_NONE, None, "品牌"
    else:  # pragma: no cover - 常量枚举之外
        return False
    if spec.source_id is not None:
        ctx.usage[(spec.source_type, str(spec.source_id), spec.platform)] = spec.day
    return True


# ---------------------------------------------------------------- 支柱挑选


def _pillar_allowed(ctx: PlanContext, *, platform: str, pillar: str, day: date, share: int) -> bool:
    if share <= 0:
        return False
    if pillar in PUNCTUATION_PILLARS:
        last = ctx.punctuation_last.get(platform)
        if last is not None and (day - last).days <= 1:
            return False
        if platform == PLATFORM_PINTEREST and pillar == PILLAR_FACTORY and day.weekday() < 5:
            return False
    return True


def _choose_pinterest_pillar(ctx: PlanContext, prof: PlatformProfile, day: date) -> str | None:
    counts = ctx.pillar_counts.setdefault(prof.platform, {})
    total = sum(counts.values())
    weights = season_weights(day)
    best: tuple[float, int, str] | None = None
    for order, pillar in enumerate(PILLARS):
        share = prof.pillar_mix.get(pillar, 0)
        if not _pillar_allowed(ctx, platform=prof.platform, pillar=pillar, day=day, share=share):
            continue
        target = share / 100.0 * weights.get(pillar, 1.0)
        deficit = target * (total + 1) - counts.get(pillar, 0)
        key = (-deficit, order, pillar)
        if best is None or key < best:
            best = key
    return best[2] if best else None


def _pinterest_slots_per_day(ctx: PlanContext, prof: PlatformProfile, day: date) -> int:
    low, high = prof.per_day
    created = ctx.channels.get(prof.platform)
    if created is not None and (day - created.date()).days < prof.seeding_days:
        return low
    reserve = ctx.inventory.summary()["pin_reserve_estimate"]
    return max(low, min(high, reserve // PINS_PER_RESERVE_UNIT))


def _instagram_pillar(ctx: PlanContext, prof: PlatformProfile, day: date) -> str | None:
    pillar = prof.weekly_template.get(day.weekday())
    if pillar is None:
        return None
    if pillar == PILLAR_FACTORY:
        # 每月第一个周六给品牌（5% ≈ 一月一条），前提是有品牌图。
        if day.day <= 7 and ctx.inventory.brand_asset_count > 0:
            return PILLAR_BRAND
    return pillar


def _pillars_by_deficit(ctx: PlanContext, prof: PlatformProfile, day: date) -> list[str]:
    """按「离配比还差多少」从大到小排的可用支柱。兜底换柱按这个顺序，
    这样缺源头时配比往最欠的支柱倾斜，而不是一律灌进导购。"""
    counts = ctx.pillar_counts.setdefault(prof.platform, {})
    total = sum(counts.values())
    weights = season_weights(day)
    scored: list[tuple[float, int, str]] = []
    for order, pillar in enumerate(PILLARS):
        share = prof.pillar_mix.get(pillar, 0)
        if not _pillar_allowed(ctx, platform=prof.platform, pillar=pillar, day=day, share=share):
            continue
        target = share / 100.0 * weights.get(pillar, 1.0)
        scored.append((-(target * (total + 1) - counts.get(pillar, 0)), order, pillar))
    scored.sort()
    return [pillar for _deficit, _order, pillar in scored]


def _fill_with_fallback(ctx: PlanContext, spec: SlotSpec, prof: PlatformProfile, wanted: str) -> None:
    """模板要的支柱没源头时按「最欠配比」顺序换；全都没有 → blocked。"""
    spec.pillar = wanted
    if _assign_source(ctx, spec, prof):
        return
    ordered = [p for p in _pillars_by_deficit(ctx, prof, spec.day) if p != wanted]
    ordered += [p for p in FALLBACK_PILLARS if p not in ordered and p != wanted and prof.pillar_mix.get(p, 0) > 0]
    for pillar in ordered:
        if not _pillar_allowed(ctx, platform=spec.platform, pillar=pillar, day=spec.day, share=prof.pillar_mix.get(pillar, 0)):
            continue
        spec.pillar = pillar
        if _assign_source(ctx, spec, prof):
            spec.swap_reason = f"{PILLAR_LABELS[wanted]}无可发源头，换成{PILLAR_LABELS[pillar]}"
            return
    spec.pillar = wanted
    spec.status = "blocked"
    spec.swap_reason = "no_source"


def _post_kind_for(pillar: str, platform: str) -> str:
    if platform == PLATFORM_PINTEREST:
        return POST_KIND_PIN
    if platform == PLATFORM_FACEBOOK:
        return POST_KIND_MIRROR
    req = image_requirement(pillar, platform)
    if req is not None:
        return req.post_kind
    return POST_KIND_CAROUSEL if pillar in (PILLAR_GUIDE, PILLAR_PRODUCT) else POST_KIND_SINGLE


def _record(ctx: PlanContext, spec: SlotSpec) -> None:
    if spec.status == "blocked":
        return
    counts = ctx.pillar_counts.setdefault(spec.platform, {})
    counts[spec.pillar] = counts.get(spec.pillar, 0) + 1
    if spec.pillar in PUNCTUATION_PILLARS:
        ctx.punctuation_last[spec.platform] = spec.day
    if spec.platform == PLATFORM_INSTAGRAM:
        ctx.instagram_slots.setdefault(spec.day, []).append(spec)


# ---------------------------------------------------------------- 纯函数核心


def compute_slots(ctx: PlanContext, *, start_day: date, days: int = PLAN_HORIZON_DAYS) -> list[SlotSpec]:
    """给定上下文，算出窗口内**新增**的格子（已存在的 (platform, day) 不再补）。"""
    specs: list[SlotSpec] = []
    order = [p for p in (PLATFORM_INSTAGRAM, PLATFORM_PINTEREST, PLATFORM_FACEBOOK) if p in ctx.channels]
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        for platform in order:
            prof = profile(platform)
            if ctx.existing_counts.get((platform, day), 0) > 0:
                continue
            if platform == PLATFORM_PINTEREST:
                n = _pinterest_slots_per_day(ctx, prof, day)
                for idx in range(n):
                    window = prof.windows_pt[idx % len(prof.windows_pt)] if prof.windows_pt else None
                    pillar = _choose_pinterest_pillar(ctx, prof, day)
                    spec = SlotSpec(day=day, platform=platform, slot_index=idx, window_pt=window,
                                    pillar=pillar or PILLAR_GUIDE, post_kind=POST_KIND_PIN)
                    if pillar is None:
                        spec.status, spec.swap_reason = "blocked", "no_pillar"
                    else:
                        _fill_with_fallback(ctx, spec, prof, pillar)
                    spec.post_kind = POST_KIND_PIN
                    _record(ctx, spec)
                    specs.append(spec)
            elif platform == PLATFORM_INSTAGRAM:
                pillar = _instagram_pillar(ctx, prof, day)
                if pillar is None:
                    continue
                spec = SlotSpec(day=day, platform=platform, slot_index=0, window_pt=prof.windows_pt[0],
                                pillar=pillar, post_kind=_post_kind_for(pillar, platform))
                _fill_with_fallback(ctx, spec, prof, pillar)
                spec.post_kind = _post_kind_for(spec.pillar, platform)
                _record(ctx, spec)
                specs.append(spec)
            elif platform == PLATFORM_FACEBOOK:
                if prof.weekly_template.get(day.weekday()) != "mirror":
                    continue
                mirror = _latest_instagram_slot(ctx, day)
                spec = SlotSpec(day=day, platform=platform, slot_index=0, window_pt=prof.windows_pt[0],
                                pillar=mirror.pillar if mirror else PILLAR_GUIDE, post_kind=POST_KIND_MIRROR)
                if mirror is None:
                    spec.status, spec.swap_reason = "blocked", "no_instagram_post"
                else:
                    spec.source_type, spec.source_id = mirror.source_type, mirror.source_id
                    spec.seed_product_id, spec.source_label = mirror.seed_product_id, mirror.source_label
                    spec.mirror_of = (mirror.day, mirror.slot_index)
                _record(ctx, spec)
                specs.append(spec)
    return specs


def _latest_instagram_slot(ctx: PlanContext, day: date) -> SlotSpec | None:
    for back in range(0, 7):
        candidates = ctx.instagram_slots.get(day - timedelta(days=back)) or []
        usable = [s for s in candidates if s.status != "blocked"]
        if usable:
            return usable[-1]
    return None


# ---------------------------------------------------------------- 数据库包装


def load_context(db: Session, scope: KScopeContext, *, start_day: date, days: int) -> PlanContext:
    inventory = load_inventory(db, scope)
    channels = {
        row.platform: row.created_at
        for row in db.execute(
            apply_scope_filters(select(SmChannel), SmChannel, scope).where(SmChannel.status == "active")
        ).scalars()
        if row.platform in PLATFORMS
    }
    ctx = PlanContext(inventory=inventory, channels=channels)
    # 历史用量：最近一次发帖日期（按源头 × 平台）
    for p in inventory.products:
        for platform, at in p.last_posted.items():
            if at is not None:
                ctx.usage[(SOURCE_K_PRODUCT, str(p.product_id), platform)] = at.date()
    for g in inventory.guides:
        for platform, at in g.last_posted.items():
            if at is not None:
                ctx.usage[(SOURCE_GEO_ITEM, str(g.item_id), platform)] = at.date()
    for f in inventory.facts:
        for platform, at in f.last_posted.items():
            if at is not None:
                ctx.usage[(SOURCE_CRAFT_FACT, str(f.fact_id), platform)] = at.date()
    # 窗口（含往前 7 天冷却期）内已存在的格
    window_start = start_day - timedelta(days=7)
    window_end = start_day + timedelta(days=days)
    rows = list(
        db.execute(
            apply_scope_filters(select(SmCalendarSlot), SmCalendarSlot, scope).where(
                SmCalendarSlot.day >= window_start, SmCalendarSlot.day < window_end
            )
        ).scalars()
    )
    for row in rows:
        if row.day >= start_day:
            ctx.existing_counts[(row.platform, row.day)] = ctx.existing_counts.get((row.platform, row.day), 0) + 1
            if row.status != "blocked":
                counts = ctx.pillar_counts.setdefault(row.platform, {})
                counts[row.pillar] = counts.get(row.pillar, 0) + 1
        if row.source_id is not None and row.status != "blocked":
            key = (row.source_type, str(row.source_id), row.platform)
            if key not in ctx.usage or ctx.usage[key] < row.day:
                ctx.usage[key] = row.day
        if row.pillar in PUNCTUATION_PILLARS and row.status != "blocked":
            last = ctx.punctuation_last.get(row.platform)
            if last is None or last < row.day:
                ctx.punctuation_last[row.platform] = row.day
        if row.platform == PLATFORM_INSTAGRAM and row.status != "blocked":
            ctx.instagram_slots.setdefault(row.day, []).append(
                SlotSpec(
                    day=row.day, platform=row.platform, slot_index=row.slot_index, window_pt=row.window_pt,
                    pillar=row.pillar, post_kind=_post_kind_for(row.pillar, row.platform),
                    source_type=row.source_type, source_id=row.source_id,
                    seed_product_id=row.seed_product_id, source_label=row.label.split(" · ")[-1],
                )
            )
    return ctx


@dataclass
class PlanResult:
    run_id: UUID
    created: int
    blocked: int
    per_platform: dict[str, int]
    start_day: date
    days: int


# (spec, 刚建好的行) → media_plan。行先建再选图，缺口单才有 slot_id 可挂。
MediaPlanner = Callable[[SlotSpec, SmCalendarSlot], dict[str, Any] | None]


def plan(
    db: Session,
    scope: KScopeContext,
    *,
    start_day: date | None = None,
    days: int = PLAN_HORIZON_DAYS,
    media_planner: MediaPlanner | None = None,
) -> PlanResult:
    """排未来 ``days`` 天，幂等：只补 (platform, day) 还没有格子的日子。**不 commit**。"""
    start = start_day or date.today()
    ctx = load_context(db, scope, start_day=start, days=days)
    specs = compute_slots(ctx, start_day=start, days=days)
    run_id = uuid4()
    per_platform: dict[str, int] = {}
    blocked = 0
    # Facebook 镜像要指向 Instagram 那一行的 id：先落 IG，再落 FB。
    created_ids: dict[tuple[str, date, int], UUID] = {}
    for spec in sorted(specs, key=lambda s: (s.platform == PLATFORM_FACEBOOK, s.day, s.platform, s.slot_index)):
        media_plan: dict[str, Any] | None = None
        if spec.mirror_of is not None:
            mirror_id = created_ids.get((PLATFORM_INSTAGRAM, *spec.mirror_of))
            media_plan = {"mirror_of_slot": str(mirror_id) if mirror_id else None}
        row = SmCalendarSlot(
            id=uuid4(),
            workspace_key=scope.workspace_key,
            business_context=scope.business_context,
            scope_mode=scope.scope_mode,
            day=spec.day,
            platform=spec.platform,
            slot_index=spec.slot_index,
            window_pt=spec.window_pt,
            pillar=spec.pillar,
            label=spec.label[:255],
            source_type=spec.source_type,
            source_id=spec.source_id,
            seed_product_id=spec.seed_product_id,
            status=spec.status,
            swap_reason=spec.swap_reason,
            media_plan_json={**(media_plan or {}), "post_kind": spec.post_kind},
            planner_version=PLANNER_VERSION,
            plan_run_id=run_id,
        )
        db.add(row)
        created_ids[(spec.platform, spec.day, spec.slot_index)] = row.id
        if spec.status != "blocked" and spec.mirror_of is None and media_planner is not None:
            try:
                planned = media_planner(spec, row)
            except Exception:  # noqa: BLE001 - 选图失败不拖垮排期，格子留空由缺口单补
                logger.exception("media planner failed for %s", spec.label)
                planned = {"error": "media_planner_failed"}
            row.media_plan_json = {**(row.media_plan_json or {}), **(planned or {})}
        per_platform[spec.platform] = per_platform.get(spec.platform, 0) + 1
        if spec.status == "blocked":
            blocked += 1
    db.flush()
    return PlanResult(run_id=run_id, created=len(specs), blocked=blocked, per_platform=per_platform, start_day=start, days=days)


def pillar_mix_deviation(slots: list[SlotSpec], platform: str) -> dict[str, float]:
    """实际支柱占比 − 档案配比（百分点）。护栏：任一支柱偏差 >10 视为排法坏了。"""
    prof = profile(platform)
    mine = [s for s in slots if s.platform == platform and s.status != "blocked"]
    if not mine:
        return {}
    total = len(mine)
    out: dict[str, float] = {}
    for pillar in PILLARS:
        actual = sum(1 for s in mine if s.pillar == pillar) / total * 100
        out[pillar] = round(actual - prof.pillar_mix.get(pillar, 0), 1)
    return out


__all__ = [
    "PlanContext",
    "PlanResult",
    "SlotSpec",
    "compute_slots",
    "load_context",
    "pillar_mix_deviation",
    "plan",
]
