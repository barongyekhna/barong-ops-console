"""汇率:欧洲央行参考汇率(经 Frankfurter 免费接口,无钥匙)→ amz_fx_rates → 欧元行按「当天」汇率折美元。

家规(界面拍板):欧元按当日汇率折美元,历史行按当天汇率。周末 / 节假日央行不出价,用之前最近一个工作日的。
种子期所有欧元交易行按固定 1.08 折(fx_source=seed_fixed);汇率一到位就把它们重算(fx_source=ecb)。
2026-09-17 实测:夏季 EUR/USD 在 1.14–1.15,1.08 让 01de 的美元数低估约 6%。

免费接口,不计费,不进台账;出网失败只记心跳失败,不改任何数。不 commit。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .models import AmzAdSearchTerm, AmzFxRate, AmzStore, AmzTransaction

_LOGGER = logging.getLogger("amz.fx")

SOURCE = "ecb"
API = "https://api.frankfurter.dev/v1"
SEED_FALLBACK = Decimal("1.08")


def fetch_range(start: date, end: date, *, base: str = "EUR", quote: str = "USD", get: Callable[..., Any] | None = None) -> dict[date, Decimal]:
    """{工作日: 汇率}。只含央行实际出价的日子。"""
    url = f"{API}/{start.isoformat()}..{end.isoformat()}"
    if get is None:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(url, params={"from": base, "to": quote})
    else:
        response = get(url, params={"from": base, "to": quote})
    response.raise_for_status()
    payload = response.json()
    out: dict[date, Decimal] = {}
    for day, rates in (payload.get("rates") or {}).items():
        value = (rates or {}).get(quote)
        if value is not None:
            out[date.fromisoformat(day)] = Decimal(str(value))
    return out


def fill_calendar(rates: dict[date, Decimal], start: date, end: date) -> dict[date, Decimal]:
    """补齐周末节假日:用之前最近一个工作日的价。开头没有前值的日子不补(宁缺不猜)。"""
    out: dict[date, Decimal] = {}
    last: Decimal | None = None
    day = start
    while day <= end:
        if day in rates:
            last = rates[day]
        if last is not None:
            out[day] = last
        day += timedelta(days=1)
    return out


def upsert_rates(db: Session, rates: dict[date, Decimal], *, base: str = "EUR", quote: str = "USD") -> int:
    if not rates:
        return 0
    now = datetime.now(UTC)
    rows = [{"rate_date": d, "base": base, "quote": quote, "rate": r, "source": SOURCE, "fetched_at": now} for d, r in rates.items()]
    stmt = pg_insert(AmzFxRate).values(rows)
    db.execute(stmt.on_conflict_do_update(index_elements=["rate_date", "base", "quote"], set_={"rate": stmt.excluded.rate, "source": stmt.excluded.source, "fetched_at": stmt.excluded.fetched_at}))
    return len(rows)


def rate_map(db: Session, *, base: str = "EUR", quote: str = "USD") -> dict[date, Decimal]:
    return {row.rate_date: Decimal(row.rate) for row in db.scalars(select(AmzFxRate).where(AmzFxRate.base == base, AmzFxRate.quote == quote))}


def rate_on(rates: dict[date, Decimal], day: date) -> Decimal | None:
    """当天没有就往前找最多 7 天。"""
    for back in range(8):
        value = rates.get(day - timedelta(days=back))
        if value is not None:
            return value
    return None


def latest_rate(db: Session, *, base: str = "EUR", quote: str = "USD") -> tuple[date, Decimal] | None:
    row = db.scalar(select(AmzFxRate).where(AmzFxRate.base == base, AmzFxRate.quote == quote).order_by(AmzFxRate.rate_date.desc()))
    return (row.rate_date, Decimal(row.rate)) if row is not None else None


def recompute_transactions(db: Session, *, store_code: str, currency: str) -> int:
    """把这家店的非美元交易行按当天汇率重算 total_usd(包括种子期的 seed_fixed 行)。"""
    if currency == "USD":
        return 0
    rates = rate_map(db, base=currency)
    changed = 0
    for row in db.scalars(select(AmzTransaction).where(AmzTransaction.store_code == store_code, AmzTransaction.currency == currency)):
        rate = rate_on(rates, row.posted_at.date())
        if rate is None:
            continue
        new_total = (Decimal(row.total) * rate).quantize(Decimal("0.01"))
        if row.fx_source != SOURCE or Decimal(row.fx_rate) != rate or Decimal(row.total_usd) != new_total:
            row.fx_rate = rate
            row.fx_source = SOURCE
            row.total_usd = new_total
            db.add(row)
            changed += 1
    db.flush()
    return changed


def sync_store(db: Session, store: AmzStore, *, today: date | None = None, get: Callable[..., Any] | None = None) -> dict[str, Any]:
    """补齐这家店数据期(广告最早一天 / 交易最早一天)到今天的汇率,再重算交易美元数。"""
    if store.currency == "USD":
        return {"skipped": "USD"}
    today = today or datetime.now(UTC).date()
    firsts = [
        db.scalar(select(func.min(AmzAdSearchTerm.report_date)).where(AmzAdSearchTerm.store_code == store.store_code)),
        db.scalar(select(func.min(func.date(AmzTransaction.posted_at))).where(AmzTransaction.store_code == store.store_code)),
    ]
    first = min([d for d in firsts if d is not None], default=today - timedelta(days=30))
    have = rate_map(db, base=store.currency)
    start = max(have) - timedelta(days=7) if have and min(have) <= first else first - timedelta(days=10)
    db.commit()  # 出网前收事务(worker 8 秒 idle 上限)
    raw = fetch_range(start, today, base=store.currency, get=get)
    filled = fill_calendar(raw, start, today)
    written = upsert_rates(db, filled, base=store.currency)
    recomputed = recompute_transactions(db, store_code=store.store_code, currency=store.currency)
    latest = latest_rate(db, base=store.currency)
    return {"fetched_business_days": len(raw), "rates_written": written, "transactions_recomputed": recomputed, "latest": [latest[0].isoformat(), float(latest[1])] if latest else None}


def usd_factor(db: Session, currency: str, *, cache: dict[str, dict[date, Decimal]] | None = None) -> Callable[[date], Decimal]:
    """给汇总用:返回「某天 → 折美元系数」。USD 恒 1;没有汇率时退回 1.08 并不报错(页面会标注)。"""
    if currency == "USD":
        return lambda _day: Decimal(1)
    if cache is not None and currency in cache:
        rates = cache[currency]
    else:
        rates = rate_map(db, base=currency)
        if cache is not None:
            cache[currency] = rates
    return lambda day: rate_on(rates, day) or SEED_FALLBACK


__all__ = ["API", "SEED_FALLBACK", "SOURCE", "fetch_range", "fill_calendar", "latest_rate", "rate_map", "rate_on", "recompute_transactions", "sync_store", "upsert_rates", "usd_factor"]
