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
from . import browser, cards, compliance_gate, memory, office
from .constants import (
    DOSSIER_ACTIVE_STATUSES,
    DOSSIER_CARD_KIND,
    DOSSIER_IMAGE_BUDGET_USD,
    DOSSIER_MIN_GAP_SECONDS,
    LA,
    NEEDS_HUMAN,
    dossier_daily_limit,
    retry_after_block,
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
    dropped = db.scalar(
        select(SqhDossier)
        .where(SqhDossier.offer_id == offer_id, SqhDossier.status == compliance_gate.DOSSIER_DROPPED)
        .order_by(SqhDossier.id.desc())
        .limit(1),
        execution_options=_X,
    )
    if dropped is not None and dropped.card_ref:
        card_status = db.scalar(select(SqhCard.status).where(SqhCard.ref == dropped.card_ref), execution_options=_X)
        if card_status == "pending":
            gate = compliance_gate.record(dropped.draft) or {}
            raise DossierError(
                f"这件货合规门不做({compliance_gate.headline(gate)}),卡 #{dropped.card_ref} 还在等你;"
                "判错了就在那张卡上点「驳」放行,我接着建档。"
            )
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
    if old.status in ("queued", "fetching", "reading", "needs_human"):
        raise DossierError("这份还在整理中,等它做完再说。")
    if old.status == "created":
        raise DossierError("这份已经建进 K 了,不能重做;要改去 K 里改。")
    if old.status in (compliance_gate.DOSSIER_DROPPED, compliance_gate.DOSSIER_GATE_ASK):
        raise DossierError(f"这份被合规门挡着,去卡 #{old.card_ref} 处理(驳 = 放行)。")
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
        labels = {"queued": "已经在排队了", "fetching": "正在打开页面", "reading": "正在读详情图", "ready": "已经整理好了,在办公室收件筐等你批", "needs_human": "被 1688 要验证了,页面在办公室的浏览器里等你过一下", "gate_ask": "过合规门时拿不准,收件筐里有张合规卡等你定"}
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


def _blocked_today(db: Session, now: datetime) -> bool:
    """今天(洛杉矶)已经被拦过一次:「今天先不碰」——10-28 之前只是嘴上说,现在真不碰(SQH_1688_RETRY_AFTER_BLOCK=1 放开)。"""
    if retry_after_block():
        return False
    start, end = la_day_bounds(now)
    n = db.scalar(
        select(func.count()).select_from(SqhDossier).where(SqhDossier.status == "blocked", SqhDossier.fetched_at >= start, SqhDossier.fetched_at < end),
        execution_options=_X,
    )
    return int(n or 0) > 0


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
GateFn = Callable[[Session, str], dict[str, Any]]


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


def _alert_blocked(db: Session, *, dossier: SqhDossier, reason: str, now: datetime, browser: bool = False) -> None:
    day = now.astimezone(LA).date().isoformat()
    if browser:
        title = "1688 要验证,页面我留着了"
        conclusion = "老板,我在办公室开着那个页面:你点「打开浏览器」帮我过一下滑块或扫码登录,过了我自己接着做。"
        if_not = "这一单先停着;两小时没人来我就按被拦处理,今天不再碰 1688。"
    else:
        title = "1688 把我拦住了"
        conclusion = "老板,我打开 1688 页面时被拦了(反爬/要登录)。今天先不再碰 1688,明天再试;急的话你帮我开一下那个页面。"
        if_not = "这一单的 K 档案今天出不来。"
    cards.create_card(
        db,
        dedupe_key=f"{day}:1688_blocked",
        kind="ops_alert",
        title=title,
        conclusion=conclusion,
        why=reason[:500],
        if_not=if_not,
        reversible=True,
        confidence="high",
        evidence={"dossier_id": dossier.id, "offer_id": dossier.offer_id, "browser": browser},
    )


def process_next(
    db: Session,
    *,
    now: datetime | None = None,
    fetch: FetchFn | None = None,
    read: ReadFn | None = None,
    build: BuildFn | None = None,
    spent: SpentFn | None = None,
    gate: GateFn | None = None,
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
    if browser.holding():  # 页面正等老板过验证 / 老板在登录 / 在问卖家:这时候不开新页面
        return None
    if _blocked_today(db, now):
        return None
    last, today = _throttle_state(db, now)
    ok, why = throttle_ok(now=now, last_fetch=last, fetched_today=today, limit=dossier_daily_limit())
    if not ok:
        return None
    if fetch is None or read is None or build is None:
        d_fetch, d_read, d_build = _defaults()
        fetch, read, build = fetch or d_fetch, read or d_read, build or d_build
        spent = spent or _ledger_spent
        gate = gate or compliance_gate.judge  # 真跑才过门;注入假抓取的测试不传 gate 就不过门

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
            reason = str(capture.get("block_reason") or "被 1688 拦了")
            if reason.startswith(NEEDS_HUMAN):
                # 页面在她的浏览器里留着(browser.py),等老板过验证;过了 resume_human 接着做
                dossier.status = "needs_human"
                dossier.capture = {**(dossier.capture or {}), **capture}
                dossier.error = reason[len(NEEDS_HUMAN):][:500]
                _alert_blocked(db, dossier=dossier, reason=dossier.error, now=now, browser=True)
                memory.log_activity(db, f"1688 {dossier.offer_id} 要验证({dossier.error[:60]}),页面我留着了,等老板过一下。", kind="error")
                _set_activity(db, "raised", "1688 要验证,等老板帮我过一下")
                db.commit()
                if browser.enabled():
                    try:
                        browser.get().note_dossier(dossier.id)
                    except Exception:  # noqa: BLE001 —— 记不上档案号不影响等人
                        logger.exception("browser note_dossier failed")
                return dossier
            dossier.status = "blocked"
            dossier.capture = {**(dossier.capture or {}), **capture}
            dossier.error = reason[:500]
            _alert_blocked(db, dossier=dossier, reason=dossier.error, now=now)
            memory.log_activity(db, f"1688 {dossier.offer_id} 被拦了:{dossier.error[:80]}", kind="error")
            _set_activity(db, "working", "1688 拦了我,今天先不碰")
            db.commit()
            return dossier
        return _complete(db, dossier, capture, read=read, build=build, spent=spent, cost_since=cost_since, gate=gate)
    except Exception as exc:  # noqa: BLE001 —— 一单失败不拖垮 worker,但要落库、写流水
        return _fail(db, dossier.id, exc)


def _complete(
    db: Session,
    dossier: SqhDossier,
    capture: dict[str, Any],
    *,
    read: ReadFn,
    build: BuildFn,
    spent: SpentFn | None,
    cost_since: datetime,
    gate: GateFn | None = None,
) -> SqhDossier:
    """页面拿到了之后的半段:读详情图 → 建草稿 → 过合规门 → ready + 建档卡(或 dropped / gate_ask + 合规卡)。被拦后老板过了验证也走这里。

    ``gate`` 不传 = 这里不过门(注入假抓取的测试);真跑时 process_next / resume_human 会给。没判成的(额度、接口)照常发建档卡,
    建进 K 以后流水线第一步会补判(pipeline 的 compliance_gate 步)。
    """
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
    db.add(dossier)
    db.commit()  # 出网前放掉事务(合规门要调模型)

    if gate is not None:
        _set_activity(db, "thinking", f"在过合规门:{dossier.offer_id}")
        db.commit()
        result = gate(db, compliance_gate.dossier_facts(draft, dossier.capture))
        dossier = db.get(SqhDossier, dossier.id, execution_options=_X)
        draft = {**(dossier.draft if isinstance(dossier.draft, dict) else draft), "compliance_gate": result}
        dossier.draft = draft
    # 花费记台账实数(读图 + 英文名 + 合规门,整单从开始到现在);台账读不到才用读图那边的数。
    real_cost = spent(cost_since) if spent else None
    dossier.cost_usd = round(float(real_cost if real_cost is not None else image_read.get("cost_usd") or 0), 4)
    title = _title(dossier)
    if compliance_gate.state(draft) in compliance_gate.WAITING:
        result = compliance_gate.record(draft) or {}
        dossier.status = compliance_gate.DOSSIER_DROPPED if result.get("status") == "drop" else compliance_gate.DOSSIER_GATE_ASK
        card = compliance_gate.raise_card(db, dossier=dossier, gate=result, stage="dossier", title_hint=title)
        dossier.card_ref = card.ref
        db.add(dossier)
        verb = "不做" if result.get("status") == "drop" else "要老板定"
        memory.log_activity(db, f"{dossier.offer_id}:合规门{verb}({compliance_gate.headline(result)}),卡 #{card.ref}。", kind="dossier")
        _set_activity(db, "working", f"档案 #{dossier.id} 合规门{verb}")
        db.commit()
        return dossier
    issue_dossier_card(db, dossier)
    _set_activity(db, "working", f"档案 #{dossier.id} 好了,等老板批")
    db.commit()
    return dossier


def _title(dossier: SqhDossier) -> str:
    draft = dossier.draft if isinstance(dossier.draft, dict) else {}
    capture = dossier.capture if isinstance(dossier.capture, dict) else {}
    return str((draft.get("fields", {}).get("name_zh", {}) or {}).get("value") or capture.get("title_zh") or dossier.offer_id)


def issue_dossier_card(db: Session, dossier: SqhDossier) -> SqhCard:
    """档案 → ready + 「建 K 档案」卡。合规门放行(或老板在合规卡上放行)之后走这里。"""
    draft = dossier.draft if isinstance(dossier.draft, dict) else {}
    gate = compliance_gate.record(draft)
    gate_note = ""
    if gate is not None and gate.get("status") == "error":
        gate_note = f" 合规门这次没判成({str(gate.get('error') or '')[:60]}),建进 K 之后我第一步先补判。"
    elif compliance_gate.state(draft) == "override":
        gate_note = " 合规门本来不让做,老板放行了。"
    dossier.status = "ready"
    card, _ = cards.create_card(
        db,
        dedupe_key=f"dossier:{dossier.offer_id}:{dossier.id}",
        kind=DOSSIER_CARD_KIND,
        title=f"建 K 档案:{_title(dossier)[:30]}",
        conclusion=(
            f"{draft.get('summary_zh', '')} 批了我就建进 K(先建成单品草稿,不上架);"
            "售价得老板定,标红的几项也请过目。" + gate_note
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
    return card


def _fail(db: Session, dossier_id: int, exc: BaseException) -> SqhDossier:
    db.rollback()
    logger.exception("dossier %s failed", dossier_id)
    failed = db.get(SqhDossier, dossier_id, execution_options=_X)
    failed.status = "failed"
    failed.error = f"{exc.__class__.__name__}: {str(exc)[:400]}"
    db.add(failed)
    memory.log_activity(db, f"{failed.offer_id} 没整理成:{failed.error[:100]}", kind="error")
    _set_activity(db, "working", "上一单 1688 没整理成,看流水")
    db.commit()
    return failed


# ---------------------------------------------------------------- 等老板过验证(10-28)


def resume_human(
    db: Session,
    *,
    now: datetime | None = None,
    event: dict[str, Any] | None = None,
    read: ReadFn | None = None,
    build: BuildFn | None = None,
    spent: SpentFn | None = None,
    gate: GateFn | None = None,
) -> SqhDossier | None:
    """浏览器线程说页面恢复了(或等不到人了):接着把那份 needs_human 的档案做完。worker 的快循环每几秒问一次。
    ``event`` 不传就从 browser 线程取;测试直接传。"""
    now = now or datetime.now(UTC)
    if event is None:
        if not browser.enabled():
            return None
        event = browser.get().take_recovered()
    if not event:
        return None
    dossier_id = event.get("dossier_id")
    dossier = db.get(SqhDossier, int(dossier_id), execution_options=_X) if dossier_id else None
    if dossier is None or dossier.status != "needs_human":
        return None
    if event.get("outcome") != "recovered":
        dossier.status = "blocked"
        dossier.error = str(event.get("reason") or dossier.error or "等老板过验证没等到")[:500]
        db.add(dossier)
        memory.log_activity(db, f"1688 {dossier.offer_id}:{dossier.error[:80]},这单按被拦处理。", kind="error")
        _set_activity(db, "working", "1688 那页没等到人,今天先不碰")
        db.commit()
        return dossier
    if read is None or build is None:
        _, d_read, d_build = _defaults()
        read, build = read or d_read, build or d_build
        spent = spent or _ledger_spent
        gate = gate or compliance_gate.judge
    from .sourcing_1688 import capture_from_render, offer_url

    cost_since = datetime.now(UTC)
    memory.log_activity(db, f"老板帮我过了 1688 的验证,接着整理 {dossier.offer_id}。", kind="fetch")
    _set_activity(db, "thinking", f"在读 1688:{dossier.offer_id}")
    db.commit()
    try:
        capture = capture_from_render(
            offer_id=dossier.offer_id,
            target=offer_url(dossier.offer_id),
            final_url=str(event.get("final_url") or ""),
            title=str(event.get("title") or ""),
            html=str(event.get("html") or ""),
            text=str(event.get("text") or ""),
        ).to_dict()
        if capture.get("blocked"):
            dossier.status = "blocked"
            dossier.error = str(capture.get("block_reason") or "还是被拦")[:500]
            db.add(dossier)
            memory.log_activity(db, f"1688 {dossier.offer_id} 过了验证还是拿不到页面:{dossier.error[:60]}", kind="error")
            db.commit()
            return dossier
        return _complete(db, dossier, capture, read=read, build=build, spent=spent, cost_since=cost_since, gate=gate)
    except Exception as exc:  # noqa: BLE001
        return _fail(db, dossier.id, exc)


def requeue_needs_human(db: Session) -> int:
    """worker 重启:内存里的浏览器状态没了,还在 needs_human 的档案回队列重抓(profile 里的登录态还在,多半直接成)。"""
    rows = db.scalars(select(SqhDossier).where(SqhDossier.status == "needs_human"), execution_options=_X).all()
    for row in rows:
        row.status = "queued"
        row.error = None
        db.add(row)
    if rows:
        memory.log_activity(db, f"重启了,{len(rows)} 份等验证的档案重新排队。", kind="fetch")
        db.commit()
    return len(rows)


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
