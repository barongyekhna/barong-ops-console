"""A1 报表同步:销售与流量(按天按 ASIN)、SQP(按周按 ASIN)。解析 + upsert;出网在 clients.sp_api。

品牌分析这一个角色就够拉这两份报表——它们是 A 系列最值钱的两份:
- 销售与流量 = 自然+广告的总盘子、每个 ASIN 的 sessions / 转化率 / 购物车赢率(TACOS 的分母,笑笑诊断的依据);
- SQP = 每个搜索词上我们的曝光份额 / 点击份额 / 购买份额(长辰"点击份额 > 转化份额 = 详情页在漏"的判据)。

每次要报表都记 amz_report_runs;失败原因原样落库。

**事务纪律**:要报表要等好几分钟,worker 的连接有 8 秒 idle-in-transaction 上限。所以出网之前必须把
事务收掉(commit),网络等待期间不能挂着任何 SELECT/INSERT 未提交——否则连接被服务端掐断,
拿回来的报表落不了库。这里的函数自己 commit,调用方不要再包事务。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .clients.sp_api import SpApiClient, SpApiReportFailed
from .models import AmzReportRun, AmzSalesDaily, AmzSqp, AmzStore

_LOGGER = logging.getLogger("amz.reports")

REPORT_SALES_TRAFFIC = "GET_SALES_AND_TRAFFIC_REPORT"
REPORT_SQP = "GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT"
SALES_TRAFFIC_LAG_DAYS = (1, 2, 3)  # 报表有一两天延迟,每天回看三天,幂等 upsert
SQP_LOOKBACK_DAYS = 60
SQP_MAX_ASINS = 12
SQP_WEEKS = 4  # 保留最近几个整周:长辰要比「上周 vs 上上周」,一周孤零零比不了
STORE_TOTAL_ASIN = ""


# ---------------------------------------------------------------- 解析(纯函数,可测)


def _money(value: Any) -> Decimal:
    if isinstance(value, dict):
        value = value.get("amount")
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (ArithmeticError, ValueError):
        return Decimal("0")


def _pct(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (ArithmeticError, ValueError):
        return None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_sales_traffic(payload: dict[str, Any], *, store_code: str, currency_default: str) -> list[dict[str, Any]]:
    """报表 → 行。byDate 每天一行(child_asin=''),byAsin 每个子 ASIN 一行,日期取报表区间(我们按单日要)。"""
    rows: list[dict[str, Any]] = []
    spec = payload.get("reportSpecification") or {}
    day_default = str(spec.get("dataStartTime") or "")[:10]
    for item in payload.get("salesAndTrafficByDate") or []:
        sales, traffic = item.get("salesByDate") or {}, item.get("trafficByDate") or {}
        rows.append(
            {
                "store_code": store_code,
                "report_date": date.fromisoformat(str(item.get("date") or day_default)[:10]),
                "parent_asin": "",
                "child_asin": STORE_TOTAL_ASIN,
                "units_ordered": _int(sales.get("unitsOrdered")),
                "ordered_product_sales": _money(sales.get("orderedProductSales")),
                "currency": str((sales.get("orderedProductSales") or {}).get("currencyCode") or currency_default),
                "total_order_items": _int(sales.get("totalOrderItems")),
                "units_refunded": _int(sales.get("unitsRefunded")),
                "sessions": _int(traffic.get("sessions")),
                "page_views": _int(traffic.get("pageViews")),
                "buy_box_pct": _pct(traffic.get("buyBoxPercentage")),
                "unit_session_pct": _pct(traffic.get("unitSessionPercentage")),
                "raw": {"sales": sales, "traffic": traffic},
            }
        )
    if not day_default:
        return rows
    for item in payload.get("salesAndTrafficByAsin") or []:
        sales, traffic = item.get("salesByAsin") or {}, item.get("trafficByAsin") or {}
        child = str(item.get("childAsin") or "").strip().upper()
        if not child:
            continue
        rows.append(
            {
                "store_code": store_code,
                "report_date": date.fromisoformat(day_default),
                "parent_asin": str(item.get("parentAsin") or "").strip().upper(),
                "child_asin": child,
                "units_ordered": _int(sales.get("unitsOrdered")),
                "ordered_product_sales": _money(sales.get("orderedProductSales")),
                "currency": str((sales.get("orderedProductSales") or {}).get("currencyCode") or currency_default),
                "total_order_items": _int(sales.get("totalOrderItems")),
                "units_refunded": _int(sales.get("unitsRefunded")),
                "sessions": _int(traffic.get("sessions")),
                "page_views": _int(traffic.get("pageViews")),
                "buy_box_pct": _pct(traffic.get("buyBoxPercentage")),
                "unit_session_pct": _pct(traffic.get("unitSessionPercentage")),
                "raw": {"sales": sales, "traffic": traffic},
            }
        )
    return rows


def parse_sqp(payload: Any, *, store_code: str) -> list[dict[str, Any]]:
    """SQP 报表 → 行。官方结构:dataByAsin[] 每条一个 (asin, searchQuery, 周)。"""
    items = payload.get("dataByAsin") if isinstance(payload, dict) else payload
    rows: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        q = item.get("searchQueryData") or {}
        imp = item.get("impressionData") or {}
        clk = item.get("clickData") or {}
        cart = item.get("cartAddData") or {}
        buy = item.get("purchaseData") or {}
        query = str(q.get("searchQuery") or "").strip()
        asin = str(item.get("asin") or "").strip().upper()
        start, end = str(item.get("startDate") or "")[:10], str(item.get("endDate") or "")[:10]
        if not (query and asin and start and end):
            continue
        rows.append(
            {
                "store_code": store_code,
                "period_type": "WEEK",
                "period_start": date.fromisoformat(start),
                "period_end": date.fromisoformat(end),
                "asin": asin,
                "search_query": query,
                "query_score": _int(q.get("searchQueryScore")) or None,
                "query_volume": _int(q.get("searchQueryVolume")) or None,
                "impressions_total": _int(imp.get("totalQueryImpressionCount")),
                "impressions_asin": _int(imp.get("asinImpressionCount")),
                "impressions_share_pct": _pct(imp.get("asinImpressionShare")),
                "clicks_total": _int(clk.get("totalClickCount")),
                "clicks_asin": _int(clk.get("asinClickCount")),
                "clicks_share_pct": _pct(clk.get("asinClickShare")),
                "cart_adds_total": _int(cart.get("totalCartAddCount")),
                "cart_adds_asin": _int(cart.get("asinCartAddCount")),
                "cart_adds_share_pct": _pct(cart.get("asinCartAddShare")),
                "purchases_total": _int(buy.get("totalPurchaseCount")),
                "purchases_asin": _int(buy.get("asinPurchaseCount")),
                "purchases_share_pct": _pct(buy.get("asinPurchaseShare")),
                "raw": item,
            }
        )
    return rows


def last_complete_week(today: date) -> tuple[date, date]:
    """SQP 的周是周日到周六;返回最近一个已经结束的整周。"""
    # weekday(): Mon=0 … Sun=6 → 最近的周六
    days_since_saturday = (today.weekday() - 5) % 7
    end = today - timedelta(days=days_since_saturday or 7)
    return end - timedelta(days=6), end


# ---------------------------------------------------------------- 落库


def upsert_sales_daily(db: Session, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    stmt = pg_insert(AmzSalesDaily).values(rows)
    update_cols = {c: getattr(stmt.excluded, c) for c in ("parent_asin", "units_ordered", "ordered_product_sales", "currency", "total_order_items", "units_refunded", "sessions", "page_views", "buy_box_pct", "unit_session_pct", "raw")}
    update_cols["updated_at"] = func.now()
    db.execute(stmt.on_conflict_do_update(constraint="uq_amz_sales_daily_store_date_asin", set_=update_cols))
    return len(rows)


def upsert_sqp(db: Session, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    stmt = pg_insert(AmzSqp).values(rows)
    update_cols = {c: getattr(stmt.excluded, c) for c in ("period_end", "query_score", "query_volume", "impressions_total", "impressions_asin", "impressions_share_pct", "clicks_total", "clicks_asin", "clicks_share_pct", "cart_adds_total", "cart_adds_asin", "cart_adds_share_pct", "purchases_total", "purchases_asin", "purchases_share_pct", "raw")}
    update_cols["updated_at"] = func.now()
    db.execute(stmt.on_conflict_do_update(constraint="uq_amz_sqp_store_period_asin_query", set_=update_cols))
    return len(rows)


def _run(db: Session, *, store_code: str, report_type: str, params: dict[str, Any]) -> AmzReportRun:
    run = AmzReportRun(store_code=store_code, report_type=report_type, params_json=params, status="requested")
    db.add(run)
    db.commit()  # 出网前收事务:接下来要等几分钟
    return run


def _finish(db: Session, run: AmzReportRun, *, status: str, rows: int = 0, report_id: str | None = None, error: str | None = None) -> None:
    run.status = status
    run.rows = rows
    run.report_id = report_id
    run.error = (error or "")[:2000] or None
    run.finished_at = datetime.now(UTC)
    db.add(run)
    db.commit()


# ---------------------------------------------------------------- 同步


def sync_sales_traffic_day(db: Session, client: SpApiClient, store: AmzStore, day: date) -> dict[str, Any]:
    params = {"day": day.isoformat(), "dateGranularity": "DAY", "asinGranularity": "CHILD"}
    run = _run(db, store_code=store.store_code, report_type=REPORT_SALES_TRAFFIC, params=params)
    try:
        report_id, payload = client.run_report(REPORT_SALES_TRAFFIC, start=day, end=day, options={"dateGranularity": "DAY", "asinGranularity": "CHILD"})
        rows = parse_sales_traffic(payload, store_code=store.store_code, currency_default=store.currency)
        n = upsert_sales_daily(db, rows)
        _finish(db, run, status="done", rows=n, report_id=report_id)
        return {"day": day.isoformat(), "rows": n, "report_id": report_id}
    except SpApiReportFailed as exc:
        db.rollback()
        _finish(db, run, status="failed", error=f"{exc.report_status}: {exc.details}")
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _finish(db, run, status="failed", error=repr(exc))
        raise


def sync_sales_traffic(db: Session, client: SpApiClient, store: AmzStore, *, today: date | None = None, lag_days: tuple[int, ...] = SALES_TRAFFIC_LAG_DAYS) -> dict[str, Any]:
    """每天回看三天(报表有延迟),按天要、按天 upsert。一天失败不拖累别的天,但要报出去。"""
    today = today or datetime.now(UTC).date()
    out: dict[str, Any] = {"days": [], "errors": []}
    for lag in lag_days:
        day = today - timedelta(days=lag)
        try:
            out["days"].append(sync_sales_traffic_day(db, client, store, day))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            out["errors"].append({"day": day.isoformat(), "error": str(exc)[:300]})
    if out["errors"] and not out["days"]:
        raise RuntimeError(f"sales_traffic all days failed: {out['errors'][0]['error']}")
    return out


def active_asins(db: Session, store_code: str, *, since: date, limit: int = SQP_MAX_ASINS) -> list[str]:
    """最近有销量的子 ASIN,按件数倒序——SQP 一个 ASIN 一份报表,不能无限要。"""
    rows = db.execute(
        select(AmzSalesDaily.child_asin, func.sum(AmzSalesDaily.units_ordered))
        .where(AmzSalesDaily.store_code == store_code, AmzSalesDaily.child_asin != STORE_TOTAL_ASIN, AmzSalesDaily.report_date >= since)
        .group_by(AmzSalesDaily.child_asin)
        .order_by(func.sum(AmzSalesDaily.units_ordered).desc())
        .limit(limit)
    ).all()
    return [asin for asin, _ in rows]


def sync_sqp_week(db: Session, client: SpApiClient, store: AmzStore, *, asin: str, start: date, end: date) -> dict[str, Any]:
    params = {"asin": asin, "start": start.isoformat(), "end": end.isoformat(), "reportPeriod": "WEEK"}
    run = _run(db, store_code=store.store_code, report_type=REPORT_SQP, params=params)
    try:
        report_id, payload = client.run_report(REPORT_SQP, start=start, end=end, options={"reportPeriod": "WEEK", "asin": asin})
        rows = parse_sqp(payload, store_code=store.store_code)
        n = upsert_sqp(db, rows)
        _finish(db, run, status="done", rows=n, report_id=report_id)
        return {"asin": asin, "rows": n, "report_id": report_id}
    except SpApiReportFailed as exc:
        db.rollback()
        _finish(db, run, status="failed", error=f"{exc.report_status}: {exc.details}")
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _finish(db, run, status="failed", error=repr(exc))
        raise


def complete_weeks(today: date, count: int = SQP_WEEKS) -> list[tuple[date, date]]:
    """最近 count 个整周(周日–周六),新的在前。"""
    start, end = last_complete_week(today)
    weeks = []
    for _ in range(count):
        weeks.append((start, end))
        start, end = start - timedelta(days=7), end - timedelta(days=7)
    return weeks


def have_sqp_weeks(db: Session, store_code: str) -> set[tuple[str, date]]:
    return set(db.execute(select(AmzSqp.asin, AmzSqp.period_start).where(AmzSqp.store_code == store_code).distinct()).all())


def sync_sqp(db: Session, client: SpApiClient, store: AmzStore, *, today: date | None = None, weeks: int = SQP_WEEKS) -> dict[str, Any]:
    """每个活跃 ASIN × 最近几个整周,库里没有的才要(一份报表约十分钟,限速 1/分钟)。"""
    today = today or datetime.now(UTC).date()
    wanted = complete_weeks(today, weeks)
    asins = active_asins(db, store.store_code, since=today - timedelta(days=SQP_LOOKBACK_DAYS))
    have = have_sqp_weeks(db, store.store_code)
    db.commit()  # 读完就收事务,下面要出网等
    out: dict[str, Any] = {"weeks": [[s.isoformat(), e.isoformat()] for s, e in wanted], "asins": [], "skipped": 0, "errors": []}
    if not asins:
        out["note"] = "no asins with sales yet (run sales_traffic first)"
        return out
    for asin in asins:
        for start, end in wanted:
            if (asin, start) in have:
                out["skipped"] += 1
                continue
            try:
                out["asins"].append(sync_sqp_week(db, client, store, asin=asin, start=start, end=end))
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                out["errors"].append({"asin": asin, "week": start.isoformat(), "error": str(exc)[:300]})
    if out["errors"] and not out["asins"]:
        raise RuntimeError(f"sqp all requests failed: {out['errors'][0]['error']}")
    return out


__all__ = [
    "REPORT_SALES_TRAFFIC",
    "REPORT_SQP",
    "active_asins",
    "complete_weeks",
    "have_sqp_weeks",
    "last_complete_week",
    "parse_sales_traffic",
    "parse_sqp",
    "sync_sales_traffic",
    "sync_sales_traffic_day",
    "sync_sqp",
    "sync_sqp_week",
    "upsert_sales_daily",
    "upsert_sqp",
]
