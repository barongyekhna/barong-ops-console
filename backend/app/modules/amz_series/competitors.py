"""A4 竞品盯盘(殷长辰):每天一张 Keepa 快照,只报变化。

盯谁:
- 对手:事实表里填的「对手 ASIN」、推新页填的对手、人在竞品页手动加的;
- 自家:销售与流量报表里出现过的子 ASIN(评分、评论数和对手放在一起看才有意义)。

每天一次、每个 ASIN 一个 Keepa token(stats=1、不拉历史),台账桶 amz_keepa_tokens 默认每天 150 个封顶。
Keepa 钥匙按家规绑在四家广州公司 × amz.ops(alias keepa),复制自 R 系列那把。

变化规则(只和上一张快照比,不和很久以前比):
- 价格变动 ≥ 8%(降价 warn,涨价 info)→ 降价转殷素素看是否要守价 / 殷笑笑看锚定价;
- 从有货变断货 → warn,转殷素素:对手断货是加广告位的窗口;
- 评分变动 ≥ 0.1 → info;
- 评论数一周内涨 ≥ max(20, 10%) → info(可能在做评论活动,我们只记录,绝不跟);
- BSR 改善 ≥ 40% → info。
不 commit。
"""

from __future__ import annotations

import gzip
import json
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable
from uuid import uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ...services.api_key_orchestration import resolve_module_api_key_for_injection
from ...services.data_isolation import without_org_data_isolation
from .constants import EMPLOYEE_C, KEY_ALIAS_KEEPA, MODULE_KEY
from .models import AmzCompetitor, AmzCompetitorSnapshot, AmzFactSheet, AmzProduct, AmzSalesDaily, AmzStore
from .rules import PRODUCT_LINE_LABELS, SuggestionDraft

_LOGGER = logging.getLogger("amz.competitors")

KEEPA_DOMAIN = {"US": 1, "DE": 3}
KEEPA_EPOCH_OFFSET_MIN = 21_564_000
IDX_AMAZON, IDX_NEW, IDX_SALES_RANK, IDX_RATING, IDX_REVIEWS, IDX_BUY_BOX = 0, 1, 3, 16, 17, 18
BATCH = 20

PRICE_CHANGE_PCT = 8.0
RATING_CHANGE = Decimal("0.1")
REVIEW_JUMP_MIN = 20
REVIEW_JUMP_PCT = 10.0
BSR_IMPROVE_PCT = 40.0

ACTION_COMPETITOR_CHANGE = "competitor_change"


# ---------------------------------------------------------------- 盯谁


def upsert_competitor(db: Session, *, marketplace: str, asin: str, product_line: str, whose: str, source: str, label: str | None = None, actor_user_id: int | None = None) -> bool:
    asin = (asin or "").strip().upper()
    marketplace = (marketplace or "US").upper()
    if len(asin) != 10 or marketplace not in KEEPA_DOMAIN:
        return False
    stmt = pg_insert(AmzCompetitor).values(id=uuid4(), marketplace=marketplace, asin=asin, product_line=product_line, whose=whose, source=source, label=(label or "")[:120] or None, active=True, created_by_user_id=actor_user_id)
    result = db.execute(stmt.on_conflict_do_nothing(constraint="uq_amz_competitors_market_asin").returning(AmzCompetitor.id))
    return result.first() is not None


def sync_watchlist(db: Session) -> dict[str, int]:
    """从事实表的对手 ASIN 和销售报表里的自家子 ASIN 补名单(只加不删;人停用的不复活)。"""
    added = 0
    for sheet in db.scalars(select(AmzFactSheet)):
        store = db.get(AmzStore, sheet.store_code) if sheet.store_code else None
        marketplace = store.country if store is not None else "US"
        for asin in (sheet.facts_json or {}).get("competitor_asins") or []:
            added += int(upsert_competitor(db, marketplace=marketplace, asin=asin, product_line=sheet.product_line, whose="competitor", source="fact_sheet"))
    for store_code, asin in db.execute(select(AmzSalesDaily.store_code, AmzSalesDaily.child_asin).where(AmzSalesDaily.child_asin != "").distinct()).all():
        store = db.get(AmzStore, store_code)
        product = db.scalar(select(AmzProduct).where(AmzProduct.store_code == store_code, AmzProduct.asin == asin))
        added += int(upsert_competitor(db, marketplace=store.country if store else "US", asin=asin, product_line=product.product_line if product else "other", whose="ours", source="sales_report", label=store_code))
    db.flush()
    return {"added": added}


# ---------------------------------------------------------------- Keepa


def keepa_key(db: Session, store: AmzStore) -> tuple[str, str]:
    with without_org_data_isolation():
        ctx = resolve_module_api_key_for_injection(db, org_id=store.company_org_id, module_id=MODULE_KEY, key_alias=KEY_ALIAS_KEEPA)
    return (ctx.url or "https://api.keepa.com").rstrip("/"), str(ctx.query_param_value or "")


def _current(stats: dict[str, Any], idx: int) -> int | None:
    current = stats.get("current") or []
    if idx < len(current) and current[idx] is not None and current[idx] >= 0:
        return int(current[idx])
    return None


def parse_product(product: dict[str, Any]) -> dict[str, Any]:
    """Keepa product(stats=1)→ 快照字段。价格是分;评分 ×10;-1 = 无值。"""
    stats = product.get("stats") or {}
    price_cents = _current(stats, IDX_BUY_BOX) or _current(stats, IDX_NEW) or _current(stats, IDX_AMAZON)
    rating = _current(stats, IDX_RATING)
    reviews = _current(stats, IDX_REVIEWS)
    bsr = _current(stats, IDX_SALES_RANK)
    in_stock = price_cents is not None
    coupon = product.get("coupon")
    coupon_text = None
    if isinstance(coupon, list) and coupon and coupon[0]:
        value = int(coupon[0])
        coupon_text = f"{-value}%" if value < 0 else f"${value / 100:.2f}"
    return {
        "title": (product.get("title") or "")[:255] or None,
        "brand": (product.get("brand") or "")[:120] or None,
        "price": (Decimal(price_cents) / 100).quantize(Decimal("0.01")) if price_cents is not None else None,
        "in_stock": in_stock,
        "rating": (Decimal(rating) / 10).quantize(Decimal("0.1")) if rating is not None else None,
        "reviews": reviews,
        "bsr": bsr,
        "monthly_sold": int(product["monthlySold"]) if isinstance(product.get("monthlySold"), int) and product["monthlySold"] >= 0 else None,
        "coupon": coupon_text,
    }


def fetch_products(*, base_url: str, key: str, marketplace: str, asins: list[str], get: Callable[..., Any] | None = None) -> tuple[list[dict[str, Any]], int | None]:
    params = {"key": key, "domain": KEEPA_DOMAIN[marketplace], "asin": ",".join(asins), "stats": 1, "history": 0, "rating": 1}
    if get is None:
        with httpx.Client(timeout=60.0) as client:
            response = client.get(f"{base_url}/product", params=params)
    else:
        response = get(f"{base_url}/product", params=params)
    if response.status_code >= 400:
        raise RuntimeError(f"Keepa HTTP {response.status_code}: {response.text[:200].replace(key, '<KEY>')}")
    raw = response.content
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    payload = json.loads(raw.decode("utf-8"))
    return list(payload.get("products") or []), payload.get("tokensLeft")


def snapshot_marketplace(db: Session, store: AmzStore, *, today: date | None = None, get: Callable[..., Any] | None = None, budget: Callable[[int], bool] | None = None) -> dict[str, Any]:
    """这家店所在站点、今天还没拍的 ASIN 拍一张。一个站点每天只需要一家店拍(已拍的跳过)。"""
    today = today or datetime.now(UTC).date()
    marketplace = store.country
    if marketplace not in KEEPA_DOMAIN:
        return {"skipped": f"no keepa domain for {marketplace}"}
    watched = [c.asin for c in db.scalars(select(AmzCompetitor).where(AmzCompetitor.marketplace == marketplace, AmzCompetitor.active.is_(True)).order_by(AmzCompetitor.asin))]
    done = set(db.scalars(select(AmzCompetitorSnapshot.asin).where(AmzCompetitorSnapshot.marketplace == marketplace, AmzCompetitorSnapshot.snap_date == today)))
    todo = [a for a in watched if a not in done]
    if not todo:
        return {"marketplace": marketplace, "snapped": 0, "already": len(done)}
    base_url, key = keepa_key(db, store)
    db.commit()  # 出网前收事务
    snapped, tokens_left, skipped_budget = 0, None, 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i : i + BATCH]
        if budget is not None and not budget(len(batch)):
            skipped_budget += len(batch)
            continue
        products, tokens_left = fetch_products(base_url=base_url, key=key, marketplace=marketplace, asins=batch, get=get)
        rows = []
        for product in products:
            asin = str(product.get("asin") or "").upper()
            if not asin:
                continue
            fields = parse_product(product)
            rows.append({"marketplace": marketplace, "asin": asin, "snap_date": today, "raw_json": {"tokens_left": tokens_left}, **fields})
        if rows:
            stmt = pg_insert(AmzCompetitorSnapshot).values(rows)
            db.execute(stmt.on_conflict_do_nothing(constraint="uq_amz_competitor_snap_day"))
            db.commit()
            snapped += len(rows)
    return {"marketplace": marketplace, "snapped": snapped, "already": len(done), "skipped_budget": skipped_budget, "tokens_left": tokens_left}


# ---------------------------------------------------------------- 只报变化


def diff(prev: AmzCompetitorSnapshot | Any, now: AmzCompetitorSnapshot | Any, *, week_ago: Any | None = None) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    if prev.price is not None and now.price is not None and prev.price > 0:
        pct = float((now.price - prev.price) / prev.price * 100)
        if abs(pct) >= PRICE_CHANGE_PCT:
            changes.append({"kind": "price_drop" if pct < 0 else "price_rise", "severity": "warn" if pct < 0 else "info", "text": f"价格 ${prev.price} → ${now.price}({pct:+.0f}%)", "handoff": ["D", "A"] if pct < 0 else []})
    if prev.in_stock and now.in_stock is False:
        changes.append({"kind": "out_of_stock", "severity": "warn", "text": "断货了(没有任何在售报价)", "handoff": ["D"]})
    if prev.in_stock is False and now.in_stock:
        changes.append({"kind": "back_in_stock", "severity": "info", "text": f"补货回来了,现价 ${now.price}", "handoff": []})
    if prev.rating is not None and now.rating is not None and abs(now.rating - prev.rating) >= RATING_CHANGE:
        changes.append({"kind": "rating", "severity": "info", "text": f"评分 {prev.rating} → {now.rating}", "handoff": []})
    base = week_ago if week_ago is not None else prev
    if base.reviews is not None and now.reviews is not None:
        jump = now.reviews - base.reviews
        if jump >= max(REVIEW_JUMP_MIN, base.reviews * REVIEW_JUMP_PCT / 100):
            changes.append({"kind": "reviews_jump", "severity": "info", "text": f"评论一周内 {base.reviews} → {now.reviews}(+{jump})", "handoff": []})
    if prev.bsr and now.bsr and prev.bsr > 0:
        improve = (prev.bsr - now.bsr) / prev.bsr * 100
        if improve >= BSR_IMPROVE_PCT:
            changes.append({"kind": "bsr_up", "severity": "info", "text": f"排名 {prev.bsr} → {now.bsr}(上升 {improve:.0f}%)", "handoff": []})
    return changes


def home_store(db: Session, *, marketplace: str, product_line: str) -> str | None:
    """这条产品线在这个站点卖得最多的那家店;没有就站点第一家店。"""
    stores = list(db.scalars(select(AmzStore).where(AmzStore.country == marketplace, AmzStore.status == "active").order_by(AmzStore.store_code)))
    if not stores:
        return None
    best, best_units = stores[0].store_code, -1
    for store in stores:
        units = sum(int((p.metadata_json or {}).get("units_total") or 0) for p in db.scalars(select(AmzProduct).where(AmzProduct.store_code == store.store_code, AmzProduct.product_line == product_line)))
        if units > best_units:
            best, best_units = store.store_code, units
    return best


def rule_competitor_changes(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    """只给「这条产品线在这个站点的主场店」出草稿,免得三家店各报一遍。"""
    store = db.get(AmzStore, store_code)
    if store is None:
        return []
    drafts: list[SuggestionDraft] = []
    for comp in db.scalars(select(AmzCompetitor).where(AmzCompetitor.marketplace == store.country, AmzCompetitor.active.is_(True))):
        if home_store(db, marketplace=store.country, product_line=comp.product_line) != store_code:
            continue
        snaps = list(db.scalars(select(AmzCompetitorSnapshot).where(AmzCompetitorSnapshot.marketplace == comp.marketplace, AmzCompetitorSnapshot.asin == comp.asin).order_by(AmzCompetitorSnapshot.snap_date.desc()).limit(8)))
        if len(snaps) < 2:
            continue
        now, prev = snaps[0], snaps[1]
        week_ago = next((s for s in snaps if (now.snap_date - s.snap_date).days >= 6), None)
        for change in diff(prev, now, week_ago=week_ago):
            who = "自家" if comp.whose == "ours" else "对手"
            name = comp.label or now.brand or comp.asin
            handoff = change["handoff"]
            advice = {
                "price_drop": "判断:可能是促销或价格战;先看我们同词的点击份额有没有掉。建议:殷素素看要不要守住精准组出价,殷笑笑看锚定价和 coupon,别急着跟降。",
                "out_of_stock": "判断:这是窗口期,它的流量会溢出。建议:殷素素在这个对手的核心词和它的 ASIN 定向上临时加一档预算(护栏内),它补货就撤。",
                "reviews_jump": "判断:可能在做 Vine 或促销带评论。我们只记录,绝不跟做任何激励评论。",
            }.get(change["kind"], "判断:先记下,持续观察;连续两次同方向变化再动。")
            drafts.append(
                SuggestionDraft(
                    employee=EMPLOYEE_C,
                    store_code=store_code,
                    action_type=ACTION_COMPETITOR_CHANGE,
                    severity=change["severity"],
                    title=f"{who}「{name}」{comp.asin}:{change['text']}",
                    why=f"事实:{now.snap_date.isoformat()} 的 Keepa 快照,对比 {prev.snap_date.isoformat()}。{PRODUCT_LINE_LABELS.get(comp.product_line, comp.product_line)}线。{advice}",
                    prediction="建议:" + ("、".join({"D": "转殷素素", "A": "转殷笑笑"}[h] for h in handoff) if handoff else "我盯着,有新变化再说。"),
                    subject=f"{comp.marketplace}|{comp.asin}|{change['kind']}|{now.snap_date.isoformat()}",
                    evidence={"asin": comp.asin, "whose": comp.whose, "kind": change["kind"], "prev": {"date": prev.snap_date.isoformat(), "price": float(prev.price) if prev.price is not None else None, "rating": float(prev.rating) if prev.rating is not None else None, "reviews": prev.reviews, "bsr": prev.bsr, "in_stock": prev.in_stock}, "now": {"date": now.snap_date.isoformat(), "price": float(now.price) if now.price is not None else None, "rating": float(now.rating) if now.rating is not None else None, "reviews": now.reviews, "bsr": now.bsr, "in_stock": now.in_stock, "coupon": now.coupon}, "handoff": handoff},
                )
            )
    return drafts


def board(db: Session, *, marketplace: str | None = None) -> list[dict[str, Any]]:
    """竞品页:每个 ASIN 最新一张快照 + 上一张。"""
    q = select(AmzCompetitor).where(AmzCompetitor.active.is_(True))
    if marketplace:
        q = q.where(AmzCompetitor.marketplace == marketplace.upper())
    out = []
    for comp in db.scalars(q.order_by(AmzCompetitor.product_line, AmzCompetitor.whose, AmzCompetitor.asin)):
        snaps = list(db.scalars(select(AmzCompetitorSnapshot).where(AmzCompetitorSnapshot.marketplace == comp.marketplace, AmzCompetitorSnapshot.asin == comp.asin).order_by(AmzCompetitorSnapshot.snap_date.desc()).limit(2)))

        def _s(s: Any) -> dict[str, Any] | None:
            if s is None:
                return None
            return {"date": s.snap_date.isoformat(), "title": s.title, "brand": s.brand, "price": float(s.price) if s.price is not None else None, "in_stock": s.in_stock, "rating": float(s.rating) if s.rating is not None else None, "reviews": s.reviews, "bsr": s.bsr, "monthly_sold": s.monthly_sold, "coupon": s.coupon}

        out.append({"id": str(comp.id), "marketplace": comp.marketplace, "asin": comp.asin, "product_line": comp.product_line, "product_line_label": PRODUCT_LINE_LABELS.get(comp.product_line, comp.product_line), "whose": comp.whose, "label": comp.label, "source": comp.source, "latest": _s(snaps[0] if snaps else None), "previous": _s(snaps[1] if len(snaps) > 1 else None)})
    return out


__all__ = ["ACTION_COMPETITOR_CHANGE", "KEEPA_DOMAIN", "board", "diff", "fetch_products", "home_store", "keepa_key", "parse_product", "rule_competitor_changes", "snapshot_marketplace", "sync_watchlist", "upsert_competitor"]
