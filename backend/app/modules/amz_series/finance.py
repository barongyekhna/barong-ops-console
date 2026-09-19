"""殷乐乐(财务):每家店每天的真实利润、每个 SKU / 产品线的毛利、广告盈亏;成本表(人手填)。

口径(和 skills/e/finance-pnl.md 一致):
- 数据来自 amz_transactions(种子「交易一览」+ SP-API 财务事件,每行已按当天汇率带 fx_rate 折美元)。
- 订单行:销售额 = 商品销售额 + 运费收入 + 促销折让;亚马逊费用 = 这一行合计 − 销售额(佣金、FBA、其他交易费;税代收代缴互相抵掉)。
- 退款行 / 其他费用行(优惠券、秒杀、调整、清算……)按行合计计入当天。
- 月结费用(仓储、长期仓储、订阅)摊到发生日往前 30 天,每天一份,标「摊」。
- **不算利润**:银行转账、跨账户结算、后台「广告扣费」行(广告费按广告报表逐日算,再扣就重复)。
- 商品成本 = 当天售出件数 × 当时生效的(出厂 + 头程)元 × 当天人民币兑美元;**只用人在财务页填的成本**,没填就记「缺成本」,
  那一天的利润标「不完整」,绝不估。
- 广告费 = amz_ad_search_terms 当天花费;广告报表没覆盖到的日子标「广告费待接入」,不估。
不 commit。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AmzAdSearchTerm, AmzCost, AmzInventoryDaily, AmzProduct, AmzStore, AmzTransaction
from .rules import PRODUCT_LINE_LABELS, product_line_of

ORDER_TYPES = ("Order", "Bestellung")
REFUND_TYPES = ("Refund", "Erstattung")
EXCLUDED_TYPES = ("Transfer", "Übertrag", "Verbindlichkeit")
AD_CHARGE_RE = re.compile(r"cost of advertising|werbekosten", re.I)
ACCRUE_RE = re.compile(r"storage fee|lagergebühr|subscription|^beitrag$", re.I)
ACCRUE_DAYS = 30
ZERO = Decimal(0)


def _q(value: Decimal) -> float:
    return float(Decimal(value).quantize(Decimal("0.01")))


# ---------------------------------------------------------------- 成本表


def cost_rows(db: Session, store_code: str) -> dict[str, list[AmzCost]]:
    out: dict[str, list[AmzCost]] = defaultdict(list)
    for row in db.scalars(select(AmzCost).where(AmzCost.store_code == store_code).order_by(AmzCost.sku, AmzCost.effective_from)):
        out[row.sku].append(row)
    return out


def cost_on(history: list[AmzCost], day: date) -> Decimal | None:
    """当天生效的(出厂 + 头程)元 / 件;生效日期之前没有成本(不往前套)。财务页填第一笔时生效日期默认是这家店最早的数据日。"""
    current = None
    for row in history:
        if row.effective_from <= day:
            current = row
    return (Decimal(current.factory_cny) + Decimal(current.freight_cny)) if current is not None else None


def save_cost(db: Session, *, store_code: str, sku: str, factory_cny: Decimal, freight_cny: Decimal, effective_from: date, note: str | None, user_id: int | None) -> AmzCost:
    if factory_cny <= 0 or freight_cny < 0:
        raise ValueError("出厂价要大于 0,头程不能是负数")
    if effective_from > datetime.now(UTC).date():
        raise ValueError("生效日期不能晚于今天")
    sku = sku.strip()[:128]
    row = db.scalar(select(AmzCost).where(AmzCost.store_code == store_code, AmzCost.sku == sku, AmzCost.effective_from == effective_from))
    if row is None:
        row = AmzCost(store_code=store_code, sku=sku, effective_from=effective_from)
    row.factory_cny, row.freight_cny = factory_cny, freight_cny
    row.note = (note or "").strip()[:255] or None
    row.created_by_user_id = user_id
    db.add(row)
    db.flush()
    return row


def sku_catalog(db: Session, store_code: str, *, today: date | None = None) -> list[dict[str, Any]]:
    """成本表要列的 SKU:近 90 天卖过的 + 最新库存里有货的 + 名册里的;带近 30 天销量和成本历史。"""
    today = today or datetime.now(UTC).date()
    T = AmzTransaction
    sold = dict(
        db.execute(
            select(T.sku, func.sum(T.quantity)).where(T.store_code == store_code, T.txn_type.in_(ORDER_TYPES), T.sku.is_not(None), func.date(T.posted_at) > today - timedelta(days=90)).group_by(T.sku)
        ).all()
    )
    last_tx = db.scalar(select(func.max(T.posted_at)).where(T.store_code == store_code, T.txn_type.in_(ORDER_TYPES)))
    anchor = last_tx.date() if last_tx else today
    sold30 = dict(
        db.execute(
            select(T.sku, func.sum(T.quantity)).where(T.store_code == store_code, T.txn_type.in_(ORDER_TYPES), T.sku.is_not(None), func.date(T.posted_at) > anchor - timedelta(days=30)).group_by(T.sku)
        ).all()
    )
    snap = db.scalar(select(func.max(AmzInventoryDaily.snap_date)).where(AmzInventoryDaily.store_code == store_code))
    stocked = set(db.scalars(select(AmzInventoryDaily.sku).where(AmzInventoryDaily.store_code == store_code, AmzInventoryDaily.snap_date == snap, AmzInventoryDaily.fulfillable + AmzInventoryDaily.inbound > 0))) if snap else set()
    products = {p.sku: p for p in db.scalars(select(AmzProduct).where(AmzProduct.store_code == store_code))}
    history = cost_rows(db, store_code)
    skus = sorted(set(sold) | stocked | set(products) | set(history), key=lambda s: (-(int(sold30.get(s) or 0)), s))
    out = []
    for sku in skus:
        product = products.get(sku)
        rows = history.get(sku, [])
        latest = rows[-1] if rows else None
        out.append(
            {
                "sku": sku,
                "title": (product.title if product else None),
                "product_line": (product.product_line if product else product_line_of(sku)),
                "units_30d": int(sold30.get(sku) or 0),
                "units_90d": int(sold.get(sku) or 0),
                "in_stock": sku in stocked,
                "cost": None if latest is None else {"factory_cny": float(latest.factory_cny), "freight_cny": float(latest.freight_cny), "effective_from": latest.effective_from.isoformat()},
                "history": [{"factory_cny": float(r.factory_cny), "freight_cny": float(r.freight_cny), "effective_from": r.effective_from.isoformat(), "note": r.note} for r in rows],
            }
        )
    return out


# ---------------------------------------------------------------- 汇率


def cny_rates(db: Session) -> dict[date, Decimal]:
    from .fx import rate_map  # noqa: PLC0415

    return rate_map(db, base="CNY", quote="USD")


def sync_cny(db: Session, *, today: date | None = None, get: Any = None) -> dict[str, Any]:
    """人民币 → 美元(欧洲央行参考汇率,免费接口);补到今天。出网前收事务。"""
    from .fx import fetch_range, fill_calendar, upsert_rates  # noqa: PLC0415

    today = today or datetime.now(UTC).date()
    have = cny_rates(db)
    first_tx = db.scalar(select(func.min(func.date(AmzTransaction.posted_at))))
    start = (max(have) - timedelta(days=7)) if have else ((first_tx or today) - timedelta(days=10))
    db.commit()
    raw = fetch_range(start, today, base="CNY", quote="USD", get=get)
    written = upsert_rates(db, fill_calendar(raw, start, today), base="CNY", quote="USD")
    return {"cny_business_days": len(raw), "cny_rates_written": written}


# ---------------------------------------------------------------- 每日账


@dataclass
class DayBook:
    sales: Decimal = ZERO
    fees: Decimal = ZERO
    refunds: Decimal = ZERO
    other: Decimal = ZERO
    accrued: Decimal = ZERO
    cogs: Decimal = ZERO
    ads: Decimal = ZERO
    units: int = 0
    missing_cost_units: int = 0
    missing_skus: set[str] = field(default_factory=set)
    ads_missing: bool = False


@dataclass
class SkuBook:
    units: int = 0
    sales: Decimal = ZERO
    fees: Decimal = ZERO
    fba_fees: Decimal = ZERO
    refunds: Decimal = ZERO
    refund_orders: int = 0
    cogs: Decimal = ZERO
    missing_cost_units: int = 0


def _usd(row: AmzTransaction, value: Any) -> Decimal:
    return Decimal(value or 0) * Decimal(row.fx_rate or 1)


def ledger(db: Session, store_code: str, *, since: date, until: date) -> dict[str, Any]:
    """一家店 [since, until] 的逐日账 + 每个 SKU 的累计 + 每条产品线的广告。金额一律美元。"""
    store = db.get(AmzStore, store_code)
    currency = store.currency if store else "USD"
    T = AmzTransaction
    days: dict[date, DayBook] = {}
    d = since
    while d <= until:
        days[d] = DayBook()
        d += timedelta(days=1)
    skus: dict[str, SkuBook] = defaultdict(SkuBook)
    history = cost_rows(db, store_code)
    rates = cny_rates(db)
    from .fx import rate_on, usd_factor  # noqa: PLC0415

    rows = db.scalars(select(T).where(T.store_code == store_code, func.date(T.posted_at) >= since, func.date(T.posted_at) <= until + timedelta(days=ACCRUE_DAYS)))
    for row in rows:
        day = row.posted_at.date()
        if row.txn_type in EXCLUDED_TYPES or AD_CHARGE_RE.search(row.description or ""):
            continue
        total = _usd(row, row.total)
        if ACCRUE_RE.search(row.description or ""):
            share = total / ACCRUE_DAYS
            for back in range(ACCRUE_DAYS):
                target = day - timedelta(days=back)
                if target in days:
                    days[target].accrued += share
            continue
        if day not in days:
            continue
        book = days[day]
        if row.txn_type in ORDER_TYPES:
            sales = _usd(row, Decimal(row.product_sales or 0) + Decimal(row.shipping_credits or 0) + Decimal(row.promotional_rebates or 0))
            book.sales += sales
            book.fees += total - sales
            qty = int(row.quantity or 0)
            book.units += qty
            sku = row.sku or "(无 SKU)"
            sb = skus[sku]
            sb.units += qty
            sb.sales += sales
            sb.fees += total - sales
            sb.fba_fees += _usd(row, row.fba_fees)
            unit_cost = cost_on(history.get(sku, []), day)
            if unit_cost is None:
                book.missing_cost_units += qty
                book.missing_skus.add(sku)
                sb.missing_cost_units += qty
            else:
                rate = rate_on(rates, day)
                if rate is None:
                    book.missing_cost_units += qty
                    book.missing_skus.add(f"{sku}(缺汇率)")
                    sb.missing_cost_units += qty
                else:
                    cost = unit_cost * qty * rate
                    book.cogs += cost
                    sb.cogs += cost
        elif row.txn_type in REFUND_TYPES:
            book.refunds += total
            if row.sku:
                skus[row.sku].refunds += total
                skus[row.sku].refund_orders += 1
        else:
            book.other += total
    # 广告
    A = AmzAdSearchTerm
    last_ads = db.scalar(select(func.max(A.report_date)).where(A.store_code == store_code))
    factor = usd_factor(db, currency)
    lines: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"spend": ZERO, "ad_sales": ZERO})
    for day, campaign, spend, ad_sales in db.execute(
        select(A.report_date, A.campaign_name, func.sum(A.spend), func.sum(A.sales_7d)).where(A.store_code == store_code, A.report_date >= since, A.report_date <= until).group_by(A.report_date, A.campaign_name)
    ).all():
        usd = Decimal(spend or 0) * factor(day)
        if day in days:
            days[day].ads += usd
        line = product_line_of(campaign or "")
        lines[line]["spend"] += usd
        lines[line]["ad_sales"] += Decimal(ad_sales or 0) * factor(day)
    for day, book in days.items():
        book.ads_missing = last_ads is None or day > last_ads
    return {"store_code": store_code, "days": days, "skus": skus, "ad_lines": lines, "last_ads": last_ads}


def day_view(day: date, book: DayBook) -> dict[str, Any]:
    before_cogs = book.sales + book.fees + book.refunds + book.other + book.accrued
    profit = before_cogs - book.cogs - book.ads
    return {
        "date": day.isoformat(),
        "sales": _q(book.sales),
        "fees": _q(book.fees),
        "refunds": _q(book.refunds),
        "other": _q(book.other),
        "accrued": _q(book.accrued),
        "cogs": _q(book.cogs),
        "ads": _q(book.ads),
        "profit": _q(profit),
        "units": book.units,
        "profit_per_unit": _q(profit / book.units) if book.units else None,
        "missing_cost_units": book.missing_cost_units,
        "missing_skus": sorted(book.missing_skus),
        "ads_missing": book.ads_missing,
        "complete": book.missing_cost_units == 0 and not book.ads_missing,
    }


def data_since(db: Session, store_code: str) -> date | None:
    first = db.scalar(select(func.min(AmzTransaction.posted_at)).where(AmzTransaction.store_code == store_code))
    return first.date() if first else None


def data_until(db: Session, store_code: str) -> date | None:
    last = db.scalar(select(func.max(AmzTransaction.posted_at)).where(AmzTransaction.store_code == store_code, AmzTransaction.txn_type.in_(ORDER_TYPES)))
    return last.date() if last else None


def line_table(db: Session, store_code: str, book: dict[str, Any]) -> list[dict[str, Any]]:
    """每条产品线:扣广告前毛利、广告、扣完广告的利润、广告盈亏。缺成本的线不下结论。"""
    lines = {p.sku: p.product_line for p in db.scalars(select(AmzProduct).where(AmzProduct.store_code == store_code))}
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"units": 0, "sales": ZERO, "gross": ZERO, "missing_cost_units": 0})
    for sku, sb in book["skus"].items():
        line = lines.get(sku) or product_line_of(sku)
        a = agg[line]
        a["units"] += sb.units
        a["sales"] += sb.sales
        a["gross"] += sb.sales + sb.fees + sb.refunds - sb.cogs
        a["missing_cost_units"] += sb.missing_cost_units
    out = []
    for line in sorted(set(agg) | set(book["ad_lines"])):
        a = agg[line]
        ads = book["ad_lines"].get(line, {"spend": ZERO, "ad_sales": ZERO})
        complete = a["missing_cost_units"] == 0 and a["units"] > 0
        margin_pct = (a["gross"] / a["sales"]) if complete and a["sales"] else None
        ad_pnl = (ads["ad_sales"] * margin_pct - ads["spend"]) if margin_pct is not None else None
        out.append(
            {
                "product_line": line,
                "label": PRODUCT_LINE_LABELS.get(line, line),
                "units": a["units"],
                "sales": _q(a["sales"]),
                "gross_before_ads": _q(a["gross"]) if complete else None,
                "ad_spend": _q(ads["spend"]),
                "ad_sales": _q(ads["ad_sales"]),
                "profit_after_ads": _q(a["gross"] - ads["spend"]) if complete else None,
                "margin_pct": round(float(margin_pct) * 100, 1) if margin_pct is not None else None,
                "ad_pnl": _q(ad_pnl) if ad_pnl is not None else None,
                "missing_cost_units": a["missing_cost_units"],
            }
        )
    return out


def store_report(db: Session, store_code: str, *, days: int = 30) -> dict[str, Any]:
    until = data_until(db, store_code)
    if until is None:
        return {"store_code": store_code, "until": None, "days": [], "lines": [], "totals": None}
    since = until - timedelta(days=days - 1)
    book = ledger(db, store_code, since=since, until=until)
    day_rows = [day_view(d, b) for d, b in sorted(book["days"].items())]
    total = DayBook()
    for b in book["days"].values():
        for attr in ("sales", "fees", "refunds", "other", "accrued", "cogs", "ads"):
            setattr(total, attr, getattr(total, attr) + getattr(b, attr))
        total.units += b.units
        total.missing_cost_units += b.missing_cost_units
        total.missing_skus |= b.missing_skus
        total.ads_missing = total.ads_missing or b.ads_missing
    totals = day_view(until, total)
    totals.pop("date")
    return {"store_code": store_code, "since": since.isoformat(), "until": until.isoformat(), "last_ads": book["last_ads"].isoformat() if book["last_ads"] else None, "days": day_rows, "totals": totals, "lines": line_table(db, store_code, book)}


__all__ = ["ACCRUE_DAYS", "DayBook", "SkuBook", "cost_on", "cost_rows", "data_since", "data_until", "day_view", "ledger", "line_table", "save_cost", "sku_catalog", "store_report", "sync_cny"]
