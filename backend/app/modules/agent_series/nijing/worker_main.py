"""霓旌的常驻进程:听 C19 → 听懂 → 对账本 → 出确认卡 → 确认后落单。

护栏全在代码里:
- 说话人必须过 M 的角色门(owner / 制造公司 super_admin),否则一句话都不办
- 每一笔写入先出卡,说「确认」才执行;一张卡只对应一个说话人,30 分钟过期
- 同一条 C19 消息永远只执行一次(executed 状态)
- 模型超时/出错 → 回「没接通,什么都没做」,绝不带着不确定往下走
"""

from __future__ import annotations

import logging
import re
import signal
import time
import uuid
from types import FrameType
from typing import Any

import httpx

from ....db.session import SessionLocal
from ....models.user import User
from ....repositories.operation_logs import create_operation_log
from ..common.c19_client import C19Client, ConsoleAuthError
from ..common.memory_store import MemoryStore
from . import brain, executor
from .constants import (
    ACTOR_TYPE,
    AGENT_ID,
    AGENT_USERNAME,
    CANCEL_WORDS,
    CARD_TTL_SECONDS,
    CONFIRM_WORDS,
    MEMORY_INDEX_TITLE,
    MESSAGE_LOOKBACK,
    PASSWORD_ENV,
    poll_seconds,
)
from .executor import Card, NeedsClarification, NotAuthorized
from .intents import RED_INTENTS, WRITE_INTENTS, Intent, qty_supported_by_text

_LOGGER = logging.getLogger("nijing.worker")
_RUNNING = True
MAX_LOGIN_BACKOFF = 60.0
MAX_EXECUTED_KEEP = 2000

REPLY_NOT_AUTHORIZED = "库存仅限 owner、制造公司超级管理员,或在权限页拿到库存权限的制造公司成员,我帮不了你。"
REPLY_READ_ONLY = "你的账号只能查库存,没有「管理制造库存」权限,入库/生产/发货/调整我办不了。"
REPLY_MULTI = "一次只说一件事吧——把入库、生产、发货分开发给我,我一件一件开单。"
REPLY_OFFLINE = "没接通脑子,这句我没处理,什么都没做。稍后再说一遍。"
REPLY_RED = "这个要在控制台做:「库存」→ 物料/成品 → 新建 / 配件清单 / 归档。主档我不碰。"
REPLY_UNSUPPORTED = "没听懂。我能办:入库、生产、发货、盘点调整、查库存、查单据、撤销刚才的单。"
REPLY_CHITCHAT = "在的。说一句「入库 1000 条桌腿」「生产 20 套折叠桌」「桌腿还剩多少」这样的话就行。"
REPLY_CANCELLED = "已取消,什么都没做。"
REPLY_NO_QTY = "没看清数量,请用阿拉伯数字再说一遍(比如「入库 1000 条桌腿」)。"


def _handle_stop(signum: int, frame: FrameType | None) -> None:
    del signum, frame
    global _RUNNING
    _RUNNING = False
    _LOGGER.info("收到停止信号,处理完当前这轮就退出")


def _heartbeat(*, success: bool, error: str = "") -> None:
    """记一次业务心跳。**任何异常都不许冒出去** —— 监控不该拖垮被监控的人。"""
    try:
        from ....db.session import SessionLocal
        from ....services.worker_heartbeat import record_failure, record_success

        with SessionLocal() as db:
            if success:
                record_success(
                    db,
                    worker_name="nijing-worker",
                    module_key="agent.nijing",
                    expected_interval_seconds=900,
                )
            else:
                record_failure(
                    db,
                    worker_name="nijing-worker",
                    module_key="agent.nijing",
                    error=error,
                    expected_interval_seconds=900,
                )
    except Exception:  # noqa: BLE001
        pass

def _sleep_interruptible(seconds: float, should_stop) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not should_stop():
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


def _log_operation(*, action: str, target_type: str, target_id: str, result: str, details: dict[str, Any] | None = None, error_code: str | None = None) -> None:
    db = SessionLocal()
    try:
        create_operation_log(
            db,
            actor_type=ACTOR_TYPE,
            actor_id=AGENT_ID,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=result,
            error_code=error_code,
            details=details,
        )
        db.commit()
    except Exception:  # noqa: BLE001
        _LOGGER.exception("写 operation_log 失败")
        db.rollback()
    finally:
        db.close()


_CARD_REF = re.compile(r"^(?P<word>.+?)\s*#(?P<card>[0-9a-f]{4})\s*$")


def _split_card_ref(text: str) -> tuple[str, str | None]:
    """「确认 #ab12」→ ("确认", "ab12");「确认」→ ("确认", None)。"""
    t = text.strip().strip("。!！.")
    m = _CARD_REF.match(t)
    if m:
        return m.group("word").strip().casefold(), m.group("card")
    return t.casefold(), None


def _is_confirm(text: str) -> bool:
    return _split_card_ref(text)[0] in CONFIRM_WORDS


def _is_cancel(text: str) -> bool:
    return _split_card_ref(text)[0] in CANCEL_WORDS


def _card_ref(text: str) -> str | None:
    return _split_card_ref(text)[1]


class NijingWorker:
    def __init__(self, *, client: C19Client | None = None, store: MemoryStore | None = None, session_factory=None, extract=None, clock=None) -> None:
        self.client = client or C19Client(username=AGENT_USERNAME, password_env=PASSWORD_ENV)
        self.store = store or MemoryStore(username=AGENT_USERNAME, index_title=MEMORY_INDEX_TITLE)
        self.session_factory = session_factory or SessionLocal
        self.extract = extract or brain.extract_intent
        self.clock = clock or time.time
        self.cursor: str | None = None
        self.pending: dict[str, dict[str, Any]] = self.store.load_state("pending", {})
        self.executed: list[str] = self.store.load_state("executed", [])

    # ---------- 生命周期 ----------

    def connect(self, *, should_stop) -> bool:
        backoff = 2.0
        while not should_stop():
            try:
                self.client.login()
                self.cursor = self.client.event_tail()
                _LOGGER.info("霓旌上线,从游标 %s 开始听", self.cursor)
                return True
            except (ConsoleAuthError, httpx.HTTPError) as exc:
                _LOGGER.warning("上线失败(%s),%.0f 秒后重试", exc, backoff)
                _sleep_interruptible(backoff, should_stop)
                backoff = min(backoff * 2, MAX_LOGIN_BACKOFF)
        return False

    def run_once(self) -> bool:
        page = self.client.events(cursor=self.cursor)
        events = page.get("events") or []
        if page.get("next_cursor"):
            self.cursor = page["next_cursor"]
        if not events:
            return False
        conversation_ids: list[str] = []
        for event in events:
            cid = event.get("conversation_id")
            if cid and cid not in conversation_ids:
                conversation_ids.append(cid)
        handled = False
        for cid in conversation_ids:
            try:
                if self.handle_conversation(cid):
                    handled = True
            except Exception as exc:  # noqa: BLE001
                _LOGGER.exception("处理会话 %s 失败", cid)
                _log_operation(action="agent.chat.reply", target_type="c19_conversation", target_id=cid, result="failure", error_code="AGENT_REPLY_FAILED", details={"error": str(exc)[:500]})
        return handled

    def run_forever(self, *, should_stop) -> None:
        if not self.connect(should_stop=should_stop):
            return
        interval = poll_seconds()
        while not should_stop():
            try:
                busy = self.run_once()
            except ConsoleAuthError:
                if not self.connect(should_stop=should_stop):
                    return
                busy = False
            except httpx.HTTPError as exc:
                _LOGGER.warning("控制台暂时够不着: %s", exc)
                # 2026-08-31 那一周,她的日志里全是这句,而没有任何人看得到——
                # 因为她上报「我够不着控制台」的通道**就是控制台**。
                # 现在它会落进心跳表,由一个不依赖控制台的脚本读走。
                _heartbeat(success=False, error=f"控制台够不着: {exc!r}")
                busy = False
            else:
                # 走完一轮没抛异常 = 这一轮干成了。
                _heartbeat(success=True)
            if not busy:
                _sleep_interruptible(interval, should_stop)

    # ---------- 一条消息 ----------

    def handle_conversation(self, conversation_id: str) -> bool:
        records = self.client.messages(conversation_id, limit=MESSAGE_LOOKBACK)
        if not records:
            return False
        my_id = str(self.client.user_id)
        incoming = [r for r in records if str(r.get("sender_user_id")) != my_id and r.get("content_type") in {"text", "emoji"}]
        if not incoming:
            return False
        latest = max(incoming, key=lambda r: int(r.get("sequence") or 0))
        my_last = max((int(r.get("sequence") or 0) for r in records if str(r.get("sender_user_id")) == my_id), default=0)
        if int(latest.get("sequence") or 0) <= my_last:
            return False
        text = str(latest.get("content") or "").strip()
        record_id = str(latest.get("record_id") or latest.get("id") or f"{conversation_id}:{latest.get('sequence')}")
        speaker_id = str(latest.get("sender_user_id"))
        if not text or record_id in self.executed:
            return False

        reply = self.reply_for(conversation_id=conversation_id, speaker_id=speaker_id, text=text, record_id=record_id)
        self.client.send_message(conversation_id, text=reply, client_message_id=f"nj-{uuid.uuid4().hex[:24]}")
        return True

    def reply_for(self, *, conversation_id: str, speaker_id: str, text: str, record_id: str) -> str:
        if record_id in self.executed:
            return "这条确认已经办过了。"
        db = self.session_factory()
        try:
            speaker = db.get(User, int(speaker_id)) if speaker_id.isdigit() else None
            if speaker is None:
                return REPLY_NOT_AUTHORIZED
            try:
                ctx = executor.authorize(db, speaker)
            except NotAuthorized:
                _log_operation(action="agent.mfg.denied", target_type="user", target_id=speaker_id, result="denied", details={"record_id": record_id})
                return REPLY_NOT_AUTHORIZED
            except executor.service.FactoryNotConfigured as exc:
                return f"系统里没配置好制造组织({exc}),我办不了。"

            # ---- 有待确认卡 ----
            pending = self.pending.get(conversation_id)
            if pending:
                card = Card.from_dict(pending)
                expired = self.clock() - float(card.created_at) > CARD_TTL_SECONDS
                if expired:
                    self._drop_pending(conversation_id)
                    pending = None
                elif card.speaker_id != speaker_id:
                    return f"这张卡是别人开的,只有开卡的人能确认。#{card.card_id}"
                elif (_is_confirm(text) or _is_cancel(text)) and _card_ref(text) not in (None, card.card_id):
                    return f"#{_card_ref(text)} 这张卡已作废,当前待确认的是 #{card.card_id}。"
                elif _is_confirm(text):
                    return self._execute(db, ctx, card=card, speaker=speaker, text=text, record_id=record_id, conversation_id=conversation_id)
                elif _is_cancel(text):
                    self._drop_pending(conversation_id)
                    _log_operation(action="agent.mfg.cancel", target_type="mfg_card", target_id=card.card_id, result="success", details={"speaker_user_id": speaker_id})
                    return REPLY_CANCELLED
                else:
                    self._drop_pending(conversation_id)
                    prefix = f"上一张卡 #{card.card_id} 已作废。\n"
                    return prefix + self._fresh(db, ctx, speaker=speaker, text=text, record_id=record_id, conversation_id=conversation_id)
            if _is_confirm(text) or _is_cancel(text):
                ref = _card_ref(text)
                return f"#{ref} 这张卡已经处理过或已作废。" if ref else "现在没有待确认的卡。"
            return self._fresh(db, ctx, speaker=speaker, text=text, record_id=record_id, conversation_id=conversation_id)
        finally:
            db.close()

    def _fresh(self, db, ctx, *, speaker: User, text: str, record_id: str, conversation_id: str) -> str:
        try:
            intent: Intent = self.extract(text)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("脑子没接通: %s", exc)
            _log_operation(action="agent.mfg.brain", target_type="c19_conversation", target_id=conversation_id, result="failure", error_code="AGENT_AI_UNAVAILABLE", details={"error": str(exc)[:300]})
            return REPLY_OFFLINE

        name = intent.intent
        if name == "multi":
            return REPLY_MULTI
        if name in RED_INTENTS:
            return REPLY_RED
        if name == "chitchat":
            return REPLY_CHITCHAT
        if name == "unsupported":
            return REPLY_UNSUPPORTED
        if name == "query_stock":
            return executor.stock_reply(db, ctx, intent)
        if name == "query_documents":
            return executor.documents_reply(db, ctx, intent)
        try:
            if name == "undo":
                card = executor.build_undo_card(db, ctx, intent=intent, speaker=speaker, conversation_id=conversation_id, now=self.clock())
            elif name in WRITE_INTENTS:
                if intent.qty is None or not qty_supported_by_text(intent.qty, text):
                    return REPLY_NO_QTY
                card = executor.build_card(db, ctx, intent=intent, speaker=speaker, conversation_id=conversation_id, now=self.clock())
            else:
                return REPLY_UNSUPPORTED
        except NeedsClarification as exc:
            return str(exc)
        except NotAuthorized:
            return REPLY_READ_ONLY
        except executor.MfgError as exc:
            return str(exc)
        card.request_text = text
        self.pending[conversation_id] = card.to_dict()
        self.store.save_state("pending", self.pending)
        return card.text

    def _execute(self, db, ctx, *, card: Card, speaker: User, text: str, record_id: str, conversation_id: str) -> str:
        if record_id in self.executed:
            return "这条确认已经办过了。"
        # 先记 executed 再落单:宁可漏办一次(用户会再说),绝不重复落单
        self._mark_executed(record_id)
        self._drop_pending(conversation_id)
        try:
            reply, doc_nos = executor.execute_card(db, ctx, card=card, speaker=speaker, original_text=text, record_id=record_id)
        except NotAuthorized:
            return REPLY_READ_ONLY
        except executor.InsufficientStock as exc:
            _log_operation(action=f"agent.mfg.{card.kind}", target_type="mfg_card", target_id=card.card_id, result="rejected", details={"speaker_user_id": str(speaker.id), "reason": str(exc)[:300]})
            return f"落单时被拦住了(这段时间库存变了):{exc}\n没有登记。"
        except executor.MfgError as exc:
            _log_operation(action=f"agent.mfg.{card.kind}", target_type="mfg_card", target_id=card.card_id, result="rejected", details={"speaker_user_id": str(speaker.id), "reason": str(exc)[:300]})
            return f"落单失败:{exc}\n没有登记。"
        _log_operation(
            action=f"agent.mfg.{card.kind}",
            target_type="mfg_document",
            target_id=",".join(doc_nos),
            result="success",
            details={"speaker_user_id": str(speaker.id), "record_id": record_id, "card_id": card.card_id, "text": text[:200]},
        )
        self.store.append_conversation_note(str(speaker.id), f"{card.kind} {','.join(doc_nos)} ← {text[:80]}")
        return reply

    def _drop_pending(self, conversation_id: str) -> None:
        if conversation_id in self.pending:
            del self.pending[conversation_id]
            self.store.save_state("pending", self.pending)

    def _mark_executed(self, record_id: str) -> None:
        self.executed.append(record_id)
        if len(self.executed) > MAX_EXECUTED_KEEP:
            self.executed = self.executed[-MAX_EXECUTED_KEEP:]
        self.store.save_state("executed", self.executed)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    worker = NijingWorker()
    worker.run_forever(should_stop=lambda: not _RUNNING)
    _LOGGER.info("霓旌下线")


if __name__ == "__main__":
    main()
