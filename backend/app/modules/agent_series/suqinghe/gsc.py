"""Search Console 搜索表现(10-30,运营看板第二期)。

老板拍板用服务账号接(他在谷歌那边建账号、给 Search Console 开门、把 JSON 钥匙贴进控制台密钥管理,类型 google_search_console)。
她每天拉一次 today-lag(谷歌数据要 2–3 天才定稿)那一天的「词 × 页」表现,落 sqh_gsc_daily;拉过的天记在 sqh_gsc_days(没展现的天也记,免得天天重拉)。
第一次接上先补 90 天,按台账 sqh_gsc(30/天)分几天拉完。

周报多一节「搜索缺口」,全是查表:差一步的词(展现够、排 8–20)、展现高点击少的页、我们排得很靠后的需求词、本周新词。
喂内容台选题和选品池的动作在第三期(动作菜单),这一期只把缺口摆出来。
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from ....services.google_service_account import ServiceAccount, ServiceAccountError, fetch_access_token, parse_service_account
from .constants import LA, gsc_backfill_days, gsc_lag_days, gsc_site
from .models import SqhGscDaily, SqhGscDay

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
# 缺口规则的门槛
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


def query_day(account: ServiceAccount, day: date, *, site: str | None = None, transport: httpx.BaseTransport | None = None) -> list[dict[str, Any]]:
    """一天的「词 × 页」表现(web,最多 ROW_LIMIT 行,按点击降序是谷歌默认)。返回 [{query, page, clicks, impressions, ctr, position}]。"""
    site = site or gsc_site()
    token = access_token(account, transport=transport)
    body = {"startDate": day.isoformat(), "endDate": day.isoformat(), "dimensions": ["query", "page"], "rowLimit": ROW_LIMIT, "type": "web", "dataState": "final"}
    url = f"{API_ROOT}/sites/{_quote(site)}/searchAnalytics/query"
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0), trust_env=False, transport=transport) as client:
        response = client.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, content=json.dumps(body))
    if response.status_code != 200:
        raise GscError(f"searchAnalytics {response.status_code}: {response.text[:200]}")
    rows = []
    for row in (response.json() or {}).get("rows") or []:
        keys = row.get("keys") or ["", ""]
        rows.append({"query": str(keys[0])[:300], "page": str(keys[1])[:1000], "clicks": int(row.get("clicks") or 0), "impressions": int(row.get("impressions") or 0), "ctr": float(row.get("ctr") or 0.0), "position": float(row.get("position") or 0.0)})
    return rows


def _quote(site: str) -> str:
    from urllib.parse import quote

    return quote(site, safe="")


# ---------------------------------------------------------------- 落库 / 节律


def save_day(db: Session, day: date, rows: list[dict[str, Any]]) -> int:
    db.execute(delete(SqhGscDaily).where(SqhGscDaily.day == day), execution_options=_X)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["query"], row["page"])
        if key in seen:
            continue
        seen.add(key)
        db.add(SqhGscDaily(day=day, query=row["query"], page=row["page"], clicks=row["clicks"], impressions=row["impressions"], ctr=row["ctr"], position=row["position"]))
    mark = db.get(SqhGscDay, day) or SqhGscDay(day=day)
    mark.rows, mark.status, mark.error, mark.pulled_at = len(seen), "ok", None, datetime.now(UTC)
    db.add(mark)
    db.flush()
    return len(seen)


def mark_failed(db: Session, day: date, error: str) -> None:
    mark = db.get(SqhGscDay, day) or SqhGscDay(day=day)
    mark.status, mark.error, mark.pulled_at = "failed", error[:500], datetime.now(UTC)
    db.add(mark)
    db.flush()


def pulled_days(db: Session) -> set[date]:
    return set(db.scalars(select(SqhGscDay.day).where(SqhGscDay.status == "ok"), execution_options=_X))


def days_due(now: datetime, *, have: set[date], lag: int | None = None, backfill: int | None = None) -> list[date]:
    """该拉哪几天:从 today-lag 往回数 backfill 天里没拉过的,新的在前。"""
    lag = lag or gsc_lag_days()
    backfill = backfill or gsc_backfill_days()
    latest = now.astimezone(LA).date() - timedelta(days=lag)
    return [latest - timedelta(days=n) for n in range(backfill) if (latest - timedelta(days=n)) not in have]


def should_pull(now: datetime, *, last_attempt_day: date | None) -> bool:
    local = now.astimezone(LA)
    return local.hour >= PULL_HOUR and last_attempt_day != local.date()


def pull_due(db: Session, *, now: datetime | None = None, fetch: Callable[[date], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """拉该拉的天(一轮最多 MAX_PULLS_PER_TICK 天),每天扣一次台账;台账用完就停,明天接着。
    没配钥匙 → {"configured": False};有钥匙 → {"configured": True, "pulled": n, "failed": n, "stopped": reason|None}。"""
    from r_system_v2.ra.quota_ledger import PROVIDER_SQH_GSC, RAQuotaExhaustedError, refund, try_consume

    now = now or datetime.now(UTC)
    if fetch is None:
        try:
            account = credentials(db)
        except GscNotConfigured as exc:
            return {"configured": False, "reason": str(exc)}
        fetch = lambda day: query_day(account, day)  # noqa: E731
    out: dict[str, Any] = {"configured": True, "pulled": 0, "failed": 0, "rows": 0, "stopped": None, "days": []}
    for day in days_due(now, have=pulled_days(db))[:MAX_PULLS_PER_TICK]:
        try:
            try_consume(db, PROVIDER_SQH_GSC, amount=1)
        except RAQuotaExhaustedError as exc:
            out["stopped"] = str(exc)[:120]
            break
        db.commit()  # 出网前放掉事务
        try:
            rows = fetch(day)
        except Exception as exc:  # noqa: BLE001 —— 一天拉失败记一笔,下一天照拉;台账退回
            refund(db, PROVIDER_SQH_GSC, amount=1)
            mark_failed(db, day, f"{type(exc).__name__}: {exc}")
            db.commit()
            out["failed"] += 1
            logger.warning("gsc pull failed day=%s: %s", day, str(exc)[:200])
            continue
        n = save_day(db, day, rows)
        db.commit()
        out["pulled"] += 1
        out["rows"] += n
        out["days"].append(day.isoformat())
    return out


def last_pull(db: Session) -> tuple[date | None, datetime | None, str | None]:
    """(最近成功拉到的那一天, 什么时候拉的, 最近一次失败的错误)。"""
    ok = db.execute(select(SqhGscDay.day, SqhGscDay.pulled_at).where(SqhGscDay.status == "ok").order_by(SqhGscDay.day.desc()).limit(1), execution_options=_X).first()
    failed = db.scalar(select(SqhGscDay.error).where(SqhGscDay.status == "failed").order_by(SqhGscDay.pulled_at.desc()).limit(1), execution_options=_X)
    return (ok[0], ok[1], failed) if ok else (None, None, failed)


# ---------------------------------------------------------------- 聚合 / 缺口(纯查表)


def _rows_between(db: Session, start: date, end: date) -> list[Any]:
    return list(db.scalars(select(SqhGscDaily).where(SqhGscDaily.day >= start, SqhGscDaily.day <= end), execution_options=_X))


def aggregate(rows: list[Any]) -> dict[str, Any]:
    """按词、按页合计;位次按展现加权。"""
    by_query: dict[str, dict[str, float]] = defaultdict(lambda: {"clicks": 0, "impressions": 0, "pos_w": 0.0})
    by_page: dict[str, dict[str, float]] = defaultdict(lambda: {"clicks": 0, "impressions": 0, "pos_w": 0.0})
    total_clicks = total_impr = 0
    pos_w = 0.0
    for r in rows:
        imp, clk, pos = int(r.impressions), int(r.clicks), float(r.position)
        for bucket in (by_query[r.query], by_page[r.page]):
            bucket["clicks"] += clk
            bucket["impressions"] += imp
            bucket["pos_w"] += pos * imp
        total_clicks += clk
        total_impr += imp
        pos_w += pos * imp

    def finish(d: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        out = {}
        for k, v in d.items():
            imp = v["impressions"]
            out[k] = {"clicks": int(v["clicks"]), "impressions": int(imp), "ctr": round(v["clicks"] / imp, 4) if imp else 0.0, "position": round(v["pos_w"] / imp, 1) if imp else 0.0}
        return out

    return {"clicks": total_clicks, "impressions": total_impr, "ctr": round(total_clicks / total_impr, 4) if total_impr else 0.0, "position": round(pos_w / total_impr, 1) if total_impr else 0.0, "queries": finish(by_query), "pages": finish(by_page)}


def gaps(current: dict[str, Any], previous: dict[str, Any], *, product_terms: list[str] | None = None) -> dict[str, Any]:
    """缺口:差一步的词 / 展现高点击少的页 / 排得很靠后的需求词(标有没有对应产品) / 本周新词。全是门槛过滤,不打分不猜。"""
    term_tokens = [_tokens(t) for t in (product_terms or []) if t]
    term_tokens = [t for t in term_tokens if t]

    def matches_product(query: str) -> bool:
        """词和某个品的名字/主关键词至少共用两个实词(品名只有一个实词就一个)。"""
        q = _tokens(query)
        return any(len(q & t) >= min(2, len(t)) for t in term_tokens)

    queries = current.get("queries") or {}
    prev_queries = previous.get("queries") or {}
    quick = sorted(((q, v) for q, v in queries.items() if v["impressions"] >= QUICK_WIN_MIN_IMPRESSIONS and QUICK_WIN_POSITION[0] <= v["position"] <= QUICK_WIN_POSITION[1]), key=lambda kv: -kv[1]["impressions"])[:TOP_N]
    low_ctr = sorted(((p, v) for p, v in (current.get("pages") or {}).items() if v["impressions"] >= LOW_CTR_MIN_IMPRESSIONS and v["ctr"] < LOW_CTR_MAX), key=lambda kv: -kv[1]["impressions"])[:TOP_N]
    far = sorted(((q, v) for q, v in queries.items() if v["impressions"] >= FAR_MIN_IMPRESSIONS and v["position"] > FAR_POSITION), key=lambda kv: -kv[1]["impressions"])[:TOP_N]
    new = sorted(((q, v) for q, v in queries.items() if q not in prev_queries and v["impressions"] >= NEW_QUERY_MIN_IMPRESSIONS), key=lambda kv: -kv[1]["impressions"])[:TOP_N]
    return {
        "quick_wins": [{"query": q, **v} for q, v in quick],
        "low_ctr_pages": [{"page": p, **v} for p, v in low_ctr],
        "far_queries": [{"query": q, **v, "has_product": matches_product(q)} for q, v in far],
        "new_queries": [{"query": q, **v} for q, v in new],
    }


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
    """给看板的「搜索」节:[start, end] 的合计 + 前一同长区间 + 缺口 + 数据到哪天。没接钥匙 → {"configured": False};接了但一天都没拉到 → rows 0。"""
    span = (end - start).days + 1
    have = pulled_days(db)
    if not have:
        try:
            credentials(db)
        except GscNotConfigured as exc:
            return {"configured": False, "reason": str(exc)}
    cur = aggregate(_rows_between(db, start, end))
    prev = aggregate(_rows_between(db, start - timedelta(days=span), start - timedelta(days=1)))
    last_day, pulled_at, last_error = last_pull(db)
    covered = sorted(d for d in have if start <= d <= end)
    top_queries = sorted(cur["queries"].items(), key=lambda kv: -kv[1]["clicks"])[:TOP_N]
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
        "top_queries": [{"query": q, **v} for q, v in top_queries],
        "gaps": gaps(cur, prev, product_terms=product_terms(db)),
    }
