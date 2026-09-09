"""殷承岳的常驻进程:听 C19 → 判类目 → 回一张类目卡。

护栏全在代码里:
- 他没有任何写动作,所以不设权限门,谁问都答
- 候选由代码从 k_category_google 查出,模型只能在候选里选;选了候选外的 id 按「没选」处理
- 同一条 C19 消息只答一次(answered 状态),宁可漏答一次也不重复刷屏
- 模型超时/出错 → 回「没接通」,绝不带着不确定往下走

主循环与霓旌一致(有意复制而不是抽基类:两个在产线跑稳的员工不该被这次发版卷进来)。
"""

from __future__ import annotations

import logging
import signal
import time
import uuid
from types import FrameType
from typing import Any

import httpx

from ....db.session import SessionLocal
from ....repositories.operation_logs import create_operation_log
from ..common.c19_client import C19Client, ConsoleAuthError
from ..common.memory_store import MemoryStore
from . import classifier
from .constants import (
    ACTOR_TYPE,
    AGENT_ID,
    AGENT_USERNAME,
    MAX_ANSWERED_KEEP,
    MEMORY_INDEX_TITLE,
    MESSAGE_LOOKBACK,
    MODULE_KEY,
    PASSWORD_ENV,
    WORKER_NAME,
    poll_seconds,
)
from .reply import REPLY_CHITCHAT, is_chitchat, render_verdict

_LOGGER = logging.getLogger("yinchengyue.worker")
_RUNNING = True
MAX_LOGIN_BACKOFF = 60.0


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
                record_success(db, worker_name=WORKER_NAME, module_key=MODULE_KEY, expected_interval_seconds=900)
            else:
                record_failure(db, worker_name=WORKER_NAME, module_key=MODULE_KEY, error=error, expected_interval_seconds=900)
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


class YinchengyueWorker:
    def __init__(self, *, client: C19Client | None = None, store: MemoryStore | None = None, session_factory=None, classify=None, clock=None) -> None:
        self.client = client or C19Client(username=AGENT_USERNAME, password_env=PASSWORD_ENV)
        self.store = store or MemoryStore(username=AGENT_USERNAME, index_title=MEMORY_INDEX_TITLE)
        self.session_factory = session_factory or SessionLocal
        self.classify = classify or classifier.classify
        self.clock = clock or time.time
        self.cursor: str | None = None
        self.answered: list[str] = self.store.load_state("answered", [])

    # ---------- 生命周期 ----------

    def connect(self, *, should_stop) -> bool:
        backoff = 2.0
        while not should_stop():
            try:
                self.client.login()
                self.cursor = self.client.event_tail()
                _LOGGER.info("殷承岳上线,从游标 %s 开始听", self.cursor)
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
                # 上报「够不着控制台」的通道就是控制台,所以这里落心跳表,由独立脚本读走。
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
        if not text or record_id in self.answered:
            return False

        reply = self.reply_for(conversation_id=conversation_id, speaker_id=speaker_id, text=text, record_id=record_id)
        if not reply:
            return False
        # 先记「已答」再发:宁可漏答一次,也不在发送后崩掉时重复刷屏。
        self._mark_answered(record_id)
        self.client.send_message(conversation_id, text=reply, client_message_id=f"ycy-{uuid.uuid4().hex[:24]}")
        return True

    def reply_for(self, *, conversation_id: str, speaker_id: str, text: str, record_id: str) -> str:
        if record_id in self.answered:
            return ""
        if is_chitchat(text):
            _log_operation(action="agent.chat.reply", target_type="c19_conversation", target_id=conversation_id, result="success", details={"record_id": record_id, "speaker_id": speaker_id, "kind": "chitchat"})
            return REPLY_CHITCHAT

        db = self.session_factory()
        try:
            verdict = self.classify(db, text)
        finally:
            db.close()

        details: dict[str, Any] = {
            "record_id": record_id,
            "speaker_id": speaker_id,
            "status": verdict.status,
            "shortlist_size": verdict.shortlist_size,
            "keywords_en": list(verdict.hint.keywords_en) if verdict.hint else [],
        }
        if verdict.status == "ok" and verdict.chosen is not None:
            details.update({"chosen_id": verdict.chosen.id, "chosen_name": verdict.chosen.name, "confidence": verdict.confidence})
            _log_operation(action="agent.category.answer", target_type="c19_conversation", target_id=conversation_id, result="success", details=details)
        elif verdict.status == "offline":
            details["error"] = verdict.error
            _log_operation(action="agent.category.answer", target_type="c19_conversation", target_id=conversation_id, result="failure", error_code="AGENT_AI_UNAVAILABLE", details=details)
        else:
            _log_operation(action="agent.category.none", target_type="c19_conversation", target_id=conversation_id, result="success", details=details)
        return render_verdict(verdict, record_id=record_id)

    def _mark_answered(self, record_id: str) -> None:
        self.answered.append(record_id)
        if len(self.answered) > MAX_ANSWERED_KEEP:
            self.answered = self.answered[-MAX_ANSWERED_KEEP:]
        self.store.save_state("answered", self.answered)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    worker = YinchengyueWorker()
    worker.run_forever(should_stop=lambda: not _RUNNING)
    _LOGGER.info("殷承岳下线")


if __name__ == "__main__":
    main()
