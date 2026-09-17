"""A4 竞品名单自动派生(殷长辰):品牌分析搜索词报表 → 我们核心词的点击前三 → 竞品名单。人不用填 ASIN。

推导链(全部从数据算,家规「能推就别问」):
1. 核心词 = 这个站点里我们**真出过单**的词:SQP 里自家 ASIN 购买 ≥ 2,或广告搜索词 60 天订单 ≥ 2;
   按词归产品线(词里得有这条线的品类词,「camping essentials」这种大词不算),每条线按搜索量取前 6。
2. 每周拉一次 GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT(全站报表,几百万行,边下边解压边过滤,只留核心词那几行)
   → amz_ba_top_clicks。
3. 对手 = 最近 4 个导入周里,这些词点击前三的 ASIN:商品名也得是同一条线的东西(「pool heater」点出来的泳池加热器不算)、
   不是自家的;按点击份额累加排序,每条线留前 5 → amz_competitors(source=brand_analytics)。
   掉出前 5 的系统来源对手停盯(不删,快照留着);人加的、事实表里的不动。

报表生成要几分钟到几十分钟:第一次请求后作业返回 deferred_seconds,worker 过一会再来看,等的时候不写心跳。
站点级报表:同一个站点同一周只拉一次,别的店跑到直接用。
"""

from __future__ import annotations

import codecs
import json
import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .models import AmzAdSearchTerm, AmzBaTopClick, AmzCompetitor, AmzProduct, AmzReportRun, AmzSalesDaily, AmzSqp, AmzStore

_LOGGER = logging.getLogger("amz.ba_competitors")

REPORT_BA_SEARCH_TERMS = "GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT"
SOURCE_BA = "brand_analytics"
CORE_MIN_ORDERS = 2
CORE_TERMS_PER_LINE = 6
COMPETITORS_PER_LINE = 5
LOOKBACK_WEEKS = 4
SIGNAL_LOOKBACK_DAYS = 60
REPORT_READY_LAG_DAYS = 4  # 周报在周六结束后几天才出
DEFER_SECONDS = 900
GIVE_UP_HOURS = 8

# 词 → 产品线:搜索词里要有品类词(英 / 德 / 西)。和 rules.product_line_of 分开:那个是认 SKU 的,这个是认买家说的话。
TERM_LINE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("heater", re.compile(r"immersion|bucket heater|water heater|tauchsieder|heizstab|wasserkocher stab|calentador de agua", re.I)),
    ("flash", re.compile(r"flashlight|torch|taschenlampe|linterna", re.I)),
    ("nail", re.compile(r"nail (grinder|trimmer|clipper)|krallen|nagelschleifer|cortau[ñn]as", re.I)),
    ("pump", re.compile(r"shower|ducha|dusche", re.I)),
)
# 商品名 → 产品线:点出来的东西得是同类(比词的门更严一点:热水棒必须是浸入式)。
ITEM_LINE_PATTERNS: dict[str, re.Pattern[str]] = {
    "heater": re.compile(r"immersion|tauchsieder|heizstab|bucket heater", re.I),
    "flash": re.compile(r"flashlight|torch|taschenlampe|linterna", re.I),
    "nail": re.compile(r"nail|krallen|nagel", re.I),
    "pump": re.compile(r"shower|ducha|dusche", re.I),
}


def line_of_term(term: str) -> str | None:
    for line, pattern in TERM_LINE_PATTERNS:
        if pattern.search(term or ""):
            return line
    return None


def item_matches_line(item_name: str | None, line: str) -> bool:
    pattern = ITEM_LINE_PATTERNS.get(line)
    return bool(pattern and pattern.search(item_name or ""))


def target_week(today: date) -> tuple[date, date]:
    """最近一个「结束已满 4 天」的周日—周六整周。"""
    ready = today - timedelta(days=REPORT_READY_LAG_DAYS)
    end = ready - timedelta(days=(ready.weekday() - 5) % 7)
    return end - timedelta(days=6), end


# ---------------------------------------------------------------- 核心词


def core_terms(db: Session, marketplace: str, *, today: date) -> dict[str, list[str]]:
    """{产品线: [核心词…]}(小写)。"""
    stores = [s.store_code for s in db.scalars(select(AmzStore).where(AmzStore.country == marketplace))]
    if not stores:
        return {}
    since = today - timedelta(days=SIGNAL_LOOKBACK_DAYS)
    volume: dict[str, int] = defaultdict(int)
    orders: dict[str, int] = defaultdict(int)
    sqp = db.execute(
        select(func.lower(AmzSqp.search_query), func.sum(AmzSqp.purchases_asin), func.max(AmzSqp.query_volume))
        .where(AmzSqp.store_code.in_(stores), AmzSqp.period_start >= since)
        .group_by(func.lower(AmzSqp.search_query))
    ).all()
    for term, bought, vol in sqp:
        orders[term] += int(bought or 0)
        volume[term] = max(volume[term], int(vol or 0))
    ads = db.execute(
        select(func.lower(AmzAdSearchTerm.search_term), func.sum(AmzAdSearchTerm.orders_7d), func.sum(AmzAdSearchTerm.clicks))
        .where(AmzAdSearchTerm.store_code.in_(stores), AmzAdSearchTerm.report_date >= since)
        .group_by(func.lower(AmzAdSearchTerm.search_term))
    ).all()
    for term, bought, clicks in ads:
        if re.fullmatch(r"b0[a-z0-9]{8}", term or ""):
            continue  # ASIN 定向的「搜索词」不是买家说的话
        orders[term] = max(orders[term], int(bought or 0))
        volume[term] = max(volume[term], int(clicks or 0))
    by_line: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for term, bought in orders.items():
        line = line_of_term(term)
        if line and bought >= CORE_MIN_ORDERS:
            by_line[line].append((volume[term], term))
    return {line: [t for _v, t in sorted(items, key=lambda x: (-x[0], x[1]))[:CORE_TERMS_PER_LINE]] for line, items in by_line.items()}


# ---------------------------------------------------------------- 报表流式解析


def iter_report_rows(chunks: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    """{"reportSpecification": …, "dataByDepartmentAndSearchTerm": [{…}, …]} → 一行一行吐。每行是扁平对象。"""
    decoder = json.JSONDecoder()
    utf8 = codecs.getincrementaldecoder("utf-8")()
    buf, pos, started = "", 0, False
    key = '"dataByDepartmentAndSearchTerm"'
    for chunk in chunks:
        buf = buf[pos:] + utf8.decode(chunk)
        pos = 0
        if not started:
            at = buf.find(key)
            if at < 0:
                buf = buf[-len(key) :]
                continue
            bracket = buf.find("[", at)
            if bracket < 0:
                pos = at
                continue
            pos, started = bracket + 1, True
        while True:
            while pos < len(buf) and buf[pos] in " \t\r\n,":
                pos += 1
            if pos >= len(buf):
                break
            if buf[pos] == "]":
                return
            try:
                obj, end = decoder.raw_decode(buf, pos)
            except json.JSONDecodeError:
                break  # 半个对象,等下一块
            pos = end
            if isinstance(obj, dict):
                yield obj
    if started and buf[pos:].strip():
        raise ValueError("brand analytics report ended mid-object")


def filter_core_rows(rows: Iterable[dict[str, Any]], core: dict[str, list[str]]) -> tuple[list[dict[str, Any]], int]:
    term_line = {t: line for line, terms in core.items() for t in terms}
    kept: list[dict[str, Any]] = []
    seen = 0
    for row in rows:
        seen += 1
        term = str(row.get("searchTerm") or "").strip().lower()
        line = term_line.get(term)
        if line is None:
            continue
        asin = str(row.get("clickedAsin") or "").strip().upper()
        rank = row.get("clickShareRank")
        if len(asin) != 10 or not isinstance(rank, int):
            continue
        kept.append(
            {
                "search_term": term,
                "product_line": line,
                "search_frequency_rank": row.get("searchFrequencyRank") if isinstance(row.get("searchFrequencyRank"), int) else None,
                "click_rank": rank,
                "asin": asin,
                "item_name": (str(row.get("clickedItemName") or "")[:512]) or None,
                "click_share": _share(row.get("clickShare")),
                "conversion_share": _share(row.get("conversionShare")),
            }
        )
    return kept, seen


def _share(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)).quantize(Decimal("0.0001")) if value is not None else None
    except (ArithmeticError, ValueError):
        return None


def store_week(db: Session, *, marketplace: str, week_start: date, rows: list[dict[str, Any]]) -> int:
    db.execute(delete(AmzBaTopClick).where(AmzBaTopClick.marketplace == marketplace, AmzBaTopClick.week_start == week_start))
    if rows:
        db.execute(pg_insert(AmzBaTopClick).values([{**r, "marketplace": marketplace, "week_start": week_start} for r in rows]).on_conflict_do_nothing(constraint="uq_amz_ba_top_clicks_week_term_rank"))
    return len(rows)


# ---------------------------------------------------------------- 名单


def our_asins(db: Session, marketplace: str) -> set[str]:
    stores = [s.store_code for s in db.scalars(select(AmzStore).where(AmzStore.country == marketplace))]
    out: set[str] = set(db.scalars(select(AmzCompetitor.asin).where(AmzCompetitor.marketplace == marketplace, AmzCompetitor.whose == "ours")))
    for child, parent in db.execute(select(AmzSalesDaily.child_asin, AmzSalesDaily.parent_asin).where(AmzSalesDaily.store_code.in_(stores)).distinct()).all():
        out.update(a for a in (child, parent) if a)
    for asin, parent in db.execute(select(AmzProduct.asin, AmzProduct.parent_asin).where(AmzProduct.store_code.in_(stores))).all():
        out.update(a for a in (asin, parent) if a)
    return {a.upper() for a in out}


def pick_competitors(rows: Iterable[Any], ours: set[str]) -> dict[str, list[tuple[str, str | None, float]]]:
    """{产品线: [(asin, 商品名, 累计点击份额)…]} 每条线前 5。"""
    score: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    names: dict[str, str | None] = {}
    for r in rows:
        if r.asin in ours or not item_matches_line(r.item_name, r.product_line):
            continue
        score[r.product_line][r.asin] += float(r.click_share or 0)
        names.setdefault(r.asin, r.item_name)
    return {line: [(a, names.get(a), round(s, 4)) for a, s in sorted(by.items(), key=lambda x: (-x[1], x[0]))[:COMPETITORS_PER_LINE]] for line, by in score.items()}


def recent_weeks(db: Session, marketplace: str) -> list[date]:
    return list(db.scalars(select(AmzBaTopClick.week_start).where(AmzBaTopClick.marketplace == marketplace).distinct().order_by(AmzBaTopClick.week_start.desc()).limit(LOOKBACK_WEEKS)))


def apply_watchlist(db: Session, marketplace: str) -> dict[str, Any]:
    weeks = recent_weeks(db, marketplace)
    if not weeks:
        return {"weeks": 0, "added": 0, "reactivated": 0, "retired": 0}
    rows = list(db.scalars(select(AmzBaTopClick).where(AmzBaTopClick.marketplace == marketplace, AmzBaTopClick.week_start.in_(weeks))))
    picks = pick_competitors(rows, our_asins(db, marketplace))
    picked: set[str] = set()
    added = reactivated = retired = 0
    for line, items in picks.items():
        for asin, name, _score in items:
            picked.add(asin)
            existing = db.scalar(select(AmzCompetitor).where(AmzCompetitor.marketplace == marketplace, AmzCompetitor.asin == asin))
            if existing is None:
                db.add(AmzCompetitor(marketplace=marketplace, asin=asin, product_line=line, whose="competitor", source=SOURCE_BA, label=(name or "")[:60] or None, active=True))
                added += 1
            elif existing.source == SOURCE_BA and not existing.active:
                existing.active = True
                reactivated += 1
    for comp in db.scalars(select(AmzCompetitor).where(AmzCompetitor.marketplace == marketplace, AmzCompetitor.source == SOURCE_BA, AmzCompetitor.active.is_(True))):
        if comp.asin not in picked:
            comp.active = False
            retired += 1
    db.flush()
    return {"weeks": len(weeks), "added": added, "reactivated": reactivated, "retired": retired, "per_line": {line: [a for a, _n, _s in items] for line, items in picks.items()}}


def terms_by_asin(db: Session, marketplace: str) -> dict[str, list[dict[str, Any]]]:
    """竞品页用:最新一周里这个 ASIN 在哪些核心词上点击排第几。"""
    weeks = recent_weeks(db, marketplace)
    if not weeks:
        return {}
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in db.scalars(select(AmzBaTopClick).where(AmzBaTopClick.marketplace == marketplace, AmzBaTopClick.week_start == weeks[0]).order_by(AmzBaTopClick.search_term, AmzBaTopClick.click_rank)):
        out[r.asin].append({"term": r.search_term, "rank": r.click_rank, "click_share": float(r.click_share) if r.click_share is not None else None, "week_start": r.week_start.isoformat()})
    return dict(out)


# ---------------------------------------------------------------- 作业


def _runs(db: Session, marketplace: str, week_start: date) -> list[AmzReportRun]:
    runs = db.scalars(select(AmzReportRun).where(AmzReportRun.report_type == REPORT_BA_SEARCH_TERMS).order_by(AmzReportRun.requested_at.desc()))
    return [r for r in runs if (r.params_json or {}).get("marketplace") == marketplace and (r.params_json or {}).get("week_start") == week_start.isoformat()]


def run(db: Session, client: Any, store: AmzStore, *, today: date | None = None, now: datetime | None = None) -> dict[str, Any]:
    """一次调用推进一步:请求报表 → (没好就 deferred)→ 下载过滤落库 → 派生名单。自己 commit。"""
    today = today or datetime.now(UTC).date()
    now = now or datetime.now(UTC)
    marketplace = store.country
    week_start, week_end = target_week(today)
    runs = _runs(db, marketplace, week_start)
    if any(r.status == "done" for r in runs):
        out = apply_watchlist(db, marketplace)
        db.commit()
        return {"marketplace": marketplace, "week_start": week_start.isoformat(), "skipped": "already imported", "watchlist": out}
    pending = next((r for r in runs if r.status == "requested" and r.report_id), None)
    failed_recently = next((r for r in runs if r.status == "failed" and r.finished_at and now - r.finished_at < timedelta(hours=24)), None)
    if pending is None and failed_recently is not None:
        raise RuntimeError(f"brand analytics search terms {week_start} failed <24h ago: {failed_recently.error}")
    core = core_terms(db, marketplace, today=today)
    db.commit()
    if not core:
        return {"marketplace": marketplace, "week_start": week_start.isoformat(), "skipped": "no core terms yet (need SQP or ad orders)"}
    if pending is None:
        report_id = client.create_report(REPORT_BA_SEARCH_TERMS, start=week_start, end=week_end, options={"reportPeriod": "WEEK"})
        db.add(AmzReportRun(store_code=store.store_code, report_type=REPORT_BA_SEARCH_TERMS, report_id=report_id, params_json={"marketplace": marketplace, "week_start": week_start.isoformat(), "week_end": week_end.isoformat()}, status="requested"))
        db.commit()
        return {"marketplace": marketplace, "week_start": week_start.isoformat(), "requested": report_id, "deferred_seconds": DEFER_SECONDS}
    status = client.get_report(pending.report_id)
    state = str(status.get("processingStatus") or "")
    if state in ("IN_QUEUE", "IN_PROGRESS", ""):
        if now - pending.requested_at > timedelta(hours=GIVE_UP_HOURS):
            _close(db, pending, "failed", error=f"still {state} after {GIVE_UP_HOURS}h")
            raise RuntimeError(f"brand analytics report {pending.report_id} still {state} after {GIVE_UP_HOURS}h")
        return {"marketplace": marketplace, "week_start": week_start.isoformat(), "waiting": state, "deferred_seconds": DEFER_SECONDS}
    document_id = str(status.get("reportDocumentId") or "")
    if state != "DONE" or not document_id:
        details = ""
        if document_id:
            try:
                details = str(json.loads(b"".join(client.stream_document(client.get_document(document_id)))).get("errorDetails") or "")
            except (ValueError, TypeError):
                details = ""
        _close(db, pending, "failed", error=f"{state}: {details or '(no details)'}")
        raise RuntimeError(f"brand analytics report {state}: {details or '(no details)'}")
    document = client.get_document(document_id)
    kept, seen = filter_core_rows(iter_report_rows(client.stream_document(document)), core)
    written = store_week(db, marketplace=marketplace, week_start=week_start, rows=kept)
    pending.status, pending.rows, pending.finished_at = "done", written, datetime.now(UTC)
    pending.params_json = {**(pending.params_json or {}), "rows_scanned": seen, "core_terms": core}
    db.add(pending)
    out = apply_watchlist(db, marketplace)
    db.commit()
    return {"marketplace": marketplace, "week_start": week_start.isoformat(), "rows_scanned": seen, "rows_kept": written, "core_terms": core, "watchlist": out}


def _close(db: Session, run_row: AmzReportRun, status: str, *, error: str | None = None) -> None:
    run_row.status = status
    run_row.error = (error or "")[:2000] or None
    run_row.finished_at = datetime.now(UTC)
    db.add(run_row)
    db.commit()


__all__ = ["REPORT_BA_SEARCH_TERMS", "SOURCE_BA", "apply_watchlist", "core_terms", "filter_core_rows", "item_matches_line", "iter_report_rows", "line_of_term", "our_asins", "pick_competitors", "run", "store_week", "target_week", "terms_by_asin"]
