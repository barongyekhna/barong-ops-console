"""Search Console 搜索表现(10-30,运营看板第二期;11-03 改按「页」存)。

老板拍板用服务账号接(他在谷歌那边建账号、给 Search Console 开门、把 JSON 钥匙贴进控制台密钥管理,类型 google_search_console)。

11-03 改口径:站小,谷歌把每天的搜索词全部匿名——拉 90 天也是 0 个词,原来按「天×词×页」存永远是空表;
按天的全站合计、按页、按国家/设备都有数。现在每天拉两样(today-lag 那一天,谷歌数据要 2–3 天才定稿):
- 当天全站合计(含被匿名的词,比按页加起来准)→ 记在 sqh_gsc_days 那一天的行上;
- 当天每个落地页 → sqh_gsc_pages。
搜索词改按「截止最新一天的近 28 天」一窗去要(匿名门槛按窗口算,量上来就露出来)→ sqh_gsc_queries,一天一窗。
第一次接上先补 90 天;补历史时隔 10 分钟再拉一批,台账 sqh_gsc 按真实请求数扣。

周报「搜索缺口」全是查表,按近 28 天算:差一步的页 / 词(展现够、排 8–20)、展现高点击少的页、排得很靠后的需求词、本期新词。
喂内容台选题和选品池的动作在第三期(动作菜单),这一期只把缺口摆出来。
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from ....services.google_service_account import ServiceAccount, ServiceAccountError, fetch_access_token, parse_service_account
from .constants import LA, gsc_backfill_days, gsc_lag_days, gsc_site
from .models import SqhGscDay, SqhGscPage, SqhGscQuery

logger = logging.getLogger(__name__)
_X = SKIP_ORG_DATA_ISOLATION

KEY_TYPE = "google_search_console"
BINDING_MODULE_ID = "w.site_ops"  # 钥匙绑到 W 站点运营模块(和 17TRACK 同一处)
BINDING_KEY_ALIAS = "google_search_console"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
API_ROOT = "https://searchconsole.googleapis.com/webmasters/v3"
ROW_LIMIT = 5000
PULL_HOUR = 8  # LA 早上 8 点后拉(早间计划 7 点之后)
MAX_PULLS_PER_TICK = 10  # 一轮最多拉几天(补历史时),别一口气把台账吃光
BACKLOG_GAP_MINUTES = 10  # 补历史没补完:隔 10 分钟再拉下一批(一天一次要补 9 天)
FMT = 2  # sqh_gsc_days.fmt:2 = 11-03 新口径(全站合计 + 按页)拉过;旧的 1 自动重拉
CALLS_PER_DAY = 2  # 一天两次请求:全站合计 + 按页
QUERY_WINDOW_DAYS = 28  # 搜索词按窗口拉
GAP_WINDOW_DAYS = 28  # 缺口按近 28 天算(一周的量太少)
# 缺口规则的门槛(按近 28 天的合计)
QUICK_WIN_MIN_IMPRESSIONS = 50
QUICK_WIN_POSITION = (8.0, 20.0)
LOW_CTR_MIN_IMPRESSIONS = 100
LOW_CTR_MAX = 0.01
FAR_MIN_IMPRESSIONS = 30
FAR_POSITION = 20.0
NEW_QUERY_MIN_IMPRESSIONS = 10
TOP_N = 8


class GscNotConfigured(RuntimeError):
    """钥匙还没贴(老板没配服务账号)。拉数和看板都当「没接」,不是故障。"""


class GscError(RuntimeError):
    pass


# ---------------------------------------------------------------- 钥匙 / token / 查询


def credentials(db: Session) -> ServiceAccount:
    """钥匙按控制台家规取:密钥管理里登记 + 绑到 w.site_ops / google_search_console(贸易组织)。
    10-31 修:原来走 SecretManager,它的服务白名单里没有这一类,登记了也读不到。"""
    from ...w_series.logistics import _target_org_id
    from ....services.api_key_orchestration import (
        ApiKeyIsolationError,
        ApiKeyOrchestrationError,
        resolve_module_api_key_for_injection,
    )

    org_id = _target_org_id(db)
    if not org_id:
        raise GscNotConfigured("贸易组织不存在")
    try:
        context = resolve_module_api_key_for_injection(db, org_id=org_id, module_id=BINDING_MODULE_ID, key_alias=BINDING_KEY_ALIAS)
    except (ApiKeyIsolationError, ApiKeyOrchestrationError) as exc:
        raise GscNotConfigured(f"没有 Search Console 钥匙:{str(exc)[:80]}") from exc
    if str(context.key_type or "").strip().lower() != KEY_TYPE:
        raise GscNotConfigured(f"绑在 {BINDING_MODULE_ID}/{BINDING_KEY_ALIAS} 的钥匙类型不对:{context.key_type}")
    raw = str(context.header_value or "").strip()
    if not raw:
        raise GscNotConfigured("Search Console 钥匙为空")
    try:
        return parse_service_account(raw)
    except ServiceAccountError as exc:
        raise GscNotConfigured(f"Search Console 钥匙不对:{exc}") from exc


_token_cache: dict[str, tuple[str, float]] = {}


def access_token(account: ServiceAccount, *, transport: httpx.BaseTransport | None = None, now: float | None = None) -> str:
    """换 token,进程内缓存到过期前 5 分钟。"""
    import time

    current = now if now is not None else time.time()
    cached = _token_cache.get(account.client_email)
    if cached and cached[1] > current + 300:
        return cached[0]
    token, expires_in = fetch_access_token(account, scope=SCOPE, transport=transport)
    _token_cache[account.client_email] = (token, current + expires_in)
    return token


def query(
    account: ServiceAccount,
    *,
    start: date,
    end: date,
    dimensions: Iterable[str],
    site: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[dict[str, Any]]:
    """searchAnalytics/query(web,定稿数据)。每行 = {维度名: 值, clicks, impressions, ctr, position};维度为空 = 全站合计(没展现时 0 行)。"""
    dims = list(dimensions)
    site = site or gsc_site()
    token = access_token(account, transport=transport)
    body: dict[str, Any] = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": dims, "rowLimit": ROW_LIMIT, "type": "web", "dataState": "final"}
    url = f"{API_ROOT}/sites/{_quote(site)}/searchAnalytics/query"
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0), trust_env=False, transport=transport) as client:
        response = client.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, content=json.dumps(body))
    if response.status_code != 200:
        raise GscError(f"searchAnalytics {response.status_code}: {response.text[:200]}")
    limits = {"query": 300, "page": 1000}
    rows = []
    for row in (response.json() or {}).get("rows") or []:
        keys = row.get("keys") or []
        item: dict[str, Any] = {dim: str(keys[i] if i < len(keys) else "")[: limits.get(dim, 200)] for i, dim in enumerate(dims)}
        item.update(clicks=int(row.get("clicks") or 0), impressions=int(row.get("impressions") or 0), ctr=float(row.get("ctr") or 0.0), position=float(row.get("position") or 0.0))
        rows.append(item)
    return rows


def query_day(account: ServiceAccount, day: date, *, site: str | None = None, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """一天两样(两次请求):{"site": 全站合计 | None(没展现), "pages": [{page, clicks, impressions, ctr, position}]}。"""
    total = query(account, start=day, end=day, dimensions=[], site=site, transport=transport)
    pages = query(account, start=day, end=day, dimensions=["page"], site=site, transport=transport)
    return {"site": total[0] if total else None, "pages": pages}


def query_window(account: ServiceAccount, end: date, *, days: int = QUERY_WINDOW_DAYS, site: str | None = None, transport: httpx.BaseTransport | None = None) -> list[dict[str, Any]]:
    """截止 end 的近 days 天,按搜索词(一次请求)。站小时是空列表——谷歌把搜的人少的词全部匿名。"""
    return query(account, start=end - timedelta(days=days - 1), end=end, dimensions=["query"], site=site, transport=transport)


def _quote(site: str) -> str:
    from urllib.parse import quote

    return quote(site, safe="")


# ---------------------------------------------------------------- 落库 / 节律


def save_day(db: Session, day: date, data: dict[str, Any]) -> int:
    """一天的全站合计记在 sqh_gsc_days 那一行(fmt=2),每页一行进 sqh_gsc_pages。返回页面行数。"""
    db.execute(delete(SqhGscPage).where(SqhGscPage.day == day), execution_options=_X)
    seen: set[str] = set()
    for row in data.get("pages") or []:
        if row["page"] in seen:
            continue
        seen.add(row["page"])
        db.add(SqhGscPage(day=day, page=row["page"], clicks=row["clicks"], impressions=row["impressions"], ctr=row["ctr"], position=row["position"]))
    site = data.get("site") or {}
    mark = db.get(SqhGscDay, day) or SqhGscDay(day=day)
    mark.rows, mark.status, mark.error, mark.pulled_at, mark.fmt = len(seen), "ok", None, datetime.now(UTC), FMT
    mark.clicks, mark.impressions = int(site.get("clicks") or 0), int(site.get("impressions") or 0)
    mark.ctr, mark.position = float(site.get("ctr") or 0.0), float(site.get("position") or 0.0)
    db.add(mark)
    db.flush()
    return len(seen)


def save_window(db: Session, end: date, rows: list[dict[str, Any]], *, days: int = QUERY_WINDOW_DAYS) -> int:
    """截止 end 的搜索词窗口;拉到几行记在 end 那天的 window_rows 上(0 = 拉了但谷歌一个词都没给)。"""
    db.execute(delete(SqhGscQuery).where(SqhGscQuery.window_end == end, SqhGscQuery.window_days == days), execution_options=_X)
    seen: set[str] = set()
    for row in rows:
        if row["query"] in seen:
            continue
        seen.add(row["query"])
        db.add(SqhGscQuery(window_end=end, window_days=days, query=row["query"], clicks=row["clicks"], impressions=row["impressions"], ctr=row["ctr"], position=row["position"]))
    mark = db.get(SqhGscDay, end)
    if mark is not None:
        mark.window_rows = len(seen)
        db.add(mark)
    db.flush()
    return len(seen)


def mark_failed(db: Session, day: date, error: str) -> None:
    mark = db.get(SqhGscDay, day) or SqhGscDay(day=day)
    mark.status, mark.error, mark.pulled_at = "failed", error[:500], datetime.now(UTC)
    db.add(mark)
    db.flush()


def pulled_days(db: Session) -> set[date]:
    """按新口径(fmt=2)拉成的天。旧口径的天不算,会重拉。"""
    return set(db.scalars(select(SqhGscDay.day).where(SqhGscDay.status == "ok", SqhGscDay.fmt >= FMT), execution_options=_X))


def latest_day(now: datetime, *, lag: int | None = None) -> date:
    """谷歌定稿到的最新一天 = LA 今天 - lag。"""
    return now.astimezone(LA).date() - timedelta(days=lag or gsc_lag_days())


def days_due(now: datetime, *, have: set[date], lag: int | None = None, backfill: int | None = None) -> list[date]:
    """该拉哪几天:从 today-lag 往回数 backfill 天里没拉过的,新的在前。"""
    backfill = backfill or gsc_backfill_days()
    latest = latest_day(now, lag=lag)
    return [latest - timedelta(days=n) for n in range(backfill) if (latest - timedelta(days=n)) not in have]


def should_pull(now: datetime, *, last_attempt_at: datetime | None, more: bool = False) -> bool:
    """LA 8 点后一天一次;补历史没补完(上一批拉满、没出错、台账没停)就隔 BACKLOG_GAP_MINUTES 再来一批。"""
    local = now.astimezone(LA)
    if local.hour < PULL_HOUR:
        return False
    if last_attempt_at is None or last_attempt_at.astimezone(LA).date() != local.date():
        return True
    return more and now - last_attempt_at >= timedelta(minutes=BACKLOG_GAP_MINUTES)


def has_more(out: dict[str, Any]) -> bool:
    """这一批之后还要不要接着补:配了钥匙、这批真拉到了、没失败、台账没停、还有没拉的天。"""
    return bool(out.get("configured") and out.get("pulled") and not out.get("failed") and not out.get("stopped") and out.get("remaining"))


def pull_due(
    db: Session,
    *,
    now: datetime | None = None,
    fetch: Callable[[date], dict[str, Any]] | None = None,
    fetch_window: Callable[[date], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """拉该拉的天(一批最多 MAX_PULLS_PER_TICK 天,每天两次请求扣两次台账),再拉一次截止最新一天的搜索词窗口(没拉过才拉,扣一次)。
    台账用完就停,明天接着。没配钥匙 → {"configured": False};有钥匙 → configured/pulled/failed/rows/stopped/days/window/remaining。"""
    from r_system_v2.ra.quota_ledger import PROVIDER_SQH_GSC, RAQuotaExhaustedError, refund, try_consume

    now = now or datetime.now(UTC)
    if fetch is None or fetch_window is None:
        try:
            account = credentials(db)
        except GscNotConfigured as exc:
            return {"configured": False, "reason": str(exc)}
        fetch = fetch or (lambda day: query_day(account, day))  # noqa: E731
        fetch_window = fetch_window or (lambda end: query_window(account, end))  # noqa: E731
    out: dict[str, Any] = {"configured": True, "pulled": 0, "failed": 0, "rows": 0, "stopped": None, "days": [], "window": None, "remaining": 0}
    for day in days_due(now, have=pulled_days(db))[:MAX_PULLS_PER_TICK]:
        try:
            try_consume(db, PROVIDER_SQH_GSC, amount=CALLS_PER_DAY)
        except RAQuotaExhaustedError as exc:
            out["stopped"] = str(exc)[:120]
            break
        db.commit()  # 出网前放掉事务
        try:
            data = fetch(day)
        except Exception as exc:  # noqa: BLE001 —— 一天拉失败记一笔,下一天照拉;台账退回
            refund(db, PROVIDER_SQH_GSC, amount=CALLS_PER_DAY)
            mark_failed(db, day, f"{type(exc).__name__}: {exc}")
            db.commit()
            out["failed"] += 1
            logger.warning("gsc pull failed day=%s: %s", day, str(exc)[:200])
            continue
        n = save_day(db, day, data)
        db.commit()
        out["pulled"] += 1
        out["rows"] += n
        out["days"].append(day.isoformat())
    latest = latest_day(now)
    mark = db.get(SqhGscDay, latest)
    if out["stopped"] is None and mark is not None and mark.status == "ok" and (mark.fmt or 1) >= FMT and mark.window_rows is None:
        try:
            try_consume(db, PROVIDER_SQH_GSC, amount=1)
        except RAQuotaExhaustedError as exc:
            out["stopped"] = str(exc)[:120]
        else:
            db.commit()
            try:
                rows = fetch_window(latest)
            except Exception as exc:  # noqa: BLE001 —— 词窗口拉失败:退台账,明天再要
                refund(db, PROVIDER_SQH_GSC, amount=1)
                db.commit()
                out["window"] = {"end": latest.isoformat(), "error": f"{type(exc).__name__}: {exc}"[:200]}
                logger.warning("gsc query window failed end=%s: %s", latest, str(exc)[:200])
            else:
                out["window"] = {"end": latest.isoformat(), "rows": save_window(db, latest, rows)}
                db.commit()
    out["remaining"] = len(days_due(now, have=pulled_days(db)))
    return out


def last_pull(db: Session) -> tuple[date | None, datetime | None, str | None]:
    """(最近成功拉到的那一天, 什么时候拉的, 最近一次失败的错误)。"""
    ok = db.execute(select(SqhGscDay.day, SqhGscDay.pulled_at).where(SqhGscDay.status == "ok", SqhGscDay.fmt >= FMT).order_by(SqhGscDay.day.desc()).limit(1), execution_options=_X).first()
    failed = db.scalar(select(SqhGscDay.error).where(SqhGscDay.status == "failed").order_by(SqhGscDay.pulled_at.desc()).limit(1), execution_options=_X)
    return (ok[0], ok[1], failed) if ok else (None, None, failed)


# ---------------------------------------------------------------- 聚合 / 缺口(纯查表)


def _finish(clicks: float, impressions: float, pos_w: float) -> dict[str, Any]:
    imp = int(impressions)
    return {"clicks": int(clicks), "impressions": imp, "ctr": round(clicks / imp, 4) if imp else 0.0, "position": round(pos_w / imp, 1) if imp else 0.0}


def total(rows: Iterable[Any]) -> dict[str, Any]:
    """合计;位次按展现加权。"""
    clicks = impressions = 0
    pos_w = 0.0
    for r in rows:
        imp = int(r.impressions)
        clicks += int(r.clicks)
        impressions += imp
        pos_w += float(r.position) * imp
    return _finish(clicks, impressions, pos_w)


def group(rows: Iterable[Any], key: str) -> dict[str, dict[str, Any]]:
    """按某一列(page / query)合计;位次按展现加权。"""
    buckets: dict[str, list[float]] = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        imp = int(r.impressions)
        b = buckets[getattr(r, key)]
        b[0] += int(r.clicks)
        b[1] += imp
        b[2] += float(r.position) * imp
    return {k: _finish(*v) for k, v in buckets.items()}


def site_totals(db: Session, start: date, end: date) -> dict[str, Any]:
    """[start, end] 的全站合计(按天的全站行加起来,含被匿名的词)。"""
    return total(db.scalars(select(SqhGscDay).where(SqhGscDay.day >= start, SqhGscDay.day <= end, SqhGscDay.status == "ok", SqhGscDay.fmt >= FMT), execution_options=_X))


def pages_between(db: Session, start: date, end: date) -> dict[str, dict[str, Any]]:
    return group(db.scalars(select(SqhGscPage).where(SqhGscPage.day >= start, SqhGscPage.day <= end), execution_options=_X), "page")


def window_queries(db: Session, *, on_or_before: date, days: int = QUERY_WINDOW_DAYS) -> tuple[date | None, dict[str, dict[str, Any]]]:
    """截止 on_or_before 之前最近拉过的那一窗搜索词:(窗口截止日 | None, {词: 合计})。"""
    end = db.scalar(
        select(SqhGscDay.day).where(SqhGscDay.day <= on_or_before, SqhGscDay.window_rows.is_not(None)).order_by(SqhGscDay.day.desc()).limit(1),
        execution_options=_X,
    )
    if end is None:
        return None, {}
    rows = db.scalars(select(SqhGscQuery).where(SqhGscQuery.window_end == end, SqhGscQuery.window_days == days), execution_options=_X)
    return end, group(rows, "query")


def _top(items: dict[str, dict[str, Any]], *, key: str, threshold: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
    picked = sorted(((k, v) for k, v in items.items() if threshold(v)), key=lambda kv: -kv[1]["impressions"])[:TOP_N]
    return [{key: k, **v} for k, v in picked]


def gaps(pages: dict[str, dict[str, Any]], queries: dict[str, dict[str, Any]], prev_queries: dict[str, dict[str, Any]] | None, *, product_terms: list[str] | None = None) -> dict[str, Any]:
    """缺口(都按近 28 天):差一步的页 / 词、展现高点击少的页、排得很靠后的需求词(标有没有对应产品)、本期新词(没有上一窗就不比)。
    全是门槛过滤,不打分不猜。"""
    term_tokens = [_tokens(t) for t in (product_terms or []) if t]
    term_tokens = [t for t in term_tokens if t]

    def matches_product(query: str) -> bool:
        """词和某个品的名字/主关键词至少共用两个实词(品名只有一个实词就一个)。"""
        q = _tokens(query)
        return any(len(q & t) >= min(2, len(t)) for t in term_tokens)

    def near(v: dict[str, Any]) -> bool:
        return v["impressions"] >= QUICK_WIN_MIN_IMPRESSIONS and QUICK_WIN_POSITION[0] <= v["position"] <= QUICK_WIN_POSITION[1]

    far = _top(queries, key="query", threshold=lambda v: v["impressions"] >= FAR_MIN_IMPRESSIONS and v["position"] > FAR_POSITION)
    return {
        "quick_win_pages": _top(pages, key="page", threshold=near),
        "quick_wins": _top(queries, key="query", threshold=near),
        "low_ctr_pages": _top(pages, key="page", threshold=lambda v: v["impressions"] >= LOW_CTR_MIN_IMPRESSIONS and v["ctr"] < LOW_CTR_MAX),
        "far_queries": [{**x, "has_product": matches_product(x["query"])} for x in far],
        "new_queries": [] if prev_queries is None else _top({q: v for q, v in queries.items() if q not in prev_queries}, key="query", threshold=lambda v: v["impressions"] >= NEW_QUERY_MIN_IMPRESSIONS),
    }


def page_label(url: str) -> str:
    """页面在看板上的短名:路径最后一段;首页叫「首页」。"""
    path = urlparse(url).path.strip("/")
    return "首页" if not path else path.split("/")[-1][:60]


_STOPWORDS = {"the", "and", "for", "with", "of", "to", "in", "a", "an", "pack", "set", "kit", "new", "best", "buy", "cheap", "near", "me", "usa", "us"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 3 and t not in _STOPWORDS}


def product_terms(db: Session) -> list[str]:
    """K 里在卖/在做的品的主关键词和英文名,给「排得远的词有没有对应产品」用。"""
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P

    out: list[str] = []
    for kw, name in db.execute(select(P.primary_keyword, P.product_name_en).where(P.parent_product_id.is_(None), P.review_status != "archived"), execution_options=_X):
        for t in (kw, name):
            if t and str(t).strip():
                out.append(str(t).strip())
    return out


def search_part(db: Session, *, start: date, end: date) -> dict[str, Any]:
    """给看板的「搜索」节:[start, end] 的全站合计 + 前一同长区间 + 页面榜 + 搜索词(最近一窗)+ 近 28 天的缺口 + 数据到哪天。
    没接钥匙 → {"configured": False};接了但一天都没拉到 → last_day None。"""
    span = (end - start).days + 1
    have = pulled_days(db)
    if not have:
        try:
            credentials(db)
        except GscNotConfigured as exc:
            return {"configured": False, "reason": str(exc)}
    cur = site_totals(db, start, end)
    prev = site_totals(db, start - timedelta(days=span), start - timedelta(days=1))
    pages = pages_between(db, start, end)
    gap_from = end - timedelta(days=GAP_WINDOW_DAYS - 1)
    gap_total = site_totals(db, gap_from, end)
    window_end, queries = window_queries(db, on_or_before=end)
    prev_end, prev_queries = window_queries(db, on_or_before=window_end - timedelta(days=7)) if window_end else (None, {})
    last_day, pulled_at, last_error = last_pull(db)
    covered = sorted(d for d in have if start <= d <= end)
    top_pages = sorted(pages.items(), key=lambda kv: (-kv[1]["clicks"], -kv[1]["impressions"]))[:TOP_N]
    top_queries = sorted(queries.items(), key=lambda kv: (-kv[1]["clicks"], -kv[1]["impressions"]))[:TOP_N]
    return {
        "configured": True,
        "day_from": start.isoformat(),
        "day_to": end.isoformat(),
        "covered_days": len(covered),
        "last_day": last_day.isoformat() if last_day else None,
        "pulled_at": pulled_at.isoformat() if pulled_at else None,
        "last_error": last_error,
        "clicks": cur["clicks"],
        "impressions": cur["impressions"],
        "ctr": cur["ctr"],
        "position": cur["position"],
        "prev_clicks": prev["clicks"],
        "prev_impressions": prev["impressions"],
        "top_pages": [{"page": p, "label": page_label(p), **v} for p, v in top_pages],
        "top_queries": [{"query": q, **v} for q, v in top_queries],
        "query_window": {"end": window_end.isoformat(), "days": QUERY_WINDOW_DAYS, "rows": len(queries)} if window_end else None,
        # 拉过词窗口、窗口里有展现,谷歌却一个词都没给 = 全被匿名(站小);看板上要说清楚,别让人以为没拉
        "queries_hidden": bool(window_end and not queries and site_totals(db, window_end - timedelta(days=QUERY_WINDOW_DAYS - 1), window_end)["impressions"] > 0),
        "gap_window": {"from": gap_from.isoformat(), "to": end.isoformat(), "impressions": gap_total["impressions"]},
        "gaps": gaps(pages_between(db, gap_from, end), queries, prev_queries if prev_end else None, product_terms=product_terms(db)),
    }
