"""流量归一化、落库、汇总。

Jetpack 七个接口的形状（2026-09-05 实测）：
- visits: {"date","unit","fields":["period","views","visitors",...],"data":[[period,...],...],"utc_offset"}
- top-posts: {"days":{"YYYY-MM-DD":{"postviews":[{id,href,title,views,...}],"total_views","other_views"}}}
- referrers: {"days":{d:{"groups":[{group,name,url,icon,total,...}],"other_views","total_views"}},"utc_offset"}
- country-views: {"days":{d:{"views":[{country_code,views}],...}},"country-info":{code:{country_full,...}},"utc_offset"}
- search-terms: {"days":{d:{"search_terms":[{term,views}],"encrypted_search_terms":n,...}},"utc_offset"}
- clicks: {"days":{d:{"clicks":[{name,url,views,...}],...}},"utc_offset"}

每个分支独立解析、独立失败：一路形状变了只丢那一列，绝不让整批作废，
也绝不用本批没带的分支去覆盖库里已有的 JSON 列。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ....services.worker_heartbeat import list_heartbeats
from .models import WTrafficDaily, WTrafficHourly
from .schemas import TrafficIngestRequest

logger = logging.getLogger(__name__)

WORKER_NAME = "w-traffic"
WORKER_MODULE_KEY = "w"
EXPECTED_INTERVAL_SECONDS = 600
# 设计稿定的阈值：两轮没成功就算停采，卡片变红。
TRAFFIC_STALE_AFTER = timedelta(minutes=20)
# 站点时区。Jetpack 按它分日；实测 -05:00。不一致时只告警不改。
DEFAULT_SITE_UTC_OFFSET = "-05:00"
MAX_LIST_ITEMS = 10
MAX_RANGE_DAYS = 92


@dataclass
class DayRow:
    views: int = 0
    visitors: int = 0
    top_posts: list[dict[str, Any]] | None = None
    referrers: list[dict[str, Any]] | None = None
    countries: list[dict[str, Any]] | None = None
    search_terms: dict[str, Any] | None = None
    clicks: list[dict[str, Any]] | None = None
    present: set[str] = field(default_factory=set)


@dataclass
class NormalizedTraffic:
    utc_offset: str
    days: dict[date, DayRow]
    hours: dict[datetime, tuple[int, int]]
    warnings: list[str]


# ---------------------------------------------------------------- 归一化


def parse_utc_offset(value: str | None) -> timezone:
    raw = (value or DEFAULT_SITE_UTC_OFFSET).strip()
    sign = -1 if raw.startswith("-") else 1
    body = raw.lstrip("+-")
    try:
        hours_part, _, minutes_part = body.partition(":")
        hours = int(hours_part or "0")
        minutes = int(minutes_part or "0")
    except ValueError:
        hours, minutes = 5, 0
        sign = -1
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def _pick_utc_offset(payload: TrafficIngestRequest) -> tuple[str, list[str]]:
    warnings: list[str] = []
    candidates: list[str] = []
    if payload.utc_offset:
        candidates.append(payload.utc_offset)
    for branch in (
        payload.visits_day,
        payload.visits_hour,
        payload.referrers,
        payload.country_views,
        payload.search_terms,
        payload.clicks,
    ):
        if isinstance(branch, dict) and isinstance(branch.get("utc_offset"), str):
            candidates.append(branch["utc_offset"])
    chosen = candidates[0] if candidates else DEFAULT_SITE_UTC_OFFSET
    if chosen != DEFAULT_SITE_UTC_OFFSET:
        warnings.append(
            f"site utc_offset {chosen} differs from configured {DEFAULT_SITE_UTC_OFFSET}"
        )
        logger.warning("w-traffic: %s", warnings[-1])
    return chosen, warnings


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_day(key: Any) -> date | None:
    if not isinstance(key, str):
        return None
    try:
        return date.fromisoformat(key[:10])
    except ValueError:
        return None


def _visits_rows(branch: dict[str, Any] | None) -> list[tuple[str, int, int]]:
    """按 `fields` 找列，不假定顺序。返回 (period, views, visitors)。"""
    if not isinstance(branch, dict):
        return []
    fields = branch.get("fields")
    data = branch.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        return []
    try:
        period_index = fields.index("period")
        views_index = fields.index("views")
        visitors_index = fields.index("visitors")
    except ValueError:
        return []
    rows: list[tuple[str, int, int]] = []
    for row in data:
        if not isinstance(row, list) or len(row) <= max(period_index, views_index, visitors_index):
            continue
        period = row[period_index]
        if not isinstance(period, str):
            continue
        rows.append((period, _safe_int(row[views_index]), _safe_int(row[visitors_index])))
    return rows


def _days_map(branch: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(branch, dict):
        return {}
    days = branch.get("days")
    return days if isinstance(days, dict) else {}


def _top_posts(day_payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for post in day_payload.get("postviews") or []:
        if not isinstance(post, dict):
            continue
        out.append(
            {
                "id": post.get("id"),
                "title": str(post.get("title") or "")[:200],
                "href": str(post.get("href") or "")[:500],
                "type": post.get("type"),
                "views": _safe_int(post.get("views")),
            }
        )
    out.sort(key=lambda item: item["views"], reverse=True)
    return out[:MAX_LIST_ITEMS]


def _referrers(day_payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for group in day_payload.get("groups") or []:
        if not isinstance(group, dict):
            continue
        out.append(
            {
                "group": group.get("group"),
                "name": str(group.get("name") or "")[:200],
                "url": str(group.get("url") or "")[:500],
                "views": _safe_int(group.get("total")),
            }
        )
    out.sort(key=lambda item: item["views"], reverse=True)
    return out[:MAX_LIST_ITEMS]


def _countries(
    day_payload: dict[str, Any], country_info: dict[str, Any]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in day_payload.get("views") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("country_code") or "")[:8]
        info = country_info.get(code) if isinstance(country_info, dict) else None
        name = info.get("country_full") if isinstance(info, dict) else None
        out.append({"code": code, "name": str(name or code)[:100], "views": _safe_int(row.get("views"))})
    out.sort(key=lambda item: item["views"], reverse=True)
    return out[:MAX_LIST_ITEMS]


def _search_terms(day_payload: dict[str, Any]) -> dict[str, Any]:
    terms: list[dict[str, Any]] = []
    for row in day_payload.get("search_terms") or []:
        if not isinstance(row, dict):
            continue
        terms.append({"term": str(row.get("term") or "")[:200], "views": _safe_int(row.get("views"))})
    terms.sort(key=lambda item: item["views"], reverse=True)
    return {
        "terms": terms[:MAX_LIST_ITEMS],
        "encrypted": _safe_int(day_payload.get("encrypted_search_terms")),
    }


def _clicks(day_payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in day_payload.get("clicks") or []:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "name": str(row.get("name") or "")[:200],
                "url": str(row.get("url") or "")[:500],
                "views": _safe_int(row.get("views")),
            }
        )
    out.sort(key=lambda item: item["views"], reverse=True)
    return out[:MAX_LIST_ITEMS]


def normalize(payload: TrafficIngestRequest) -> NormalizedTraffic:
    utc_offset, warnings = _pick_utc_offset(payload)
    site_tz = parse_utc_offset(utc_offset)
    days: dict[date, DayRow] = {}
    hours: dict[datetime, tuple[int, int]] = {}

    def row_for(day: date) -> DayRow:
        return days.setdefault(day, DayRow())

    # visits by day
    try:
        for period, views, visitors in _visits_rows(payload.visits_day):
            day = _parse_day(period)
            if day is None:
                continue
            row = row_for(day)
            row.views, row.visitors = views, visitors
            row.present.add("visits")
    except Exception:  # noqa: BLE001
        warnings.append("visits_day branch unparsable")
        logger.exception("w-traffic: visits_day branch unparsable")

    # visits by hour
    try:
        for period, views, visitors in _visits_rows(payload.visits_hour):
            try:
                naive = datetime.fromisoformat(period)
            except ValueError:
                continue
            bucket = naive.replace(tzinfo=site_tz)
            hours[bucket] = (views, visitors)
    except Exception:  # noqa: BLE001
        warnings.append("visits_hour branch unparsable")
        logger.exception("w-traffic: visits_hour branch unparsable")

    branches: tuple[tuple[str, dict[str, Any] | None, Any], ...] = (
        ("top_posts", payload.top_posts, _top_posts),
        ("referrers", payload.referrers, _referrers),
        ("search_terms", payload.search_terms, _search_terms),
        ("clicks", payload.clicks, _clicks),
    )
    for name, branch, parser in branches:
        try:
            for key, day_payload in _days_map(branch).items():
                day = _parse_day(key)
                if day is None or not isinstance(day_payload, dict):
                    continue
                row = row_for(day)
                setattr(row, name, parser(day_payload))
                row.present.add(name)
        except Exception:  # noqa: BLE001
            warnings.append(f"{name} branch unparsable")
            logger.exception("w-traffic: %s branch unparsable", name)

    try:
        country_info = (
            payload.country_views.get("country-info")
            if isinstance(payload.country_views, dict)
            else None
        ) or {}
        for key, day_payload in _days_map(payload.country_views).items():
            day = _parse_day(key)
            if day is None or not isinstance(day_payload, dict):
                continue
            row = row_for(day)
            row.countries = _countries(day_payload, country_info)
            row.present.add("countries")
    except Exception:  # noqa: BLE001
        warnings.append("country_views branch unparsable")
        logger.exception("w-traffic: country_views branch unparsable")

    return NormalizedTraffic(utc_offset=utc_offset, days=days, hours=hours, warnings=warnings)


# ---------------------------------------------------------------- 落库

_JSON_COLUMNS: dict[str, str] = {
    "top_posts": "top_posts_json",
    "referrers": "referrers_json",
    "countries": "countries_json",
    "search_terms": "search_terms_json",
    "clicks": "clicks_json",
}


def upsert_traffic(
    db: Session, *, workspace_key: str, normalized: NormalizedTraffic
) -> tuple[int, int]:
    now = datetime.now(UTC)
    days_written = 0
    for day, row in sorted(normalized.days.items()):
        if not row.present:
            continue
        values: dict[str, Any] = {
            "id": uuid4(),
            "workspace_key": workspace_key,
            "day": day,
            "updated_at": now,
        }
        on_conflict: dict[str, Any] = {"updated_at": now}
        if "visits" in row.present:
            values["views"] = row.views
            values["visitors"] = row.visitors
            on_conflict["views"] = row.views
            on_conflict["visitors"] = row.visitors
        for attr, column in _JSON_COLUMNS.items():
            if attr in row.present:
                payload = getattr(row, attr)
                values[column] = payload
                on_conflict[column] = payload
        stmt = pg_insert(WTrafficDaily).values(**values)
        db.execute(
            stmt.on_conflict_do_update(
                constraint="uq_w_traffic_daily_ws_day", set_=on_conflict
            )
        )
        days_written += 1

    hours_written = 0
    for bucket_at, (views, visitors) in sorted(normalized.hours.items()):
        stmt = pg_insert(WTrafficHourly).values(
            id=uuid4(),
            workspace_key=workspace_key,
            bucket_at=bucket_at,
            views=views,
            visitors=visitors,
            updated_at=now,
        )
        db.execute(
            stmt.on_conflict_do_update(
                constraint="uq_w_traffic_hourly_ws_bucket",
                set_={"views": views, "visitors": visitors, "updated_at": now},
            )
        )
        hours_written += 1
    return days_written, hours_written


# ---------------------------------------------------------------- 汇总


def site_today(now: datetime | None = None) -> date:
    current = now or datetime.now(UTC)
    return current.astimezone(parse_utc_offset(DEFAULT_SITE_UTC_OFFSET)).date()


def collector_state(db: Session, now: datetime | None = None) -> tuple[datetime | None, bool]:
    """(最近一次采集成功时间, 是否已停采)。只认心跳表，不认别的。"""
    current = now or datetime.now(UTC)
    for beat in list_heartbeats(db):
        if beat["worker_name"] != WORKER_NAME:
            continue
        raw = beat["last_success_at"]
        if not raw:
            return None, True
        last_success = datetime.fromisoformat(raw)
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=UTC)
        return last_success, (current - last_success) > TRAFFIC_STALE_AFTER
    return None, True


def _rows_between(
    db: Session, workspace_key: str, day_from: date, day_to: date
) -> dict[date, WTrafficDaily]:
    rows = db.scalars(
        select(WTrafficDaily)
        .where(
            WTrafficDaily.workspace_key == workspace_key,
            WTrafficDaily.day >= day_from,
            WTrafficDaily.day <= day_to,
        )
        .order_by(WTrafficDaily.day)
    )
    return {row.day: row for row in rows}


def _aggregate(
    rows: dict[date, WTrafficDaily], attr: str, key: str
) -> list[dict[str, Any]]:
    """把区间内每天的列表按 key 合并求和，views 降序。"""
    totals: dict[str, dict[str, Any]] = {}
    for row in rows.values():
        for item in getattr(row, attr) or []:
            if not isinstance(item, dict):
                continue
            ident = str(item.get(key) or "")
            if not ident:
                continue
            bucket = totals.setdefault(ident, {**item, "views": 0})
            bucket["views"] += _safe_int(item.get("views"))
    return sorted(totals.values(), key=lambda item: item["views"], reverse=True)


def _aggregate_search_terms(rows: dict[date, WTrafficDaily]) -> tuple[list[dict[str, Any]], int]:
    totals: dict[str, int] = {}
    encrypted = 0
    for row in rows.values():
        payload = row.search_terms_json or {}
        if not isinstance(payload, dict):
            continue
        encrypted += _safe_int(payload.get("encrypted"))
        for item in payload.get("terms") or []:
            if isinstance(item, dict) and item.get("term"):
                totals[str(item["term"])] = totals.get(str(item["term"]), 0) + _safe_int(
                    item.get("views")
                )
    terms = [{"term": term, "views": views} for term, views in totals.items()]
    terms.sort(key=lambda item: item["views"], reverse=True)
    return terms, encrypted


def _day_dict(day: date, row: WTrafficDaily | None) -> dict[str, Any]:
    return {
        "day": day,
        "views": int(row.views) if row else 0,
        "visitors": int(row.visitors) if row else 0,
    }


def range_report(
    db: Session,
    *,
    workspace_key: str,
    day_from: date,
    day_to: date,
    now: datetime | None = None,
) -> dict[str, Any]:
    """区间报表：逐日曲线 + 与前一等长区间对比 + 各维度聚合。"""
    if day_to < day_from:
        raise ValueError("day_to must not precede day_from")
    span = (day_to - day_from).days + 1
    if span > MAX_RANGE_DAYS:
        raise ValueError(f"range exceeds {MAX_RANGE_DAYS} days")
    prev_to = day_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=span - 1)

    rows = _rows_between(db, workspace_key, day_from, day_to)
    prev_rows = _rows_between(db, workspace_key, prev_from, prev_to)
    days = [_day_dict(day_from + timedelta(days=offset), rows.get(day_from + timedelta(days=offset))) for offset in range(span)]

    today = site_today(now)
    yesterday = today - timedelta(days=1)
    today_row = rows.get(today) or prev_rows.get(today)
    yesterday_row = rows.get(yesterday) or prev_rows.get(yesterday)

    top_posts = _aggregate(rows, "top_posts_json", "href")
    referrers = _aggregate(rows, "referrers_json", "name")
    countries = _aggregate(rows, "countries_json", "code")
    search_terms, encrypted = _aggregate_search_terms(rows)
    clicks = _aggregate(rows, "clicks_json", "url")
    collected_at, stale = collector_state(db, now)

    return {
        "site_utc_offset": DEFAULT_SITE_UTC_OFFSET,
        "day_from": day_from,
        "day_to": day_to,
        "days": days,
        "views": sum(item["views"] for item in days),
        "visitors": sum(item["visitors"] for item in days),
        "prev_views": sum(int(row.views) for row in prev_rows.values()),
        "prev_visitors": sum(int(row.visitors) for row in prev_rows.values()),
        "today": _day_dict(today, today_row) if today_row else None,
        "yesterday": _day_dict(yesterday, yesterday_row) if yesterday_row else None,
        "top_post": top_posts[0] if top_posts else None,
        "top_referrer": referrers[0] if referrers else None,
        "top_country": countries[0] if countries else None,
        "collected_at": collected_at,
        "collector_stale": stale,
        "top_posts": top_posts[:MAX_LIST_ITEMS],
        "referrers": referrers[:MAX_LIST_ITEMS],
        "countries": countries[:MAX_LIST_ITEMS],
        "search_terms": search_terms[:MAX_LIST_ITEMS],
        "encrypted_search_terms": encrypted,
        "clicks": clicks[:MAX_LIST_ITEMS],
    }


def summary(
    db: Session, *, workspace_key: str, days: int = 7, now: datetime | None = None
) -> dict[str, Any]:
    """最近 N 天（含今天，按站点时区）。"""
    day_to = site_today(now)
    day_from = day_to - timedelta(days=max(1, days) - 1)
    return range_report(db, workspace_key=workspace_key, day_from=day_from, day_to=day_to, now=now)


# ---------------------------------------------------------------- 主页卡


def load_home_card(
    db: Session,
    *,
    workspace_key: str,
    user: Any,
    permission_keys: frozenset[str],
    is_full_access: bool,
    **_: Any,
) -> Any:
    from ...home.schemas import HomeCardRead, HomeTrafficSummaryRead

    report = summary(db, workspace_key=workspace_key, days=7)
    extra = HomeTrafficSummaryRead.model_validate(report)
    return HomeCardRead(
        card_id="site-traffic",
        module_key=None,
        count=extra.visitors,
        items=[],
        freshness=extra.collected_at or datetime.now(UTC),
        actions=["range"],
        extra=extra.model_dump(mode="json"),
        severity="error" if extra.collector_stale else "ok",
    )
