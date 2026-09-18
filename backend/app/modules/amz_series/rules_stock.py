"""库存规则(殷素素 D):库存能撑几天 / 已经断货。计划 A2 的八条 D 规则里最后两条,等库存数据接上才有。

底数:amz_inventory_daily 最新一张(≤ 2 天前的才算数)+ 最近 14 天日均销量(优先销售与流量报表按 ASIN,
没有就用交易一览按 SKU)。能撑的天数 = (可售 + 在途) ÷ 日均。

- 已断货(可售 0、最近 14 天有卖)→ bad:停这个 SKU 的广告,不然花钱把人送去看「暂时缺货」;
- 撑不到 7 天 → bad:马上降广告保排名(断货掉排名比少卖几单贵得多),催补货;
- 撑不到 21 天 → warn:别在这时候加预算冲量。
不 commit。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .constants import EMPLOYEE_D
from .models import AmzInventoryDaily, AmzProduct, AmzSalesDaily, AmzTransaction
from .rules import SuggestionDraft, product_line_of

SNAP_MAX_AGE_DAYS = 2
RATE_WINDOW_DAYS = 14
BAD_DAYS = 7
WARN_DAYS = 21
ORDER_TYPES = ("Order", "Bestellung")
ACTION_STOCKOUT = "stockout"
ACTION_STOCK_COVER = "stock_cover"


def daily_rates(db: Session, store_code: str, *, today: date) -> tuple[dict[str, float], dict[str, float]]:
    """({asin: 日均件数}, {sku: 日均件数})。"""
    since = today - timedelta(days=RATE_WINDOW_DAYS)
    by_asin = {
        asin: int(units or 0) / RATE_WINDOW_DAYS
        for asin, units in db.execute(
            select(AmzSalesDaily.child_asin, func.sum(AmzSalesDaily.units_ordered)).where(AmzSalesDaily.store_code == store_code, AmzSalesDaily.child_asin != "", AmzSalesDaily.report_date > since).group_by(AmzSalesDaily.child_asin)
        ).all()
    }
    by_sku = {
        sku: int(qty or 0) / RATE_WINDOW_DAYS
        for sku, qty in db.execute(
            select(AmzTransaction.sku, func.sum(AmzTransaction.quantity)).where(AmzTransaction.store_code == store_code, AmzTransaction.txn_type.in_(ORDER_TYPES), AmzTransaction.sku.is_not(None), func.date(AmzTransaction.posted_at) > since).group_by(AmzTransaction.sku)
        ).all()
    }
    return by_asin, by_sku


def cover_days(on_hand: int, rate: float) -> float | None:
    return round(on_hand / rate, 1) if rate > 0 else None


def cover_groups(db: Session, store_code: str) -> tuple[date | None, list[dict[str, Any]]]:
    """按 ASIN 合并最新库存快照:同一个 ASIN 常挂好几个 SKU(老 SKU 0 件、新 SKU 有货),按 SKU 判会误报断货。"""
    snap = db.scalar(select(func.max(AmzInventoryDaily.snap_date)).where(AmzInventoryDaily.store_code == store_code))
    if snap is None:
        return None, []
    by_asin, by_sku = daily_rates(db, store_code, today=snap)
    groups: dict[str, dict[str, Any]] = {}
    for row in db.scalars(select(AmzInventoryDaily).where(AmzInventoryDaily.store_code == store_code, AmzInventoryDaily.snap_date == snap).order_by(AmzInventoryDaily.sku)):
        key = row.asin or f"sku:{row.sku}"
        g = groups.setdefault(key, {"asin": row.asin, "skus": [], "fulfillable": 0, "inbound": 0, "reserved": 0, "sku_rate": 0.0})
        g["skus"].append(row.sku)
        g["fulfillable"] += int(row.fulfillable or 0)
        g["inbound"] += int(row.inbound or 0)
        g["reserved"] += int(row.reserved or 0)
        g["sku_rate"] += by_sku.get(row.sku, 0.0)
    out = []
    for g in groups.values():
        rate = by_asin.get(g["asin"] or "") or g["sku_rate"]
        # 主 SKU = 有货的那个(没有就第一个),建议里写它
        stocked = [sku for sku in g["skus"]]
        out.append({**g, "sku": stocked[0], "daily_rate": round(rate, 2), "days_cover": cover_days(g["fulfillable"] + g["inbound"], rate), "snap_date": snap.isoformat()})
    return snap, out


def rule_stock(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    """as_of 是广告数据的最后一天;库存要看「今天」,所以用最新快照日判,快照太旧就不说话。按 ASIN 判(见 cover_groups)。"""
    snap, groups = cover_groups(db, store_code)
    if snap is None:
        return []
    latest_any = db.scalar(select(func.max(AmzInventoryDaily.snap_date)))
    if latest_any is not None and (latest_any - snap).days > SNAP_MAX_AGE_DAYS:
        return []
    lines = {p.sku: p.product_line for p in db.scalars(select(AmzProduct).where(AmzProduct.store_code == store_code))}
    drafts: list[SuggestionDraft] = []
    for g in groups:
        rate = g["daily_rate"]
        if rate <= 0:
            continue
        name = g["asin"] or g["sku"]
        skus = "、".join(g["skus"])
        line = next((lines[s] for s in g["skus"] if s in lines), None) or product_line_of(skus)
        days = g["days_cover"]
        base = {"asin": g["asin"], "skus": g["skus"], "sku": g["sku"], "fulfillable": g["fulfillable"], "inbound": g["inbound"], "daily_rate": rate, "days_cover": days, "snap_date": snap.isoformat(), "product_line": line}
        if g["fulfillable"] == 0:
            drafts.append(
                SuggestionDraft(
                    employee=EMPLOYEE_D,
                    store_code=store_code,
                    action_type=ACTION_STOCKOUT,
                    severity="bad",
                    title=f"{name} 已断货(可售 0,在途 {g['inbound']}):先停它的广告",
                    why=f"SKU {skus} 合计可售 0;最近 {RATE_WINDOW_DAYS} 天日均卖 {rate:.1f} 件。断货还开着广告,点进来的人看到「暂时缺货」,钱白花,转化率还被拉低。",
                    prediction="停这个商品的所有广告组;到货可售后第一天恢复,出价先回到断货前的八成,一周内爬回去。",
                    subject=f"stockout|{name}|{snap.isoformat()}",
                    evidence=base,
                )
            )
        elif days is not None and days < WARN_DAYS:
            bad = days < BAD_DAYS
            drafts.append(
                SuggestionDraft(
                    employee=EMPLOYEE_D,
                    store_code=store_code,
                    action_type=ACTION_STOCK_COVER,
                    severity="bad" if bad else "warn",
                    title=f"{name} 库存只够 {days:g} 天(可售 {g['fulfillable']} + 在途 {g['inbound']},日均 {rate:.1f})",
                    why=("撑不到一周:断货掉排名比少卖几单贵得多。" if bad else "撑不到三周:这时候加预算冲量,等于加速断货。") + f" SKU:{skus}。广告的活是保住排名,不是把最后几件卖快。",
                    prediction=("马上把这个商品的广告降到只留精准核心词、出价降两成;催补货。" if bad else "预算不加、不开新活动;在途的货到了再说。") + f" 按日均 {rate:.1f} 件,补货要赶在 {days:g} 天内可售。",
                    subject=f"cover|{name}|{snap.isoformat()}",
                    evidence=base,
                )
            )
    return drafts


def cover_table(db: Session, store_code: str) -> list[dict[str, Any]]:
    """店铺页用:每个商品(ASIN)能撑几天。"""
    _snap, groups = cover_groups(db, store_code)
    return [{"sku": "、".join(g["skus"]), "asin": g["asin"], "fulfillable": g["fulfillable"], "inbound": g["inbound"], "reserved": g["reserved"], "daily_rate": g["daily_rate"], "days_cover": g["days_cover"], "snap_date": g["snap_date"]} for g in groups]


__all__ = ["ACTION_STOCKOUT", "ACTION_STOCK_COVER", "cover_days", "cover_groups", "cover_table", "daily_rates", "rule_stock"]
