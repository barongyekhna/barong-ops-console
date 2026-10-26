"""1688 档案的排队、节流、处理一单。

- 入口:老板在 C19 直接丢 1688 链接,或在办公室「电话」里贴 → ``enqueue``。同一个 offer 还在处理中就不重复排。
- worker 每轮最多处理一单(``process_next``):匿名打开 1688 页面会被 baxia 反爬盯上,
  两单之间至少隔 60 秒,一天最多 ``SQH_1688_DAILY_LIMIT`` 单(按洛杉矶日期)。
- 被拦了 → 整单标 blocked、不重试,发一张 ops_alert 卡(一天一张)。
- 处理完 → 草稿 + 「建 K 档案」卡;批卡才真的建进 K(见 executor)。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from . import cards, memory, office
from .constants import (
    DOSSIER_ACTIVE_STATUSES,
    DOSSIER_CARD_KIND,
    DOSSIER_IMAGE_BUDGET_USD,
    DOSSIER_MIN_GAP_SECONDS,
    LA,
    dossier_daily_limit,
)
from .models import SqhCard, SqhDossier

logger = logging.getLogger(__name__)
_X = SKIP_ORG_DATA_ISOLATION
MINUTES_PER_DOSSIER = 3
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"'，。]+", re.I)


class DossierError(ValueError):
    pass


def parse_offer_id(url: str) -> str | None:
    """优先用抓取模块的解析(同一套规则);它还没就绪时退回最小规则。"""
    try:
        from .sourcing_1688 import parse_offer_id as _parse
    except ImportError:  # pragma: no cover - 抓取模块和这里同一次发版
        _parse = None
    if _parse is not None:
        return _parse(url)
    parsed = urlparse((url or "").strip())
    if not (parsed.hostname or "").endswith("1688.com"):
        return None
    match = re.search(r"/offer/(\d{6,})", parsed.path)
    if match:
        return match.group(1)
    for key in ("offerId", "offerid", "id"):
        values = parse_qs(parsed.query).get(key)
        if values and values[0].isdigit() and len(values[0]) >= 6:
            return values[0]
    return None


def find_1688_links(text: str) -> list[tuple[str, str]]:
    """一段话里的 1688 商品链接 → [(url, offer_id)],同一个 offer 只算一次。"""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in _URL_IN_TEXT.findall(text or ""):
        offer = parse_offer_id(raw)
        if offer and offer not in seen:
            seen.add(offer)
            out.append((raw, offer))
    return out


def _queue_position(db: Session, dossier: SqhDossier) -> int:
    ahead = db.scalar(
        select(func.count()).select_from(SqhDossier).where(SqhDossier.status == "queued", SqhDossier.id < dossier.id),
        execution_options=_X,
    )
    return int(ahead or 0) + 1


def enqueue(db: Session, *, url: str, actor_user_id: str | None, channel: str) -> tuple[SqhDossier, bool, int]:
    """返回 (档案, 是不是新排的, 排第几)。不是 1688 商品链接 → DossierError。"""
    offer_id = parse_offer_id(url)
    if not offer_id:
        raise DossierError("这不是 1688 商品链接(要 detail.1688.com/offer/数字.html 那种)。")
    existing = db.scalar(
        select(SqhDossier)
        .where(SqhDossier.offer_id == offer_id, SqhDossier.status.in_(DOSSIER_ACTIVE_STATUSES))
        .order_by(SqhDossier.id.desc())
        .limit(1),
        execution_options=_X,
    )
    if existing is not None:
        return existing, False, _queue_position(db, existing) if existing.status == "queued" else 0
    dossier = SqhDossier(
        source_url=f"https://detail.1688.com/offer/{offer_id}.html",
        offer_id=offer_id,
        status="queued",
        requested_by_user_id=actor_user_id,
        channel=channel if channel in {"web", "c19"} else "web",
        capture={"submitted_url": url[:1000]},
        draft={},
    )
    db.add(dossier)
    db.flush()
    memory.log_activity(db, f"收到 1688 链接 {offer_id},排队整理成 K 档案。", kind="intake")
    return dossier, True, _queue_position(db, dossier)


REDO_REASON = "重新整理:规则更新后按新规则再做一遍"


def redo(db: Session, *, dossier_id: int, actor: Any) -> tuple[SqhDossier, bool, int]:
    """老板点「重新整理」:旧档案作废(待批的卡按驳回处理、写明原因),同一个链接重新排队。

    建进 K 的不能重做(要改去 K 里改);还在整理中的等它做完。
    """
    old = db.get(SqhDossier, dossier_id, execution_options=_X)
    if old is None:
        raise DossierError("没有这份档案。")
    if old.status in ("queued", "fetching", "reading"):
        raise DossierError("这份还在整理中,等它做完再说。")
    if old.status == "created":
        raise DossierError("这份已经建进 K 了,不能重做;要改去 K 里改。")
    if old.card_ref in building_refs(db, [old]):  # 卡批了、worker 正在建:这时驳卡驳不动,档案却会被标驳回、没人去建
        raise DossierError("这份已经批了,正在建进 K;建完要改去 K 里改。")
    if old.status == "ready" and old.card_ref:
        cards.decide_card(db, card_id=old.card_ref, decision="reject", actor=actor, channel="web", reason=REDO_REASON)
        db.refresh(old)
    if old.status == "ready":  # 没有卡的待批档案(理论上不会有)也不能挡着重排
        old.status = "rejected"
        db.add(old)
        db.flush()
    memory.log_activity(db, f"老板让档案 #{old.id}({old.offer_id})按新规则重新整理。", kind="intake")
    return enqueue(db, url=old.source_url, actor_user_id=str(getattr(actor, "id", "") or "") or None, channel="web")


def queue_reply(position: int, *, created: bool, status: str) -> str:
    if not created:
        labels = {"queued": "已经在排队了", "fetching": "正在打开页面", "reading": "正在读详情图", "ready": "已经整理好了,在办公室收件筐等你批"}
        return f"这个链接{labels.get(status, '在处理中')}。"
    eta = max(1, position) * MINUTES_PER_DOSSIER
    return f"收到，排在第 {position} 个，大概 {eta} 分钟后整理好，放在办公室收件筐里。"


# ---------------------------------------------------------------- 节流


def la_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    local = now.astimezone(LA)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def throttle_ok(*, now: datetime, last_fetch: datetime | None, fetched_today: int, limit: int, min_gap: int = DOSSIER_MIN_GAP_SECONDS) -> tuple[bool, str]:
    if fetched_today >= limit:
        return False, f"今天已经开了 {fetched_today} 个 1688 页面,到上限 {limit} 了,明天接着做。"
    if last_fetch is not None and (now - last_fetch).total_seconds() < min_gap:
        return False, "离上一个 1688 页面不到一分钟,歇一下,别被拦。"
    return True, ""


def _throttle_state(db: Session, now: datetime) -> tuple[datetime | None, int]:
    start, end = la_day_bounds(now)
    last = db.scalar(select(func.max(SqhDossier.fetched_at)), execution_options=_X)
    today = db.scalar(
        select(func.count()).select_from(SqhDossier).where(SqhDossier.fetched_at >= start, SqhDossier.fetched_at < end),
        execution_options=_X,
    )
    return last, int(today or 0)


# ---------------------------------------------------------------- 处理一单


FetchFn = Callable[[str], Any]
ReadFn = Callable[[Session, dict[str, Any]], dict[str, Any]]
BuildFn = Callable[[Session, dict[str, Any], dict[str, Any]], dict[str, Any]]
SpentFn = Callable[[datetime | None], "float | None"]


def _ledger_spent(since: datetime | None) -> float | None:
    from .constants import USAGE_LABEL
    from .sourcing_1688 import ledger_meter

    return ledger_meter(USAGE_LABEL, since)() if since else None


def reading_text(reading: dict[str, Any]) -> str:
    """审批卡上的一句话:详情图读得怎么样。"""
    if reading.get("detail_error"):
        return "详情图没取到(规格只来自页面)"
    images = int(reading.get("images") or 0)
    if not images:
        return "卖家的详情里没有图片"
    text = f"详情图 {images} 张,读了 {int(reading.get('segments_seen') or 0)} 段"
    if reading.get("images_failed"):
        text += f",{int(reading['images_failed'])} 张打不开"
    if reading.get("stopped_reason") == "budget":
        text += "(到单份预算上限停了)"
    elif reading.get("stopped_reason") == "degraded":
        text += "(Claude 额度用完停了)"
    return text


def _defaults() -> tuple[FetchFn, ReadFn, BuildFn]:
    from . import dossier as dossier_mod
    from . import sourcing_1688

    def fetch(url: str) -> dict[str, Any]:
        capture = sourcing_1688.fetch_offer(url)
        return capture.to_dict() if hasattr(capture, "to_dict") else dict(capture)

    def read(db: Session, capture: dict[str, Any]) -> dict[str, Any]:
        return sourcing_1688.read_detail_images(db, capture, budget_usd=DOSSIER_IMAGE_BUDGET_USD)

    return fetch, read, dossier_mod.build_draft


def _set_activity(db: Session, activity: str, task: str) -> None:
    state = office.get_state(db)
    state.activity = activity
    state.task = task[:300]
    state.progress = None
    db.add(state)


def _alert_blocked(db: Session, *, dossier: SqhDossier, reason: str, now: datetime) -> None:
    day = now.astimezone(LA).date().isoformat()
    cards.create_card(
        db,
        dedupe_key=f"{day}:1688_blocked",
        kind="ops_alert",
        title="1688 把我拦住了",
        conclusion="老板,我打开 1688 页面时被拦了(反爬/要登录)。今天先不再碰 1688,明天再试;急的话你帮我开一下那个页面。",
        why=reason[:500],
        if_not="这一单的 K 档案今天出不来。",
        reversible=True,
        confidence="high",
        evidence={"dossier_id": dossier.id, "offer_id": dossier.offer_id},
    )


def process_next(
    db: Session,
    *,
    now: datetime | None = None,
    fetch: FetchFn | None = None,
    read: ReadFn | None = None,
    build: BuildFn | None = None,
    spent: SpentFn | None = None,
) -> SqhDossier | None:
    """处理一单排队的档案。没有可做的(或被节流)返回 None。

    ``spent(开始时间)`` 返回这单的台账实数花费;注入假的抓取/读图时不传,就用读图那边报的数。
    """
    now = now or datetime.now(UTC)
    dossier = db.scalar(
        select(SqhDossier).where(SqhDossier.status == "queued").order_by(SqhDossier.id).limit(1),
        execution_options=_X,
    )
    if dossier is None:
        return None
    last, today = _throttle_state(db, now)
    ok, why = throttle_ok(now=now, last_fetch=last, fetched_today=today, limit=dossier_daily_limit())
    if not ok:
        return None
    if fetch is None or read is None or build is None:
        d_fetch, d_read, d_build = _defaults()
        fetch, read, build = fetch or d_fetch, read or d_read, build or d_build
        spent = spent or _ledger_spent

    dossier.status = "fetching"
    dossier.fetched_at = now
    # 花费从真正开始抓页面这一刻算起:同一轮里先做的早晨计划、回老板的话(也调 Claude)不能算进这单。
    cost_since = datetime.now(UTC)
    _set_activity(db, "thinking", f"在读 1688:{dossier.offer_id}")
    memory.log_activity(db, f"打开 1688 页面 {dossier.offer_id}。", kind="fetch")
    db.commit()  # 出网前放掉事务(8 秒 idle-in-transaction 上限)

    try:
        capture = fetch(dossier.source_url)
        if capture.get("blocked"):
            dossier.status = "blocked"
            dossier.capture = {**(dossier.capture or {}), **capture}
            dossier.error = str(capture.get("block_reason") or "被 1688 拦了")[:500]
            _alert_blocked(db, dossier=dossier, reason=dossier.error, now=now)
            memory.log_activity(db, f"1688 {dossier.offer_id} 被拦了:{dossier.error[:80]}", kind="error")
            _set_activity(db, "working", "1688 拦了我,今天先不碰")
            db.commit()
            return dossier

        dossier.status = "reading"
        dossier.capture = {**(dossier.capture or {}), **capture}
        _set_activity(db, "thinking", f"在读 1688 详情图:{dossier.offer_id}")
        memory.log_activity(db, f"{dossier.offer_id}:页面拿到了,{len(capture.get('skus') or [])} 个 SKU,开始读详情图。", kind="fetch")
        db.commit()

        image_read = read(db, capture)
        draft = build(db, capture, image_read)
        dossier = db.get(SqhDossier, dossier.id, execution_options=_X)
        dossier.draft = draft
        dossier.flagged_count = int(draft.get("flagged_count") or 0)
        # 花费记台账实数(读图 + 英文名,整单从开始到现在);台账读不到才用读图那边的数。
        real_cost = spent(cost_since) if spent else None
        dossier.cost_usd = round(float(real_cost if real_cost is not None else image_read.get("cost_usd") or 0), 4)
        dossier.status = "ready"
        title = (draft.get("fields", {}).get("name_zh", {}) or {}).get("value") or capture.get("title_zh") or dossier.offer_id
        card, _ = cards.create_card(
            db,
            dedupe_key=f"dossier:{dossier.offer_id}:{dossier.id}",
            kind=DOSSIER_CARD_KIND,
            title=f"建 K 档案:{str(title)[:30]}",
            conclusion=(
                f"{draft.get('summary_zh', '')} 批了我就建进 K(先建成单品草稿,不上架);"
                "售价得老板定,标红的几项也请过目。"
            ),
            why=f"1688 offer {dossier.offer_id},{reading_text(draft.get('image_read') or {})},花了 ${dossier.cost_usd}。",
            if_not="不批就停在草稿,不会进 K。",
            reversible=True,
            confidence="medium" if dossier.flagged_count else "high",
            evidence={"dossier_id": dossier.id, "offer_id": dossier.offer_id, "flagged_count": dossier.flagged_count},
        )
        dossier.card_ref = card.ref
        db.add(dossier)
        memory.log_activity(db, f"{dossier.offer_id} 的 K 档案草稿好了,标红 {dossier.flagged_count} 项,卡 #{card.ref} 等老板批。", kind="dossier")
        _set_activity(db, "working", f"档案 #{dossier.id} 好了,等老板批")
        db.commit()
        return dossier
    except Exception as exc:  # noqa: BLE001 —— 一单失败不拖垮 worker,但要落库、写流水
        db.rollback()
        logger.exception("dossier %s failed", dossier.id)
        failed = db.get(SqhDossier, dossier.id, execution_options=_X)
        failed.status = "failed"
        failed.error = f"{exc.__class__.__name__}: {str(exc)[:400]}"
        db.add(failed)
        memory.log_activity(db, f"{failed.offer_id} 没整理成:{failed.error[:100]}", kind="error")
        _set_activity(db, "working", "上一单 1688 没整理成,看流水")
        db.commit()
        return failed


# ---------------------------------------------------------------- 展示


def building_refs(db: Session, rows: list[SqhDossier]) -> set[str]:
    """这些档案里哪些卡已经批了、worker 还在建(档案还是 ready):界面显示「已批,建档中」。"""
    refs = [d.card_ref for d in rows if d.status == "ready" and d.card_ref]
    if not refs:
        return set()
    return set(db.scalars(select(SqhCard.ref).where(SqhCard.ref.in_(refs), SqhCard.status == "approved"), execution_options=_X))


def summary_payload(d: SqhDossier, *, building: bool = False) -> dict[str, Any]:
    draft = d.draft or {}
    name = ((draft.get("fields") or {}).get("name_zh") or {}).get("value") or (d.capture or {}).get("title_zh")
    return {
        "id": d.id,
        "offer_id": d.offer_id,
        "source_url": d.source_url,
        "status": d.status,
        "building": building,
        "title": name,
        "flagged_count": d.flagged_count,
        "cost_usd": float(d.cost_usd or 0),
        "card_ref": d.card_ref,
        "k_product_id": d.k_product_id,
        "error": d.error,
        "channel": d.channel,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def detail_payload(d: SqhDossier, *, building: bool = False) -> dict[str, Any]:
    return {**summary_payload(d, building=building), "capture": d.capture or {}, "draft": d.draft or {}}
