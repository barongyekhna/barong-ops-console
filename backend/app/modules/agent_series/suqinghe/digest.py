"""运营看板(10-30 老板拍板:运营项里先做这个)。

她早上看完全局快照,顺手把昨天的运营数算出来:流量(Jetpack,W 系列已落库)、订单(Woo,W 系列缓存表)、站点健康(H 哨兵)、
内容台、店里品数;每周一再把上一整周合成一张「只看不用批」的卡。全部是查表加减法,**模型不碰发版 1 的任何数字**。

老板的两条规矩:日报不发卡(只进早间快照和办公室「看板」面板),触发异常规则才发一张提醒卡;周报一周一张卡。
小基数静默:访客中位数 < 20、订单 < 3 的比较一律不报,免得几十个访客的波动天天报警。

日期一律按洛杉矶日(LA):订单的 placed_at 是 UTC,换算;流量日是 Jetpack 的站点日(固定 -05:00),差一小时不纠结,直接用。
落库 sqh_digests(kind=day|week, period_key=2026-10-29|2026-W44),接口和面板只读它,不现算。
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION, without_org_data_isolation
from .constants import LA
from .models import SqhCard, SqhDigest, SqhSnapshot

logger = logging.getLogger(__name__)
_X = SKIP_ORG_DATA_ISOLATION

DAY, WEEK = "day", "week"
UNREADABLE = {"error": "读不到"}
ORDER_OK_STATUSES = ("processing", "completed", "on-hold")
ORDER_BAD_STATUSES = ("cancelled", "refunded", "failed")
SMALL_VIEWS = 20  # 近 7 日浏览中位数低于这个数,涨跌不报
SMALL_ORDERS = 3  # 比较期订单低于这个数,涨跌不报
SITE_CHECK_MAX_AGE_H = 36
ORDER_SYNC_MAX_AGE_H = 2
TOP_N = 5
WEEKLY_HOUR = 7  # LA 周一 07:00 后出上周的周报


# ---------------------------------------------------------------- 日期


def la_date(now: datetime) -> date:
    return now.astimezone(LA).date()


def la_day_bounds(day: date) -> tuple[datetime, datetime]:
    """这一天(洛杉矶)对应的 UTC 区间 [start, end)。"""
    start = datetime(day.year, day.month, day.day, tzinfo=LA)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def week_key(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def week_days(key: str) -> tuple[date, date]:
    """'2026-W44' → (周一, 周日)。"""
    year, week = key.split("-W")
    monday = date.fromisocalendar(int(year), int(week), 1)
    return monday, monday + timedelta(days=6)


def previous_week_key(now: datetime) -> str:
    """刚过完的那一周(周一早上算的是上周)。"""
    today = la_date(now)
    return week_key(today - timedelta(days=today.isoweekday()))


def should_run_weekly(now: datetime, *, exists: bool) -> bool:
    """LA 周一 07:00 以后、上周的周报还没有 → 该出了。错过周一也补(任何一天只要上周没有就出)。"""
    local = now.astimezone(LA)
    if exists:
        return False
    if local.isoweekday() == 1:
        return local.hour >= WEEKLY_HOUR
    return True


# ---------------------------------------------------------------- 各路数(每路单独兜底)


def _trade_org_id(db: Session) -> str | None:
    from ....core.target_org_guard import INTERNATIONAL_TRADE_ORG_NAME, resolve_target_org

    target = resolve_target_org(db, INTERNATIONAL_TRADE_ORG_NAME)
    return str(target.org_id) if target is not None else None


def _top(items: list[dict[str, Any]], key: str, n: int = TOP_N) -> list[dict[str, Any]]:
    out = []
    for item in items[:n]:
        if not isinstance(item, dict):
            continue
        out.append({"name": str(item.get(key) or item.get("title") or item.get("name") or "")[:80], "views": int(item.get("views") or 0)})
    return out


def traffic_part(db: Session, *, day_to: date, span: int, now: datetime) -> dict[str, Any]:
    """range_report 的精简版:区间合计 + 前一同长区间 + 逐日 + 榜单前五 + 采集状态。"""
    from ...w_series.traffic import service as traffic

    org_id = _trade_org_id(db)
    if org_id is None:
        return {"error": "贸易组织读不到"}
    with without_org_data_isolation():
        report = traffic.range_report(db, workspace_key=org_id, day_from=day_to - timedelta(days=span - 1), day_to=day_to, now=now)
    days = [{"day": d["day"].isoformat() if hasattr(d["day"], "isoformat") else str(d["day"]), "views": int(d["views"]), "visitors": int(d["visitors"])} for d in report["days"]]
    return {
        "day_from": (day_to - timedelta(days=span - 1)).isoformat(),
        "day_to": day_to.isoformat(),
        "views": int(report["views"]),
        "visitors": int(report["visitors"]),
        "prev_views": int(report["prev_views"]),
        "prev_visitors": int(report["prev_visitors"]),
        "days": days,
        "top_posts": _top(report["top_posts"], "title"),
        "referrers": _top(report["referrers"], "name"),
        "countries": _top(report["countries"], "name"),
        "search_terms": [{"name": str(t.get("term") or "")[:80], "views": int(t.get("views") or 0)} for t in report["search_terms"][:TOP_N] if isinstance(t, dict)],
        "collector_stale": bool(report["collector_stale"]),
        "collected_at": report["collected_at"].isoformat() if report["collected_at"] else None,
    }


def _orders_between(db: Session, start: date, end: date) -> list[Any]:
    from ...w_series.shipping.models import WOrder

    start_utc, _ = la_day_bounds(start)
    _, end_utc = la_day_bounds(end)
    return list(db.scalars(select(WOrder).where(WOrder.placed_at >= start_utc, WOrder.placed_at < end_utc), execution_options=_X))


def _order_stats(rows: list[Any]) -> dict[str, Any]:
    ok = [r for r in rows if (r.woo_status or "") in ORDER_OK_STATUSES]
    bad = [r for r in rows if (r.woo_status or "") in ORDER_BAD_STATUSES]
    revenue: dict[str, float] = {}
    for r in ok:
        cur = (r.currency or "USD").upper()
        revenue[cur] = round(revenue.get(cur, 0.0) + float(r.total or Decimal(0)), 2)
    items: Counter[str] = Counter()
    names: dict[str, str] = {}
    for r in ok:
        for it in r.items_json or []:
            if not isinstance(it, dict):
                continue
            key = str(it.get("sku") or it.get("name") or "")
            if not key:
                continue
            try:
                items[key] += int(it.get("qty") or 0)
            except (TypeError, ValueError):
                continue
            names.setdefault(key, str(it.get("name") or key))
    countries = Counter((r.country or "?") for r in ok)
    main_cur = max(revenue, key=revenue.get) if revenue else None
    return {
        "count": len(ok),
        "cancelled": len(bad),
        "revenue": revenue,
        "aov": round(revenue[main_cur] / len(ok), 2) if ok and main_cur else None,
        "currency": main_cur,
        "top_items": [{"sku": k, "name": names[k][:60], "qty": v} for k, v in items.most_common(TOP_N)],
        "countries": [{"name": k, "count": v} for k, v in countries.most_common(TOP_N)],
    }


def orders_part(db: Session, *, start: date, end: date) -> dict[str, Any]:
    """[start, end] 这几个 LA 日的订单 + 前一同长区间。"""
    span = (end - start).days + 1
    current = _order_stats(_orders_between(db, start, end))
    previous = _order_stats(_orders_between(db, start - timedelta(days=span), start - timedelta(days=1)))
    sync_at, sync_stale = _heartbeat(db, "w-orders", max_age_h=ORDER_SYNC_MAX_AGE_H)
    return {**current, "prev_count": previous["count"], "prev_revenue": previous["revenue"], "sync_at": sync_at, "sync_stale": sync_stale, "day_from": start.isoformat(), "day_to": end.isoformat()}


def _heartbeat(db: Session, worker_name: str, *, max_age_h: float) -> tuple[str | None, bool]:
    from ....services.worker_heartbeat import list_heartbeats

    for beat in list_heartbeats(db):
        if beat.get("worker_name") != worker_name:
            continue
        raw = beat.get("last_success_at")
        if not raw:
            return None, True
        last = datetime.fromisoformat(str(raw))
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return last.isoformat(), (datetime.now(UTC) - last) > timedelta(hours=max_age_h)
    return None, True  # 从没记过心跳 = 不知道它活没活,按停了算(读不到 ≠ 0,但这里是「同步没跑」本身)


def site_part(db: Session, *, now: datetime) -> dict[str, Any]:
    from sqlalchemy import func

    from ...h_series.sitehealth.models import HHealthFinding, HHealthRun

    with without_org_data_isolation():
        run = db.scalar(select(HHealthRun).order_by(HHealthRun.started_at.desc().nullslast()).limit(1), execution_options=_X)
        open_findings = int(db.scalar(select(func.count()).select_from(HHealthFinding).where(HHealthFinding.status == "open"), execution_options=_X) or 0)
    if run is None:
        return {"checked_at": None, "age_hours": None, "open_findings": open_findings}
    at = run.finished_at or run.started_at
    age = (now - at).total_seconds() / 3600 if at else None
    return {
        "checked_at": at.isoformat() if at else None,
        "age_hours": round(age, 1) if age is not None else None,
        "status": run.status,
        "urls_total": int(run.urls_total or 0),
        "urls_broken": int(run.urls_broken or 0),
        "urls_slow": int(run.urls_slow or 0),
        "avg_response_ms": run.avg_response_ms,
        "p95_response_ms": run.p95_response_ms,
        "homepage_ok": bool(run.homepage_ok),
        "sitemap_ok": bool(run.sitemap_ok),
        "open_findings": open_findings,
    }


def content_part(db: Session, *, start: date, end: date) -> dict[str, Any]:
    from sqlalchemy import func

    from ...content_desk.queries import step_counts
    from ...geo_series.content.models import GeoContentItem
    from ...seo_series.content.models import SeoContentItem

    start_utc, _ = la_day_bounds(start)
    _, end_utc = la_day_bounds(end)
    with without_org_data_isolation():
        counts = dict(step_counts(db))
        published = 0
        for model in (GeoContentItem, SeoContentItem):
            published += int(db.scalar(select(func.count()).select_from(model).where(model.published_at >= start_utc, model.published_at < end_utc), execution_options=_X) or 0)
    return {**counts, "published_in_period": published}


def catalog_part(db: Session) -> dict[str, Any]:
    """店里品数:直接用最新一份早间快照里的产品节(它已经核过 Woo 状态),不再出网。"""
    snap = db.scalar(select(SqhSnapshot).order_by(SqhSnapshot.snapshot_date.desc()).limit(1), execution_options=_X)
    products = (snap.payload or {}).get("products") if snap is not None and isinstance(snap.payload, dict) else None
    if not isinstance(products, dict) or "by_stage" not in products:
        return dict(UNREADABLE)
    by = dict(products["by_stage"])
    return {"snapshot_date": snap.snapshot_date.isoformat(), "published": int(by.get("published", 0)), "ready_to_upload": int(by.get("ready_to_upload", 0)), "uploaded_draft": int(by.get("uploaded_draft", 0)), "total": int(sum(int(v) for v in by.values()))}


def cards_part(db: Session, *, start: date, end: date) -> dict[str, Any]:
    start_utc, _ = la_day_bounds(start)
    _, end_utc = la_day_bounds(end)
    rows = list(db.scalars(select(SqhCard).where(SqhCard.created_at >= start_utc, SqhCard.created_at < end_utc), execution_options=_X))
    decided = list(db.scalars(select(SqhCard).where(SqhCard.decided_at >= start_utc, SqhCard.decided_at < end_utc), execution_options=_X))
    return {
        "created": len(rows),
        "approved": sum(1 for c in decided if c.status == "approved"),
        "rejected": sum(1 for c in decided if c.status == "rejected"),
        "by_kind": dict(Counter(c.kind for c in rows)),
    }


def _safe(name: str, fn, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except Exception:  # noqa: BLE001 —— 一路读不到只标这一路(读不到 ≠ 0)
        logger.exception("digest part failed: %s", name)
        db = kwargs.get("db") or (args[0] if args else None)
        if db is not None:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        return dict(UNREADABLE)


def collect_day(db: Session, day: date, *, now: datetime | None = None) -> dict[str, Any]:
    """某一天(通常是昨天)的运营数。"""
    now = now or datetime.now(UTC)
    return {
        "kind": DAY,
        "period_key": day.isoformat(),
        "generated_at": now.isoformat(),
        "traffic": _safe("traffic", traffic_part, db, day_to=day, span=7, now=now),
        "orders": _safe("orders", orders_part, db, start=day, end=day),
        "orders_7d": _safe("orders_7d", orders_part, db, start=day - timedelta(days=6), end=day),
        "site": _safe("site", site_part, db, now=now),
        "content": _safe("content", content_part, db, start=day - timedelta(days=6), end=day),
        "catalog": _safe("catalog", catalog_part, db),
        "search": _safe("search", search_part_lagged, db, end=day),
    }


def search_part_lagged(db: Session, *, end: date) -> dict[str, Any]:
    """日报里的搜索一节:谷歌数据滞后,看到 end-lag 为止的最近 7 天。"""
    from .constants import gsc_lag_days
    from .gsc import search_part

    last = end - timedelta(days=gsc_lag_days() - 1)
    return search_part(db, start=last - timedelta(days=6), end=last)


def collect_week(db: Session, key: str, *, now: datetime | None = None) -> dict[str, Any]:
    """一整周(周一到周日 LA)的运营数 + 这周日报里出现过的异常 + 这周卡片的账。"""
    now = now or datetime.now(UTC)
    monday, sunday = week_days(key)
    daily = list(db.scalars(select(SqhDigest).where(SqhDigest.kind == DAY, SqhDigest.period_key >= monday.isoformat(), SqhDigest.period_key <= sunday.isoformat()), execution_options=_X))
    codes: Counter[str] = Counter()
    for row in daily:
        for f in row.findings or []:
            if isinstance(f, dict) and f.get("code"):
                codes[str(f["code"])] += 1
    return {
        "kind": WEEK,
        "period_key": key,
        "generated_at": now.isoformat(),
        "day_from": monday.isoformat(),
        "day_to": sunday.isoformat(),
        "traffic": _safe("traffic", traffic_part, db, day_to=sunday, span=7, now=now),
        "orders": _safe("orders", orders_part, db, start=monday, end=sunday),
        "site": _safe("site", site_part, db, now=now),
        "content": _safe("content", content_part, db, start=monday, end=sunday),
        "catalog": _safe("catalog", catalog_part, db),
        "cards": _safe("cards", cards_part, db, start=monday, end=sunday),
        "search": _safe("search", _search_week, db, start=monday, end=sunday),
        "daily_findings": dict(codes),
        "daily_digests": len(daily),
    }


def _search_week(db: Session, *, start: date, end: date) -> dict[str, Any]:
    from .gsc import search_part

    return search_part(db, start=start, end=end)


# ---------------------------------------------------------------- 规则层:只报有数据支撑的


def _pct(now_v: float, prev_v: float) -> float | None:
    if prev_v <= 0:
        return None
    return round((now_v - prev_v) / prev_v * 100)


def rules(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """异常清单,每条 {code, severity: warn|info, text, numbers}。warn 的早上会出提醒卡,info 只写在面板里。"""
    out: list[dict[str, Any]] = []
    kind = payload.get("kind")

    def add(code: str, severity: str, text: str, **numbers: Any) -> None:
        out.append({"code": code, "severity": severity, "text": text, "numbers": numbers})

    traffic = payload.get("traffic") or {}
    if isinstance(traffic, dict) and "error" not in traffic:
        if traffic.get("collector_stale"):
            add("traffic_collector_stale", "warn", "流量采集停了(Jetpack 那路 20 分钟没成功过),看板上的流量数不准", collected_at=traffic.get("collected_at"))
        days = [int(d.get("views") or 0) for d in traffic.get("days") or []]
        if kind == DAY and len(days) >= 4:
            yesterday, before = days[-1], days[:-1]
            med = median(before)
            if med >= SMALL_VIEWS and yesterday < med * 0.5:
                add("traffic_drop", "warn", f"昨天只有 {yesterday} 次浏览,不到前几天中位数 {med:g} 的一半", views=yesterday, median=med)
            elif yesterday >= 50 and med > 0 and yesterday > med * 3:
                add("traffic_spike", "info", f"昨天 {yesterday} 次浏览,是前几天中位数 {med:g} 的三倍多,看看来源里多了谁", views=yesterday, median=med)
        if kind == WEEK:
            v, p = int(traffic.get("views") or 0), int(traffic.get("prev_views") or 0)
            change = _pct(v, p)
            if p >= SMALL_VIEWS * 7 and change is not None:
                if change <= -40:
                    add("week_traffic_drop", "warn", f"本周 {v} 次浏览,比上周 {p} 少了 {-change}%", views=v, prev=p, change=change)
                elif change >= 40:
                    add("week_traffic_spike", "info", f"本周 {v} 次浏览,比上周 {p} 多了 {change}%", views=v, prev=p, change=change)
    orders = payload.get("orders_7d") if kind == DAY else payload.get("orders")
    if isinstance(orders, dict) and "error" not in orders:
        if orders.get("sync_stale"):
            add("order_sync_silent", "warn", f"订单同步 {ORDER_SYNC_MAX_AGE_H} 小时没成功过(n8n 那条 15 分钟一跑的),新订单可能没进来", sync_at=orders.get("sync_at"))
        c, p = int(orders.get("count") or 0), int(orders.get("prev_count") or 0)
        if c == 0 and p >= SMALL_ORDERS:
            add("orders_stall", "warn", f"{'近 7 天' if kind == DAY else '本周'} 0 单,而前一段有 {p} 单", count=c, prev=p)
        elif kind == WEEK and p >= 5:
            change = _pct(c, p)
            if change is not None and change <= -50:
                add("orders_week_drop", "warn", f"本周 {c} 单,比上周 {p} 少了 {-change}%", count=c, prev=p, change=change)
            elif change is not None and change >= 50:
                add("orders_week_spike", "info", f"本周 {c} 单,比上周 {p} 多了 {change}%", count=c, prev=p, change=change)
    site = payload.get("site") or {}
    if isinstance(site, dict) and site and "error" not in site:
        age = site.get("age_hours")
        if site.get("checked_at") is None or (age is not None and age > SITE_CHECK_MAX_AGE_H):
            add("site_check_missing", "warn", f"站点体检 {int(age) if age else '从来'} 小时没跑了(H 哨兵每天 03:40 那条)", age_hours=age)
        else:
            if not site.get("homepage_ok", True):
                add("site_homepage_down", "warn", "站点体检说首页打不开或不对,先看站", checked_at=site.get("checked_at"))
            if int(site.get("urls_broken") or 0) >= 1:
                add("site_broken_links", "warn", f"站上有 {site['urls_broken']} 个坏链接", urls_broken=site["urls_broken"])
            slow, p95 = int(site.get("urls_slow") or 0), site.get("p95_response_ms")
            if slow >= 3 or (isinstance(p95, int) and p95 > 3000):
                add("site_slow_pages", "info", f"{slow} 个页面响应超过 3 秒,p95 {p95 or '—'} ms(美国买家体感)", urls_slow=slow, p95=p95)
    content = payload.get("content") or {}
    if isinstance(content, dict) and "error" not in content and int(content.get("pending_review") or 0) >= 10:
        add("content_backlog", "info", f"内容台积压 {content['pending_review']} 篇待审", pending_review=content["pending_review"])
    search = payload.get("search") or {}
    if isinstance(search, dict) and "error" not in search and search.get("configured"):
        from .constants import gsc_lag_days

        last_day = search.get("last_day")
        try:
            stale_days = (date.fromisoformat(str(payload.get("period_key"))[:10]) - date.fromisoformat(str(last_day))).days if last_day and kind == DAY else None
        except ValueError:
            stale_days = None
        if last_day is None or (stale_days is not None and stale_days > gsc_lag_days() + 3):
            add("gsc_pull_stale", "warn", f"Search Console 的数{'一天都没拉到' if last_day is None else f'停在 {last_day}'}{',最近一次报错:' + str(search.get('last_error'))[:80] if search.get('last_error') else ''}", last_day=last_day)
        elif kind == WEEK:
            c, p = int(search.get("clicks") or 0), int(search.get("prev_clicks") or 0)
            change = _pct(c, p)
            if p >= 50 and change is not None and change <= -40:
                add("gsc_clicks_drop", "warn", f"本周谷歌搜索点击 {c},比上周 {p} 少了 {-change}%", clicks=c, prev=p, change=change)
            elif p >= 50 and change is not None and change >= 40:
                add("gsc_clicks_spike", "info", f"本周谷歌搜索点击 {c},比上周 {p} 多了 {change}%", clicks=c, prev=p, change=change)
    return out


# ---------------------------------------------------------------- 人话 + 给卡和面板的统一结构


def _money(revenue: dict[str, Any] | None, currency: str | None) -> str:
    if not revenue:
        return "0"
    parts = [f"{cur} {amount:,.2f}" for cur, amount in sorted(revenue.items(), key=lambda kv: kv[0] != (currency or ""))]
    return " / ".join(parts)


def headline(payload: dict[str, Any]) -> str:
    traffic, orders, site = payload.get("traffic") or {}, payload.get("orders") or {}, payload.get("site") or {}
    parts: list[str] = []
    label = "昨日" if payload.get("kind") == DAY else "本周"
    if isinstance(traffic, dict) and "error" not in traffic:
        if payload.get("kind") == DAY:
            last = (traffic.get("days") or [{}])[-1]
            parts.append(f"{label} {int(last.get('visitors') or 0)} 人 {int(last.get('views') or 0)} 次浏览")
        else:
            change = _pct(int(traffic.get("views") or 0), int(traffic.get("prev_views") or 0))
            parts.append(f"{label} {traffic.get('visitors', 0)} 人 {traffic.get('views', 0)} 次浏览" + (f"(比上周{'多' if change >= 0 else '少'} {abs(change)}%)" if change is not None else ""))
        if traffic.get("referrers"):
            parts.append(f"来源头一名 {traffic['referrers'][0]['name']}")
    else:
        parts.append("流量读不到")
    if isinstance(orders, dict) and "error" not in orders:
        parts.append(f"{orders.get('count', 0)} 单" + (f" {_money(orders.get('revenue'), orders.get('currency'))}" if orders.get("count") else ""))
    else:
        parts.append("订单读不到")
    if isinstance(site, dict) and "error" not in site and site.get("checked_at"):
        parts.append(f"站点 {site.get('urls_broken', 0)} 坏链 {site.get('urls_slow', 0)} 慢页")
    search = payload.get("search") or {}
    if isinstance(search, dict) and search.get("configured") and search.get("last_day"):
        parts.append(f"谷歌搜索 {search.get('clicks', 0)} 点击 {search.get('impressions', 0)} 展现")
    return ";".join(parts) + "。"


def _delta(now_v: Any, prev_v: Any) -> str | None:
    try:
        a, b = float(now_v), float(prev_v)
    except (TypeError, ValueError):
        return None
    if b <= 0:
        return None
    change = round((a - b) / b * 100)
    return f"{'+' if change >= 0 else ''}{change}%"


def sections(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """[{heading, rows: [[label, value, delta|None]]}];面板和卡都画这个,不在前端拼数。"""
    out: list[dict[str, Any]] = []
    kind = payload.get("kind")
    prev_label = "比前 7 天" if kind == DAY else "比上周"
    traffic = payload.get("traffic") or {}
    if isinstance(traffic, dict) and "error" not in traffic:
        rows: list[list[Any]] = []
        if kind == DAY:
            last = (traffic.get("days") or [{}])[-1]
            rows.append(["昨日浏览 / 访客", f"{int(last.get('views') or 0)} / {int(last.get('visitors') or 0)}", None])
        rows.append(["近 7 日浏览", str(traffic.get("views", 0)), _delta(traffic.get("views"), traffic.get("prev_views")) and f"{_delta(traffic.get('views'), traffic.get('prev_views'))} {prev_label}"])
        rows.append(["近 7 日访客", str(traffic.get("visitors", 0)), _delta(traffic.get("visitors"), traffic.get("prev_visitors")) and f"{_delta(traffic.get('visitors'), traffic.get('prev_visitors'))} {prev_label}"])
        for label, key in (("来源前五", "referrers"), ("热门页前五", "top_posts"), ("国家前五", "countries"), ("站内搜索词", "search_terms")):
            items = traffic.get(key) or []
            if items:
                rows.append([label, "、".join(f"{i['name']} {i['views']}" for i in items), None])
        if traffic.get("collector_stale"):
            rows.append(["采集", "停了", None])
        out.append({"heading": "流量(Jetpack)", "rows": rows})
    else:
        out.append({"heading": "流量(Jetpack)", "rows": [["状态", "读不到", None]]})
    orders = payload.get("orders") or {}
    if isinstance(orders, dict) and "error" not in orders:
        rows = [["订单数", str(orders.get("count", 0)), (f"{_delta(orders.get('count'), orders.get('prev_count'))} {prev_label}" if _delta(orders.get("count"), orders.get("prev_count")) else None)]]
        rows.append(["销售额", _money(orders.get("revenue"), orders.get("currency")), None])
        if orders.get("aov") is not None:
            rows.append(["客单价", f"{orders.get('currency') or ''} {orders['aov']:,.2f}", None])
        if orders.get("cancelled"):
            rows.append(["取消/退款", str(orders["cancelled"]), None])
        if orders.get("top_items"):
            rows.append(["卖得最多", "、".join(f"{i['name']} ×{i['qty']}" for i in orders["top_items"]), None])
        if orders.get("countries"):
            rows.append(["买家国家", "、".join(f"{i['name']} {i['count']}" for i in orders["countries"]), None])
        if orders.get("sync_stale"):
            rows.append(["订单同步", "停了", None])
        out.append({"heading": "订单(Woo)" + (f" {orders.get('day_from')}~{orders.get('day_to')}" if kind == WEEK else ""), "rows": rows})
    else:
        out.append({"heading": "订单(Woo)", "rows": [["状态", "读不到", None]]})
    if kind == DAY and isinstance(payload.get("orders_7d"), dict) and "error" not in payload["orders_7d"]:
        o7 = payload["orders_7d"]
        out[-1]["rows"].append(["近 7 日订单", f"{o7.get('count', 0)} 单 {_money(o7.get('revenue'), o7.get('currency'))}", (f"{_delta(o7.get('count'), o7.get('prev_count'))} 比前 7 天" if _delta(o7.get("count"), o7.get("prev_count")) else None)])
    site = payload.get("site") or {}
    if isinstance(site, dict) and "error" not in site and site.get("checked_at"):
        out.append({"heading": "站点健康(H 哨兵)", "rows": [
            ["最近一次体检", str(site.get("checked_at") or "")[:16].replace("T", " "), None],
            ["坏链接 / 慢页", f"{site.get('urls_broken', 0)} / {site.get('urls_slow', 0)}(共查 {site.get('urls_total', 0)} 页)", None],
            ["响应 p95", f"{site.get('p95_response_ms') or '—'} ms", None],
            ["首页 / 站点地图", f"{'正常' if site.get('homepage_ok') else '异常'} / {'正常' if site.get('sitemap_ok') else '异常'}", None],
            ["未处理的问题", str(site.get("open_findings", 0)), None],
        ]})
    else:
        out.append({"heading": "站点健康(H 哨兵)", "rows": [["状态", "读不到或没跑过", None]]})
    content = payload.get("content") or {}
    if isinstance(content, dict) and "error" not in content:
        out.append({"heading": "内容台", "rows": [
            ["本期发布", str(content.get("published_in_period", 0)), None],
            ["待审 / 批了没发 / 已上线", f"{content.get('pending_review', 0)} / {content.get('approved_unpublished', 0)} / {content.get('live', 0)}", None],
        ]})
    catalog = payload.get("catalog") or {}
    if isinstance(catalog, dict) and "error" not in catalog:
        out.append({"heading": "店里的品", "rows": [["已发布 / 可上架 / 草稿", f"{catalog.get('published', 0)} / {catalog.get('ready_to_upload', 0)} / {catalog.get('uploaded_draft', 0)}", None]]})
    out.extend(search_sections(payload.get("search"), kind=kind, prev_label=prev_label))
    cards = payload.get("cards") or {}
    if kind == WEEK and isinstance(cards, dict) and "error" not in cards:
        out.append({"heading": "她这周的卡", "rows": [["发了 / 你批了 / 你驳了", f"{cards.get('created', 0)} / {cards.get('approved', 0)} / {cards.get('rejected', 0)}", None]]})
    return out


def search_sections(search: Any, *, kind: str, prev_label: str) -> list[dict[str, Any]]:
    """「搜索(Search Console)」+「搜索缺口」两节。没接钥匙就一行说明;接了没拉到就说到哪天。"""
    if not isinstance(search, dict) or "error" in search:
        return [{"heading": "搜索(Search Console)", "rows": [["状态", "读不到", None]]}]
    if not search.get("configured"):
        return [{"heading": "搜索(Search Console)", "rows": [["状态", "还没接:等老板按操作单配好服务账号", None]]}]
    window = f"{search.get('day_from')}~{search.get('day_to')}"
    rows: list[list[Any]] = [
        ["数据到哪天", str(search.get("last_day") or "一天都没拉到") + (f"(窗口 {window},覆盖 {search.get('covered_days', 0)} 天)" if search.get("last_day") else ""), None],
        ["点击 / 展现", f"{search.get('clicks', 0)} / {search.get('impressions', 0)}", (f"{_delta(search.get('clicks'), search.get('prev_clicks'))} {prev_label}" if _delta(search.get("clicks"), search.get("prev_clicks")) else None)],
        ["点击率 / 平均位次", f"{round(float(search.get('ctr') or 0) * 100, 1)}% / {search.get('position', 0)}", None],
    ]
    if search.get("top_queries"):
        rows.append(["点击最多的词", "、".join(f"{q['query']} {q['clicks']}" for q in search["top_queries"][:5]), None])
    out = [{"heading": "搜索(Search Console)", "rows": rows}]
    g = search.get("gaps") or {}
    gap_rows: list[list[Any]] = []
    if g.get("quick_wins"):
        gap_rows.append(["差一步的词(排 8–20,展现够)", "、".join(f"{x['query']}(第 {x['position']:g},{x['impressions']} 展现)" for x in g["quick_wins"][:5]), "值得补内容/内链把它推进前十"])
    if g.get("low_ctr_pages"):
        gap_rows.append(["有展现没点击的页", "、".join(f"{x['page'].split('/')[-2] or x['page'].split('/')[-1] or x['page']}({x['impressions']} 展现,点击率 {round(x['ctr'] * 100, 1)}%)" for x in g["low_ctr_pages"][:5]), "标题和描述该改"])
    far_product = [x for x in g.get("far_queries") or [] if x.get("has_product")]
    far_none = [x for x in g.get("far_queries") or [] if not x.get("has_product")]
    if far_product:
        gap_rows.append(["有需求、我们有品但排得远", "、".join(f"{x['query']}(第 {x['position']:g})" for x in far_product[:5]), "产品页该加强"])
    if far_none:
        gap_rows.append(["有需求、我们没对应品/内容", "、".join(f"{x['query']}({x['impressions']} 展现)" for x in far_none[:5]), "喂内容台选题 / 选品池"])
    if g.get("new_queries"):
        gap_rows.append(["本期新出现的词", "、".join(f"{x['query']}({x['impressions']})" for x in g["new_queries"][:5]), None])
    if search.get("last_day"):
        out.append({"heading": "搜索缺口", "rows": gap_rows or [["这一期", "没有够门槛的缺口(展现太少)", None]]})
    return out


# ---------------------------------------------------------------- 落库 / 读取


def save(db: Session, *, kind: str, period_key: str, payload: dict[str, Any], findings: list[dict[str, Any]], headline_text: str, now: datetime | None = None) -> SqhDigest:
    now = now or datetime.now(UTC)
    row = db.scalar(select(SqhDigest).where(SqhDigest.kind == kind, SqhDigest.period_key == period_key), execution_options=_X)
    if row is None:
        row = SqhDigest(kind=kind, period_key=period_key)
    row.payload, row.findings, row.headline, row.generated_at = payload, findings, headline_text[:500], now
    db.add(row)
    db.flush()
    return row


def build_and_save(db: Session, *, kind: str, period_key: str, now: datetime | None = None) -> SqhDigest:
    now = now or datetime.now(UTC)
    payload = collect_day(db, date.fromisoformat(period_key), now=now) if kind == DAY else collect_week(db, period_key, now=now)
    findings = rules(payload)
    payload["sections"] = sections(payload)
    return save(db, kind=kind, period_key=period_key, payload=payload, findings=findings, headline_text=headline(payload), now=now)


def exists(db: Session, *, kind: str, period_key: str) -> bool:
    return db.scalar(select(SqhDigest.id).where(SqhDigest.kind == kind, SqhDigest.period_key == period_key), execution_options=_X) is not None


def latest(db: Session, kind: str) -> SqhDigest | None:
    return db.scalar(select(SqhDigest).where(SqhDigest.kind == kind).order_by(SqhDigest.period_key.desc()).limit(1), execution_options=_X)


def listing(db: Session, *, kind: str | None, limit: int) -> list[SqhDigest]:
    stmt = select(SqhDigest).order_by(SqhDigest.period_key.desc(), SqhDigest.kind)
    if kind:
        stmt = stmt.where(SqhDigest.kind == kind)
    return list(db.scalars(stmt.limit(limit), execution_options=_X))


def get(db: Session, *, kind: str, period_key: str) -> SqhDigest | None:
    return db.scalar(select(SqhDigest).where(SqhDigest.kind == kind, SqhDigest.period_key == period_key), execution_options=_X)


def summary_payload(row: SqhDigest) -> dict[str, Any]:
    findings = [f for f in (row.findings or []) if isinstance(f, dict)]
    return {"kind": row.kind, "period_key": row.period_key, "headline": row.headline, "generated_at": row.generated_at.isoformat() if row.generated_at else None, "findings": findings, "warnings": sum(1 for f in findings if f.get("severity") == "warn")}


def detail_payload(row: SqhDigest) -> dict[str, Any]:
    payload = row.payload if isinstance(row.payload, dict) else {}
    return {**summary_payload(row), "sections": payload.get("sections") or sections(payload), "payload": payload}


def backfill(db: Session, *, days: int, weeks: int, now: datetime | None = None) -> dict[str, int]:
    """上线当天就有东西看:把最近 N 天的日报和 N 周的周报算出来(数据都在库里)。已有的不重算。"""
    now = now or datetime.now(UTC)
    today = la_date(now)
    made = {"day": 0, "week": 0}
    for offset in range(days, 0, -1):
        key = (today - timedelta(days=offset)).isoformat()
        if not exists(db, kind=DAY, period_key=key):
            build_and_save(db, kind=DAY, period_key=key, now=now)
            made["day"] += 1
            db.commit()
    for offset in range(weeks, 0, -1):
        key = week_key(today - timedelta(days=today.isoweekday() + 7 * (offset - 1)))
        if not exists(db, kind=WEEK, period_key=key):
            build_and_save(db, kind=WEEK, period_key=key, now=now)
            made["week"] += 1
            db.commit()
    return made
