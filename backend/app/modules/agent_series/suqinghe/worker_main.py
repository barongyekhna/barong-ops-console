"""苏青禾的常驻进程。影子期:只出方案、发审批卡、接老板的批/驳/交代,不动任何业务数据。

每一轮(SQH_LOOP_SECONDS,默认 60 秒):
1. 写业务心跳(间隔按 120 秒算,3 倍没成功 = 办公室显示「掉线」)。
2. 暂停中:只写心跳,别的都不做(C19 里老板的批/驳照样认——那是老板的动作,不是她的)。
3. 洛杉矶早上 7 点以后、今天还没出过计划:快照 → 对账(没了的事作废卡)→ 计划 → 审批卡(一件事只发一张,见 cards.settle_issues)。
4. 老板在办公室「交代一句」的事:记下、回执,影子期不执行。
5. 主动开口四规矩:一天最多一条、洛杉矶 8–22 点、只在有待审卡时、静音期内不说、同一天不重复。
6. 她建进 K 的产品往下推(pipeline.py):关键词 → 风险词 → 卖点 →(价格卡)→ …;在另一个线程里一件一件干。

C19 每 AGENT_CHAT_POLL_SECONDS(默认 3 秒)听一次:只回老板的私聊。

    python -m backend.app.modules.agent_series.suqinghe.worker_main                  # 常驻
    python -m backend.app.modules.agent_series.suqinghe.worker_main --run-morning-now # 立刻跑一次早间流程后退出(验收用)
"""

from __future__ import annotations

import logging
import re
import signal
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from types import FrameType
from typing import Any

import httpx
from sqlalchemy import select

from ....core.roles import is_owner_role
from ....db.session import SessionLocal
from ....models.user import User
from ..common.c19_client import C19Client, ConsoleAuthError
from ..common.memory_store import MemoryStore
from . import brain, browser, cards, dossiers, executor, memory, office, picks, pipeline, snapshot, seller_chat
from .constants import (
    AGENT_USERNAME,
    HEARTBEAT_INTERVAL_SECONDS,
    LA,
    MODULE_KEY,
    MORNING_HOUR,
    PASSWORD_ENV,
    WORKER_NAME,
    loop_seconds,
)

_LOGGER = logging.getLogger("suqinghe.worker")
_RUNNING = True
MAX_LOGIN_BACKOFF = 60.0
MESSAGE_LOOKBACK = 20
MAX_ANSWERED_KEEP = 2000
SPEAK_START_HOUR = 8
MORNING_MAX_ATTEMPTS = 3
MORNING_RETRY_MINUTES = 30
PICK_MAX_ATTEMPTS = 2  # 第⑥步挑新品:一天最多试两次(挑成了第二次只是白查一下),两次至少隔半小时
PICK_RETRY_MINUTES = 30
SPEAK_END_HOUR = 22
CHANNEL_LABELS = {"web": "网页", "c19": "C19", "mcp": "MCP"}

_APPROVE = re.compile(r"^\s*(?:批|准|同意|approve)\s*#?\s*([0-9a-fA-F]{4,8})\s*[。.!！]?\s*$")
_REJECT = re.compile(r"^\s*(?:驳回|驳|不批|reject)\s*#?\s*([0-9a-fA-F]{4,8})\s*[,，:：]?\s*(.*)$", re.S)


def _handle_stop(signum: int, frame: FrameType | None) -> None:
    del signum, frame
    global _RUNNING
    _RUNNING = False


def _sleep_interruptible(seconds: float, should_stop) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not should_stop():
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


def _heartbeat(*, success: bool, error: str = "") -> None:
    """业务心跳。**任何异常都不许冒出去**——监控不该拖垮被监控的人。"""
    try:
        from ....services.worker_heartbeat import record_failure, record_success

        with SessionLocal() as db:
            if success:
                record_success(db, worker_name=WORKER_NAME, module_key=MODULE_KEY, expected_interval_seconds=HEARTBEAT_INTERVAL_SECONDS)
            else:
                record_failure(db, worker_name=WORKER_NAME, module_key=MODULE_KEY, error=error[:2000], expected_interval_seconds=HEARTBEAT_INTERVAL_SECONDS)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("heartbeat write failed")


# ---------------------------------------------------------------- 纯函数(有测试)


@dataclass(frozen=True)
class Command:
    decision: str  # approve / reject
    ref: str
    reason: str = ""


def parse_command(text: str) -> Command | None:
    m = _APPROVE.match(text or "")
    if m:
        return Command("approve", m.group(1).lower())
    m = _REJECT.match(text or "")
    if m:
        return Command("reject", m.group(1).lower(), m.group(2).strip())
    return None


def la_date(now: datetime) -> date:
    return now.astimezone(LA).date()


def may_speak(*, now: datetime, pending: int, last_spoke: date | None, muted_until: date | None, paused: bool) -> bool:
    """主动开口四规矩:有事才说、一天一条、白天才说、静音期不说。暂停时也不说。"""
    if paused or pending <= 0:
        return False
    local = now.astimezone(LA)
    if not (SPEAK_START_HOUR <= local.hour < SPEAK_END_HOUR):
        return False
    today = local.date()
    if last_spoke == today:
        return False
    if muted_until is not None and today <= muted_until:
        return False
    return True


def should_run_morning(*, now: datetime, last_plan: date | None) -> bool:
    local = now.astimezone(LA)
    return local.hour >= MORNING_HOUR and last_plan != local.date()


def reminder_text(pending: int) -> str:
    return f"老板,今天有 {pending} 张卡等你,在办公室里(右下角我的头像)。不急,你有空再看。"


def decided_text(card: Any, *, changed: bool, decision: str, execution: dict[str, Any] | None = None) -> str:
    if not changed:
        channel = CHANNEL_LABELS.get(card.decided_via or "", card.decided_via or "")
        if card.status == "approved":
            return f"#{card.ref} 这张卡已经批过了({channel})。"
        if card.status == "rejected":
            return f"#{card.ref} 这张卡已经驳过了({channel})。"
        if card.decision_reason in cards.RETIRE_REASONS:
            return f"#{card.ref} 这张卡已经作废了:{card.decision_reason}"
        if card.status == "stale":
            return f"#{card.ref} 这张卡已经作废了:底层数据变了,我会按新数据重出。"
        return f"#{card.ref} 这张卡现在是 {card.status},不用再处理。"
    if card.status == "stale":
        return f"#{card.ref} 建卡后数据变了,这张卡我作废了,明早按新数据重出。"
    if decision == "approve" and execution is not None:
        if execution.get("ok"):
            return f"收到,#{card.ref} 批了。{execution.get('note', '')}"
        return f"#{card.ref} 批了,但我没做成:{execution.get('note', '')}。我记下了,你看一眼。"
    if decision == "approve":
        return f"收到,#{card.ref}「{card.title}」批了。影子期我先记下,不动手。"
    if execution is not None and execution.get("note"):
        return f"收到,#{card.ref} 驳了。{execution['note']}"
    return f"收到,#{card.ref} 驳了,原因我记住了,同类的不再提。"


def build_failed_text(outcome: dict[str, Any]) -> str:
    return f"#{outcome['card_ref']} 批了,但建进 K 没成:{outcome['note']}。我记下了,你看一眼。"


# ---------------------------------------------------------------- 状态小工具


def _set_activity(db, activity: str, task: str, progress: int | None = None) -> None:
    state = office.get_state(db)
    state.activity = activity
    state.task = task[:300]
    state.progress = progress
    db.add(state)
    db.commit()


def owner_users(db) -> list[User]:
    rows = db.scalars(select(User).where(User.is_active.is_(True)))
    return [u for u in rows if is_owner_role(u.role or "") and not getattr(u, "is_bot", False)]


# ---------------------------------------------------------------- 早间流程


def run_morning(db, *, now: datetime | None = None) -> dict[str, Any]:
    """快照 → 计划 → 审批卡。返回摘要(验收脚本看)。"""
    now = now or datetime.now(UTC)
    today = la_date(now)
    _set_activity(db, "thinking", "在看今天的全局快照…", 10)
    memory.log_activity(db, "开始看今天的全局快照。", kind="snapshot")
    db.commit()
    snap = snapshot.build_snapshot(db, now=now)
    snapshot.save_snapshot(db, snap, now=now)
    memory.log_activity(db, f"快照:{snap.get('headline', '')}"[:500], kind="snapshot")
    db.commit()

    live, readable = brain.issues_in(snap)
    settled = cards.settle_issues(db, live=set(live), readable=readable, today=today.isoformat())
    if settled["merged"]:
        memory.log_activity(db, f"旧卡里同一件事发了好几张,合并掉 {settled['merged']} 张;还在的事今天按新规矩最多再出一张。", kind="plan")
    if settled["gone"]:
        memory.log_activity(db, f"{settled['gone']} 张卡上的事今天已经没有了,卡作废。", kind="plan")
    raised = cards.raised_issues(db)
    db.commit()

    _set_activity(db, "thinking", "在想今天的计划…", 40)
    result = brain.plan(db, snap, already_raised=raised)
    created = 0
    if result is None:
        memory.log_activity(db, "计划没出来(脑子没接通或输出不对),下一轮再试。", kind="error")
        _set_activity(db, "working", "计划没出来,等下一轮再试", None)
        db.commit()
        return {"snapshot": snap.get("headline"), "plan": None, "cards_created": 0}

    _set_activity(db, "working", "在写审批卡…", 80)
    for item in result.cards:
        if item["issue"] in raised:  # 提示词里说了别再发,模型还是发了
            continue
        evidence: dict[str, Any] = {"snapshot_date": today.isoformat(), "plan_role": result.role, "issue": item["issue"]}
        if item.get("product_id"):
            evidence["recheck"] = {"type": "product_gate", "product_id": item["product_id"]}
        _, is_new = cards.create_card(
            db,
            dedupe_key=f"issue:{item['issue']}:{today.isoformat()}",
            kind=item["kind"],
            title=item["title"],
            conclusion=item["conclusion"],
            why=item.get("why", ""),
            if_not=item.get("if_not", ""),
            reversible=item.get("reversible", True),
            confidence=item.get("confidence", "medium"),
            evidence=evidence,
        )
        created += int(is_new)
    memory.record(db, kind="plan", subject=f"{today.isoformat()} 计划", body=result.plan, refs={"role": result.role, "degraded": result.degraded})
    note = "(今天额度紧,用的是便宜档)" if result.degraded else ""
    memory.log_activity(db, f"今天的计划出好了,新卡 {created} 张{note}。", kind="plan")
    state = office.get_state(db)
    state.last_plan_date = today
    db.add(state)
    db.commit()
    first_line = result.plan.splitlines()[0] if result.plan else "今天的计划出好了"
    _set_activity(db, "working", first_line[:300], None)
    return {"snapshot": snap.get("headline"), "plan": result.plan, "cards_created": created, "role": result.role, "settled": settled}


def intake_links(db, links: list[tuple[str, str]], *, actor_user_id: str) -> str:
    """老板在 C19 里丢了 1688 链接:排队,回一句排第几、大概多久。"""
    replies: list[str] = []
    for url, offer_id in links[:5]:
        dossier, created, position = dossiers.enqueue(db, url=url, actor_user_id=actor_user_id, channel="c19")
        replies.append(f"{offer_id}:" + dossiers.queue_reply(position, created=created, status=dossier.status))
    db.commit()
    if len(links) > 5:
        replies.append("一次最多收 5 个,剩下的等这批做完再发我。")
    return "\n".join(replies)


def handle_dictations(db) -> int:
    rows = memory.unhandled_dictations(db)
    for row in rows:
        memory.log_activity(db, f"收到老板交代:{row.body[:80]}——影子期先记下,不动手。", kind="instruct")
        memory.mark_handled(db, row, note="影子期:已记录,未执行")
    if rows:
        db.commit()
    return len(rows)


# ---------------------------------------------------------------- 进程


class SuqingheWorker:
    def __init__(self, *, client: C19Client | None = None, store: MemoryStore | None = None, clock=None) -> None:
        self.client = client or C19Client(username=AGENT_USERNAME, password_env=PASSWORD_ENV)
        self.store = store or MemoryStore(username=AGENT_USERNAME, index_title="苏青禾的记忆")
        self.clock = clock or (lambda: datetime.now(UTC))
        self.cursor: str | None = None
        self.online = False
        self.answered: list[str] = self.store.load_state("answered", [])
        self.owner_conversations: dict[str, str] = {}
        self._morning_day: date | None = None
        self._morning_attempts = 0
        self._morning_last: datetime | None = None
        self._pick_day: date | None = None
        self._pick_attempts = 0
        self._pick_last: datetime | None = None
        # 第②步:K 流水线在另一个线程里一件一件推(一步能跑十几分钟,不能卡住聊天和批卡建档)
        self.pipeline = pipeline.Runner()

    # ---- C19 ----

    def connect(self) -> bool:
        try:
            self.client.login()
            self.cursor = self.client.event_tail()
            self.online = True
            _LOGGER.info("苏青禾上线,游标 %s", self.cursor)
            return True
        except (ConsoleAuthError, httpx.HTTPError) as exc:
            self.online = False
            _LOGGER.warning("C19 上线失败: %s", exc)
            return False

    def _owner_conversation(self, owner_id: str) -> str | None:
        cid = self.owner_conversations.get(owner_id)
        if cid:
            return cid
        cid = self.client.direct_conversation_with(owner_id)
        if cid:
            self.owner_conversations[owner_id] = cid
        return cid

    def build_approved(self) -> bool:
        """老板批了的「建 K 档案」卡,在这里真的建(K 建档 + 下参考图是慢活,不放在点「批」的请求里)。

        一轮一单;暂停时也照做 —— 这是老板亲口批的。没建成就「出事就说」:在 C19 告诉批卡的人。
        """
        db = SessionLocal()
        try:
            waiting = executor.approved_waiting(db, limit=1)
            if not waiting:
                return False
            dossier, card = waiting[0]
            approver = str(card.decided_by_user_id or "")
            outcome = executor.build_approved(db, dossier, card)
            if not outcome["ok"] and approver and (self.online or self.connect()):
                cid = self._owner_conversation(approver)
                if cid:
                    self.client.send_message(cid, text=build_failed_text(outcome), client_message_id=f"sqh-build-{uuid.uuid4().hex[:20]}")
            return True
        finally:
            db.close()

    def poll_chat(self) -> bool:
        if not self.online:
            return False
        page = self.client.events(cursor=self.cursor)
        if page.get("next_cursor"):
            self.cursor = page["next_cursor"]
        conversation_ids: list[str] = []
        for event in page.get("events") or []:
            cid = event.get("conversation_id")
            if cid and cid not in conversation_ids:
                conversation_ids.append(cid)
        handled = False
        for cid in conversation_ids:
            try:
                handled = self.handle_conversation(cid) or handled
            except Exception:  # noqa: BLE001
                _LOGGER.exception("处理会话 %s 失败", cid)
        return handled

    def handle_conversation(self, conversation_id: str) -> bool:
        records = self.client.messages(conversation_id, limit=MESSAGE_LOOKBACK)
        my_id = str(self.client.user_id)
        incoming = [r for r in records if str(r.get("sender_user_id")) != my_id and r.get("content_type") in {"text", "emoji"}]
        if not incoming:
            return False
        latest = max(incoming, key=lambda r: int(r.get("sequence") or 0))
        my_last = max((int(r.get("sequence") or 0) for r in records if str(r.get("sender_user_id")) == my_id), default=0)
        if int(latest.get("sequence") or 0) <= my_last:
            return False
        record_id = str(latest.get("record_id") or latest.get("id") or f"{conversation_id}:{latest.get('sequence')}")
        text = str(latest.get("content") or "").strip()
        if not text or record_id in self.answered:
            return False
        reply = self.reply_for(speaker_id=str(latest.get("sender_user_id")), text=text)
        # 先记「已答」再发:宁可漏答一次,也不重复刷屏。
        self._mark_answered(record_id)
        if reply:
            self.client.send_message(conversation_id, text=reply, client_message_id=f"sqh-{uuid.uuid4().hex[:24]}")
        return True

    def reply_for(self, *, speaker_id: str, text: str) -> str:
        db = SessionLocal()
        try:
            speaker = db.get(User, int(speaker_id)) if speaker_id.isdigit() else None
            if speaker is None or not is_owner_role(speaker.role or ""):
                return "我只听老板的安排。想看我在忙什么,点控制台右下角我的头像就行。"
            links = dossiers.find_1688_links(text)
            if links:
                return intake_links(db, links, actor_user_id=str(speaker.id))
            command = parse_command(text)
            if command is not None:
                try:
                    outcome = cards.decide_card(db, card_id=command.ref, decision=command.decision, actor=speaker, channel="c19", reason=command.reason or None)
                except cards.CardError as exc:
                    db.rollback()
                    return exc.message
                db.commit()
                return decided_text(outcome.card, changed=outcome.changed, decision=command.decision, execution=outcome.execution)
            state = office.get_state(db)
            if state.paused:
                return "老板,我现在是暂停状态。批卡照样可以在这儿说「批 #编号」;要我接着干,在办公室点「恢复」。"
            pending = len(cards.pending_cards(db))
            result = brain.chat(db, text, context=f"现在有 {pending} 张待审卡。影子期:你只出方案,不执行。")
            if result.dictation:
                memory.record(db, kind="dictation", subject="老板口述", body=result.dictation, refs={"handled": True, "channel": "c19"}, source="human", actor_user_id=str(speaker.id))
            if result.mute_days:
                state = office.get_state(db)
                state.muted_until = la_date(self.clock()) + timedelta(days=result.mute_days)
                db.add(state)
            db.commit()
            return result.reply
        finally:
            db.close()

    def _mark_answered(self, record_id: str) -> None:
        self.answered.append(record_id)
        if len(self.answered) > MAX_ANSWERED_KEEP:
            self.answered = self.answered[-MAX_ANSWERED_KEEP:]
        self.store.save_state("answered", self.answered)

    # ---- 主动开口 ----

    def maybe_remind(self, db) -> bool:
        now = self.clock()
        state = office.get_state(db)
        pending = len(cards.pending_cards(db))
        if not may_speak(now=now, pending=pending, last_spoke=state.last_spoke_date, muted_until=state.muted_until, paused=state.paused):
            return False
        if not self.online and not self.connect():
            return False
        # 先记「今天说过了」再发:宁可漏一条,也不重复刷屏。
        state.last_spoke_date = la_date(now)
        db.add(state)
        db.commit()
        sent = False
        for owner in owner_users(db):
            cid = self._owner_conversation(str(owner.id))
            if not cid:
                continue
            self.client.send_message(cid, text=reminder_text(pending), client_message_id=f"sqh-remind-{uuid.uuid4().hex[:20]}")
            sent = True
        if sent:
            memory.log_activity(db, f"在 C19 提醒了老板:{pending} 张卡待审。", kind="speak")
            db.commit()
        return sent

    # ---- 一轮 ----

    def _morning_attempt_allowed(self, now: datetime) -> bool:
        """早间计划失败时别每分钟重来一遍(每次都要出网拉快照、调一次 Opus):
        同一天最多试 MORNING_MAX_ATTEMPTS 次,两次之间至少隔 MORNING_RETRY_MINUTES 分钟。"""
        today = la_date(now)
        if self._morning_day != today:
            self._morning_day, self._morning_attempts, self._morning_last = today, 0, None
        if self._morning_attempts >= MORNING_MAX_ATTEMPTS:
            return False
        if self._morning_last is not None and now - self._morning_last < timedelta(minutes=MORNING_RETRY_MINUTES):
            return False
        self._morning_attempts += 1
        self._morning_last = now
        return True

    def _pick_attempt_allowed(self, now: datetime) -> bool:
        """挑新品同理:一天最多 PICK_MAX_ATTEMPTS 次,两次之间至少隔 PICK_RETRY_MINUTES 分钟(每次都要调一次模型)。"""
        today = la_date(now)
        if self._pick_day != today:
            self._pick_day, self._pick_attempts, self._pick_last = today, 0, None
        if self._pick_attempts >= PICK_MAX_ATTEMPTS:
            return False
        if self._pick_last is not None and now - self._pick_last < timedelta(minutes=PICK_RETRY_MINUTES):
            return False
        self._pick_attempts += 1
        self._pick_last = now
        return True

    def tick(self) -> None:
        db = SessionLocal()
        try:
            state = office.get_state(db)
            db.commit()
            if state.paused:
                return
            now = self.clock()
            if should_run_morning(now=now, last_plan=state.last_plan_date) and self._morning_attempt_allowed(now):
                run_morning(db, now=now)
            handle_dictations(db)
            # 1688 → K 档案:一轮最多一单,节流在 dossiers.process_next 里。
            dossiers.process_next(db, now=now)
            # 第⑥步:早间计划排完后去找货池里挑今天的新品(一天几张卡、攒多了不发,都在 picks 里管)
            if picks.should_pick(now=now, last_plan=office.get_state(db).last_plan_date) and self._pick_attempt_allowed(now):
                picks.run_picks(db, now=now)
            # 建进 K 的产品往下推:线程闲着就派下一件(暂停时上面已经 return,不派新活)
            self.pipeline.maybe_start(db)
            # B 期(10-29):问过卖家的档案到点去旺旺看回复(一轮最多一单;浏览器正等老板就跳过)
            try:
                seller_chat.poll_all(db, now=now)
            except Exception:  # noqa: BLE001 —— 看回复出错不拖垮这一轮
                _LOGGER.exception("看卖家回复出错")
            try:
                self.maybe_remind(db)
            except (ConsoleAuthError, httpx.HTTPError) as exc:
                _LOGGER.warning("提醒没发出去: %s", exc)
                self.online = False
        finally:
            db.close()

    def resume_human(self) -> bool:
        """浏览器线程说老板过完验证了(或等不到人):接着把那份档案做完。开关关着什么都不做。"""
        if not browser.enabled():
            return False
        with SessionLocal() as db:
            return dossiers.resume_human(db, now=self.clock()) is not None

    def run_forever(self, *, should_stop) -> None:
        backoff = 2.0
        next_tick = 0.0
        if browser.enabled():
            try:
                with SessionLocal() as db:
                    dossiers.requeue_needs_human(db)  # 重启后内存里的浏览器状态没了,等验证的档案回队列
                browser.get()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("browser session init failed")
        while not should_stop():
            if not self.online:
                if not self.connect():
                    _heartbeat(success=False, error="C19 登录失败")
                    _sleep_interruptible(backoff, should_stop)
                    backoff = min(backoff * 2, MAX_LOGIN_BACKOFF)
                    # 登不上 C19 也照样干早上的活(计划和卡不依赖 C19)
                else:
                    backoff = 2.0
            if time.monotonic() >= next_tick:
                try:
                    self.tick()
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.exception("这一轮出错")
                    _heartbeat(success=False, error=f"tick: {exc!r}")
                else:
                    _heartbeat(success=True)
                next_tick = time.monotonic() + loop_seconds()
            built = False
            try:
                built = self.build_approved()
            except Exception:  # noqa: BLE001 —— 建档出错不能拖垮整个循环;没记上账的下一轮还会再捡到
                _LOGGER.exception("批了的档案建 K 出错")
            resumed = False
            try:
                resumed = self.resume_human()
            except Exception:  # noqa: BLE001 —— 续做出错不拖垮循环;档案已落 failed/blocked
                _LOGGER.exception("等验证的档案续做出错")
            busy = False
            try:
                busy = self.poll_chat()
            except ConsoleAuthError:
                self.online = False
            except httpx.HTTPError as exc:
                _LOGGER.warning("控制台暂时够不着: %s", exc)
                self.online = False
            if not busy and not built and not resumed:
                _sleep_interruptible(_chat_poll_seconds(), should_stop)
        if browser.enabled():
            browser.shutdown()  # 10-28:关干净才不留 SingletonLock,下个容器(新主机名)才起得来 Chromium


def _chat_poll_seconds() -> float:
    import os

    try:
        return max(1.0, float(os.getenv("AGENT_CHAT_POLL_SECONDS", "3")))
    except ValueError:
        return 3.0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = list(sys.argv[1:] if argv is None else argv)
    if "--run-morning-now" in args:
        db = SessionLocal()
        try:
            summary = run_morning(db)
            print(summary)
            worker = SuqingheWorker()
            try:
                print({"reminded": worker.maybe_remind(db)})
            except (ConsoleAuthError, httpx.HTTPError) as exc:
                print({"reminded": False, "error": str(exc)[:200]})
        finally:
            db.close()
        return 0
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    SuqingheWorker().run_forever(should_stop=lambda: not _RUNNING)
    _LOGGER.info("苏青禾下线")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
