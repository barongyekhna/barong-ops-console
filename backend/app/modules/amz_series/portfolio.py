"""跨店协调(殷素素 D):三家店卖同一款货、在同一个词上互相抬价——谁来主打这个词,按数据分;同一批货的需求合起来看。

两件事:
1. **主场词**(rule_term_owner):同站点里 ≥2 家店都在买同一个搜索词(各自 ≥ 20 次点击),按「每花一块钱卖回多少」(ROAS)
   选主场店;明显更差的店(ROAS 不到主场的 70%)出一条「让位」建议——降出价或否定精准,把这个词让给主场店。
   只给「让位的那家店」出草稿(每家店每天跑自己的那份),证据里写全三家的数。
   这和殷笑笑的「页面接不住词」不矛盾:那条说页面该修,这条说修好之前别拿钱去抢;页面修好了,这个词会重新比。
2. **同批货需求合成**(demand_board):按产品线把各店最近 28 天的销量加起来 → 日均 → 合计库存能撑几天 → 该补多少
   (生产 + 头程按 LEAD_DAYS 估,再加 45 天安全库存)。排产建议永远 L1:只给人看,系统不下单。

不 commit。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .constants import EMPLOYEE_D
from .models import AmzAdSearchTerm, AmzInventoryDaily, AmzProduct, AmzStore, AmzTransaction
from .rules import PRODUCT_LINE_LABELS, SuggestionDraft, product_line_of

OWNER_WINDOW_DAYS = 28
OWNER_MIN_CLICKS = 20
OWNER_MIN_HOME_ORDERS = 3
OWNER_YIELD_RATIO = 0.7
OWNER_WARN_SPEND = Decimal("30")
OWNER_LIMIT = 6

DEMAND_WINDOW_DAYS = 28
LEAD_DAYS = 40  # 生产 + 头程的粗估;事实表里填了 lead_days 就用事实表的
SAFETY_DAYS = 45

ACTION_TERM_OWNER = "portfolio_yield"
ORDER_TYPES = ("Order", "Bestellung")


def _sibling_stores(db: Session, store_code: str) -> tuple[AmzStore | None, list[str]]:
    store = db.get(AmzStore, store_code)
    if store is None:
        return None, []
    return store, list(db.scalars(select(AmzStore.store_code).where(AmzStore.country == store.country, AmzStore.status == "active").order_by(AmzStore.store_code)))


def term_table(db: Session, *, stores: list[str], since: date, until: date) -> dict[str, dict[str, dict[str, Any]]]:
    """{词: {店: {clicks, orders, spend, sales, line}}}(词小写)。"""
    T = AmzAdSearchTerm
    rows = db.execute(
        select(T.store_code, func.lower(T.search_term), func.max(T.campaign_name), func.sum(T.clicks), func.sum(T.orders_7d), func.sum(T.spend), func.sum(T.sales_7d))
        .where(T.store_code.in_(stores), T.report_date > since, T.report_date <= until)
        .group_by(T.store_code, func.lower(T.search_term))
    ).all()
    out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for store_code, term, campaign, clicks, orders, spend, sales in rows:
        if not term or term.startswith("b0"):
            continue  # ASIN 定向不是词
        out[term][store_code] = {"clicks": int(clicks or 0), "orders": int(orders or 0), "spend": Decimal(spend or 0), "sales": Decimal(sales or 0), "campaign": campaign or ""}
    return out


def pick_owner(per_store: dict[str, dict[str, Any]]) -> tuple[str | None, list[str]]:
    """(主场店, 该让位的店)。只看点击够的店;主场要有单;让位 = ROAS 不到主场 70%。"""
    eligible = {s: v for s, v in per_store.items() if v["clicks"] >= OWNER_MIN_CLICKS and v["spend"] > 0}
    if len(eligible) < 2:
        return None, []

    def roas(v: dict[str, Any]) -> float:
        return float(v["sales"] / v["spend"]) if v["spend"] else 0.0

    home = max(eligible, key=lambda s: (roas(eligible[s]), eligible[s]["orders"], s))
    if eligible[home]["orders"] < OWNER_MIN_HOME_ORDERS:
        return None, []
    home_roas = roas(eligible[home])
    losers = sorted(s for s, v in eligible.items() if s != home and roas(v) < home_roas * OWNER_YIELD_RATIO)
    return home, losers


def rule_term_owner(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    store, siblings = _sibling_stores(db, store_code)
    if store is None or len(siblings) < 2:
        return []
    table = term_table(db, stores=siblings, since=as_of - timedelta(days=OWNER_WINDOW_DAYS), until=as_of)
    symbol = "€" if currency == "EUR" else "$"
    drafts: list[SuggestionDraft] = []
    for term, per_store in table.items():
        if store_code not in per_store:
            continue
        home, losers = pick_owner(per_store)
        if home is None or store_code not in losers:
            continue
        mine, theirs = per_store[store_code], per_store[home]
        my_roas = float(mine["sales"] / mine["spend"]) if mine["spend"] else 0.0
        home_roas = float(theirs["sales"] / theirs["spend"]) if theirs["spend"] else 0.0
        line = product_line_of(mine["campaign"] or term)
        drafts.append(
            SuggestionDraft(
                employee=EMPLOYEE_D,
                store_code=store_code,
                action_type=ACTION_TERM_OWNER,
                severity="warn" if mine["spend"] >= OWNER_WARN_SPEND else "info",
                title=f"「{term}」让给 {home} 主打:我们花 {symbol}{float(mine['spend']):.0f} 卖回 {my_roas:.1f} 倍,{home} 是 {home_roas:.1f} 倍",
                why=(
                    f"最近 {OWNER_WINDOW_DAYS} 天同一个词、同一款货:{store_code} {mine['clicks']} 次点击 {mine['orders']} 单,"
                    f"{home} {theirs['clicks']} 次点击 {theirs['orders']} 单。两家店在同一个词上竞价,等于自己抬自己的 CPC。"
                ),
                prediction=f"把这个词在 {store_code} 降到最低出价或否定精准;预计每 {OWNER_WINDOW_DAYS} 天省 {symbol}{float(mine['spend']):.0f},大部分单会落到 {home}。如果殷笑笑把这家店的页面修好了,这个词会重新比一次。",
                subject=f"owner|{term}",
                evidence={
                    "term": term,
                    "home_store": home,
                    "product_line": line,
                    "stores": {s: {"clicks": v["clicks"], "orders": v["orders"], "spend": float(v["spend"]), "sales": float(v["sales"])} for s, v in sorted(per_store.items())},
                },
            )
        )
    drafts.sort(key=lambda d: -d.evidence["stores"][store_code]["spend"])
    return drafts[:OWNER_LIMIT]


def owner_board(db: Session, *, marketplace: str, as_of: date | None = None) -> list[dict[str, Any]]:
    """看板用:这个站点所有被 ≥2 家店争的词,谁是主场、谁该让。"""
    stores = list(db.scalars(select(AmzStore.store_code).where(AmzStore.country == marketplace, AmzStore.status == "active")))
    if len(stores) < 2:
        return []
    as_of = as_of or db.scalar(select(func.max(AmzAdSearchTerm.report_date)).where(AmzAdSearchTerm.store_code.in_(stores)))
    if as_of is None:
        return []
    out = []
    for term, per_store in term_table(db, stores=stores, since=as_of - timedelta(days=OWNER_WINDOW_DAYS), until=as_of).items():
        contested = [s for s, v in per_store.items() if v["clicks"] >= OWNER_MIN_CLICKS]
        if len(contested) < 2:
            continue
        home, losers = pick_owner(per_store)
        spend = sum(float(v["spend"]) for v in per_store.values())
        out.append({"term": term, "home_store": home, "yield_stores": losers, "spend_total": round(spend, 2), "stores": {s: {"clicks": v["clicks"], "orders": v["orders"], "spend": float(v["spend"]), "sales": float(v["sales"])} for s, v in sorted(per_store.items())}})
    out.sort(key=lambda r: -r["spend_total"])
    return out[:30]


# ---------------------------------------------------------------- 同批货需求合成


def _sku_lines(db: Session, stores: list[str]) -> dict[tuple[str, str], str]:
    return {(p.store_code, p.sku): p.product_line for p in db.scalars(select(AmzProduct).where(AmzProduct.store_code.in_(stores)))}


def demand_board(db: Session, *, marketplace: str, lead_days: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """每条产品线:各店最近 28 天卖了几件、合计日均、合计库存(有库存数据的店)、能撑几天、建议补多少。"""
    stores = list(db.scalars(select(AmzStore.store_code).where(AmzStore.country == marketplace, AmzStore.status == "active").order_by(AmzStore.store_code)))
    if not stores:
        return []
    lines = _sku_lines(db, stores)
    units: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    windows: dict[str, tuple[date, date]] = {}
    for store_code in stores:
        last = db.scalar(select(func.max(AmzTransaction.posted_at)).where(AmzTransaction.store_code == store_code, AmzTransaction.txn_type.in_(ORDER_TYPES)))
        if last is None:
            continue
        end = last.date()
        start = end - timedelta(days=DEMAND_WINDOW_DAYS)
        windows[store_code] = (start, end)
        for sku, qty in db.execute(
            select(AmzTransaction.sku, func.sum(AmzTransaction.quantity))
            .where(AmzTransaction.store_code == store_code, AmzTransaction.txn_type.in_(ORDER_TYPES), func.date(AmzTransaction.posted_at) > start)
            .group_by(AmzTransaction.sku)
        ).all():
            line = lines.get((store_code, sku or "")) or product_line_of(sku or "")
            units[line][store_code] += int(qty or 0)
    stock: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for store_code in stores:
        snap = db.scalar(select(func.max(AmzInventoryDaily.snap_date)).where(AmzInventoryDaily.store_code == store_code))
        if snap is None:
            continue
        for row in db.scalars(select(AmzInventoryDaily).where(AmzInventoryDaily.store_code == store_code, AmzInventoryDaily.snap_date == snap)):
            line = lines.get((store_code, row.sku)) or product_line_of(row.sku)
            slot = stock[line].setdefault(store_code, {"fulfillable": 0, "inbound": 0, "as_of": snap.isoformat()})
            slot["fulfillable"] += int(row.fulfillable or 0)
            slot["inbound"] += int(row.inbound or 0)
    out = []
    for line in sorted(set(units) | set(stock)):
        per_store = units.get(line, {})
        total = sum(per_store.values())
        daily = round(total / DEMAND_WINDOW_DAYS, 2)
        stocked = stock.get(line, {})
        on_hand = sum(v["fulfillable"] + v["inbound"] for v in stocked.values())
        covered_stores = sorted(stocked)
        # 只有「卖货的店都有库存数据」时才敢说能撑几天、该补多少——缺一家就是瞎算。
        selling = sorted(s for s, n in per_store.items() if n > 0)
        complete = bool(selling) and all(s in stocked for s in selling)
        lead = (lead_days or {}).get(line, LEAD_DAYS)
        days_cover = round(on_hand / daily, 1) if complete and daily > 0 else None
        reorder = max(0, round(daily * (lead + SAFETY_DAYS) - on_hand)) if complete and daily > 0 else None
        out.append(
            {
                "product_line": line,
                "label": PRODUCT_LINE_LABELS.get(line, line),
                "units_28d": dict(sorted(per_store.items())),
                "units_28d_total": total,
                "daily": daily,
                "stock": stocked,
                "stock_complete": complete,
                "stock_missing_stores": [s for s in selling if s not in stocked],
                "days_cover": days_cover,
                "lead_days": lead,
                "reorder_units": reorder,
                "windows": {s: [a.isoformat(), b.isoformat()] for s, (a, b) in windows.items() if s in per_store},
                "note": "排产建议永远 L1:只给人看,系统不下单。" if reorder else ("有店还没有库存数据(没接 SP-API),先不算能撑几天。" if selling and not complete else ""),
            }
        )
    out.sort(key=lambda r: -r["units_28d_total"])
    return out


__all__ = ["ACTION_TERM_OWNER", "LEAD_DAYS", "SAFETY_DAYS", "demand_board", "owner_board", "pick_owner", "rule_term_owner", "term_table"]
