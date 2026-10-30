"""运营看板(10-30)的纯逻辑:规则层异常(含小基数静默)、一句人话、给面板的分节、周的日期、周一的闸、订单按洛杉矶日聚合。
unit,不连库、不出网。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.app.modules.agent_series.suqinghe import digest, worker_main

pytestmark = pytest.mark.unit


def _traffic(days: list[int], *, prev_views: int = 0, stale: bool = False, referrers: list[tuple[str, int]] | None = None) -> dict:
    return {
        "views": sum(days),
        "visitors": sum(max(1, v // 2) for v in days),
        "prev_views": prev_views,
        "prev_visitors": prev_views // 2,
        "days": [{"day": f"2026-10-{20 + i:02d}", "views": v, "visitors": max(1, v // 2)} for i, v in enumerate(days)],
        "top_posts": [],
        "referrers": [{"name": n, "views": v} for n, v in (referrers or [])],
        "countries": [],
        "search_terms": [],
        "collector_stale": stale,
        "collected_at": None,
    }


def _orders(count: int, prev: int, *, stale: bool = False, revenue: dict | None = None) -> dict:
    return {"count": count, "prev_count": prev, "revenue": revenue or ({"USD": 25.0 * count} if count else {}), "currency": "USD" if count else None, "aov": 25.0 if count else None, "cancelled": 0, "top_items": [], "countries": [], "sync_stale": stale, "sync_at": None, "prev_revenue": {}, "day_from": "2026-10-23", "day_to": "2026-10-29"}


def _site(**over) -> dict:
    base = {"checked_at": "2026-10-29T03:40:00+00:00", "age_hours": 5.0, "status": "ok", "urls_total": 120, "urls_broken": 0, "urls_slow": 0, "avg_response_ms": 400, "p95_response_ms": 900, "homepage_ok": True, "sitemap_ok": True, "open_findings": 0}
    base.update(over)
    return base


def _day(**parts) -> dict:
    payload = {"kind": "day", "period_key": "2026-10-29", "traffic": _traffic([30, 32, 28, 31, 29, 30, 30]), "orders": _orders(1, 1), "orders_7d": _orders(4, 3), "site": _site(), "content": {"generated": 20, "pending_review": 2, "approved_unpublished": 1, "live": 15, "published_in_period": 2}, "catalog": {"published": 9, "ready_to_upload": 2, "uploaded_draft": 3, "total": 20}}
    payload.update(parts)
    return payload


# ---------------------------------------------------------------- 规则层


def test_quiet_day_raises_nothing() -> None:
    assert digest.rules(_day()) == []


def test_traffic_rules_respect_the_small_base_rule() -> None:
    codes = lambda p: [f["code"] for f in digest.rules(p)]  # noqa: E731
    assert "traffic_drop" in codes(_day(traffic=_traffic([30, 32, 28, 31, 29, 30, 5])))  # 昨天 5,中位 30
    assert "traffic_drop" not in codes(_day(traffic=_traffic([8, 9, 7, 8, 9, 8, 1])))  # 基数太小,静默
    assert "traffic_spike" in codes(_day(traffic=_traffic([30, 32, 28, 31, 29, 30, 120])))
    assert "traffic_collector_stale" in codes(_day(traffic=_traffic([30] * 7, stale=True)))
    week = {**_day(), "kind": "week", "period_key": "2026-W44", "traffic": _traffic([30] * 7, prev_views=400)}
    assert "week_traffic_drop" in codes(week)  # 210 vs 400 = -48%
    assert [f for f in digest.rules(week) if f["code"] == "week_traffic_drop"][0]["severity"] == "warn"
    assert "week_traffic_drop" not in codes({**week, "traffic": _traffic([10] * 7, prev_views=100)})  # 上周不到 140,静默
    assert "week_traffic_spike" in codes({**week, "traffic": _traffic([60] * 7, prev_views=200)})


def test_order_and_site_rules() -> None:
    codes = lambda p: {f["code"]: f for f in digest.rules(p)}  # noqa: E731
    assert "orders_stall" in codes(_day(orders_7d=_orders(0, 4)))
    assert "orders_stall" not in codes(_day(orders_7d=_orders(0, 1)))  # 前一段才 1 单,不算断
    assert "order_sync_silent" in codes(_day(orders_7d=_orders(2, 2, stale=True)))
    week = {**_day(), "kind": "week", "orders": _orders(2, 8)}
    assert "orders_week_drop" in codes(week) and "orders_week_spike" in codes({**week, "orders": _orders(12, 6)})
    assert codes(_day(site=_site(urls_broken=3)))["site_broken_links"]["severity"] == "warn"
    assert codes(_day(site=_site(urls_slow=4)))["site_slow_pages"]["severity"] == "info"
    assert "site_slow_pages" in codes(_day(site=_site(p95_response_ms=3500)))
    assert "site_homepage_down" in codes(_day(site=_site(homepage_ok=False)))
    assert "site_check_missing" in codes(_day(site=_site(age_hours=50)))
    assert "site_check_missing" in codes(_day(site={"checked_at": None, "age_hours": None, "open_findings": 0}))
    assert "content_backlog" in codes(_day(content={"pending_review": 12, "approved_unpublished": 0, "live": 1, "generated": 20, "published_in_period": 0}))
    # 读不到的那一路一条都不报(读不到 ≠ 0)
    assert digest.rules(_day(traffic={"error": "读不到"}, orders_7d={"error": "读不到"}, site={"error": "读不到"})) == []


# ---------------------------------------------------------------- 人话 + 分节


def test_headline_and_sections_read_from_the_payload_only() -> None:
    payload = _day(traffic=_traffic([30, 32, 28, 31, 29, 30, 37], prev_views=150, referrers=[("Google", 80), ("Pinterest", 12)]), orders=_orders(2, 1, revenue={"USD": 61.98}))
    line = digest.headline(payload)
    assert line.startswith("昨日 18 人 37 次浏览") and "来源头一名 Google" in line and "2 单 USD 61.98" in line and "站点 0 坏链 0 慢页" in line
    sections = digest.sections(payload)
    headings = [s["heading"] for s in sections]
    assert headings[:2] == ["流量(Jetpack)", "订单(Woo)"] and "站点健康(H 哨兵)" in headings and "内容台" in headings and "店里的品" in headings
    traffic_rows = {r[0]: r for r in sections[0]["rows"]}
    assert traffic_rows["昨日浏览 / 访客"][1] == "37 / 18"
    assert traffic_rows["近 7 日浏览"][1] == "217" and traffic_rows["近 7 日浏览"][2] == "+45% 比前 7 天"
    assert traffic_rows["来源前五"][1] == "Google 80、Pinterest 12"
    order_rows = {r[0]: r for r in sections[1]["rows"]}
    assert order_rows["订单数"][1] == "2" and order_rows["订单数"][2] == "+100% 比前 7 天" and order_rows["销售额"][1] == "USD 61.98"
    assert order_rows["近 7 日订单"][1].startswith("4 单")
    # 读不到的路写「读不到」,不写 0
    broken = digest.sections(_day(traffic={"error": "读不到"}))
    assert broken[0]["rows"] == [["状态", "读不到", None]] and "流量读不到" in digest.headline(_day(traffic={"error": "读不到"}))
    week = {**_day(), "kind": "week", "period_key": "2026-W44", "traffic": _traffic([30] * 7, prev_views=150), "cards": {"created": 6, "approved": 4, "rejected": 1, "by_kind": {}}}
    assert digest.headline(week).startswith("本周 105 人 210 次浏览(比上周多 40%)")
    assert any(s["heading"] == "她这周的卡" and s["rows"][0][1] == "6 / 4 / 1" for s in digest.sections(week))


# ---------------------------------------------------------------- 日期 / 周一的闸


def test_week_keys_and_the_monday_gate() -> None:
    assert digest.week_key(date(2026, 10, 29)) == "2026-W44" and digest.week_days("2026-W44") == (date(2026, 10, 26), date(2026, 11, 1))
    monday_0630 = datetime(2026, 11, 2, 14, 30, tzinfo=UTC)  # LA 周一 06:30(PST)
    monday_0705 = datetime(2026, 11, 2, 15, 5, tzinfo=UTC)
    assert digest.previous_week_key(monday_0705) == "2026-W44" and digest.previous_week_key(datetime(2026, 11, 1, 20, 0, tzinfo=UTC)) == "2026-W43"  # 周日算的还是上上周
    assert not digest.should_run_weekly(monday_0630, exists=False)
    assert digest.should_run_weekly(monday_0705, exists=False)
    assert not digest.should_run_weekly(monday_0705, exists=True)
    assert digest.should_run_weekly(datetime(2026, 11, 4, 9, 0, tzinfo=UTC), exists=False)  # 周三补上周的
    assert worker_main.should_run_weekly(monday_0705, exists=False)
    start, end = digest.la_day_bounds(date(2026, 10, 29))
    assert start == datetime(2026, 10, 29, 7, 0, tzinfo=UTC) and end == datetime(2026, 10, 30, 7, 0, tzinfo=UTC)  # PDT


def test_order_stats_group_by_currency_and_count_only_real_orders() -> None:
    rows = [
        SimpleNamespace(woo_status="processing", total=Decimal("29.99"), currency="USD", items_json=[{"sku": "PTB-001", "name": "Battery", "qty": 2}], country="US"),
        SimpleNamespace(woo_status="completed", total=Decimal("40.00"), currency="USD", items_json=[{"sku": "PTB-001", "name": "Battery", "qty": 1}, {"sku": "CLL-001", "name": "Lantern", "qty": 1}], country="CA"),
        SimpleNamespace(woo_status="cancelled", total=Decimal("99.00"), currency="USD", items_json=[], country="US"),
        SimpleNamespace(woo_status="completed", total=Decimal("12.00"), currency="EUR", items_json=None, country="DE"),
    ]
    stats = digest._order_stats(rows)
    assert stats["count"] == 3 and stats["cancelled"] == 1
    assert stats["revenue"] == {"USD": 69.99, "EUR": 12.0} and stats["currency"] == "USD" and stats["aov"] == round(69.99 / 3, 2)
    assert stats["top_items"][0] == {"sku": "PTB-001", "name": "Battery", "qty": 3}
    assert stats["countries"][0] == {"name": "US", "count": 1} or {"name": "CA", "count": 1} in stats["countries"]
    assert digest._money({"USD": 1234.5, "EUR": 3}, "USD") == "USD 1,234.50 / EUR 3.00" and digest._money({}, None) == "0"


def test_reminder_mentions_the_weekly_digest_card() -> None:
    assert "本周运营看板" in worker_main.reminder_text(3, digest_cards=1)
    assert "本周运营看板" not in worker_main.reminder_text(3)


def test_digest_findings_become_live_issues_only_when_warn() -> None:
    from backend.app.modules.agent_series.suqinghe import brain

    snap = {"ops": {"day": "2026-10-29", "findings": [{"code": "traffic_drop", "severity": "warn", "text": "x"}, {"code": "site_slow_pages", "severity": "info", "text": "y"}]}}
    live, readable = brain.issues_in(snap)
    assert "ops" in readable and "ops:traffic_drop" in live and "ops:site_slow_pages" not in live
    live2, readable2 = brain.issues_in({"ops": {"error": "读不到"}})
    assert "ops" not in readable2 and not [k for k in live2 if k.startswith("ops:")]
