"""白苏婉的常驻进程(``baisuwan-worker`` 容器)。

    python -m backend.app.modules.agent_series.baisuwan.worker_main

登录控制台 → 从「现在」开始订阅 C19 事件 → 有人跟她说话就取正文、取只读
快照、取记忆 → 跑一次 flash → 回消息 → 该记的记下来。

C19 没有推送钩子,只能轮询事件游标(GET /events)。间隔默认 3 秒,聊天体感够用。
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
from . import memory, patrol
from .brain import build_messages, build_patrol_messages, think
from .console_client import ConsoleAuthError, ConsoleClient
from .constants import (
    ACTOR_TYPE,
    AGENT_ID,
    patrol_enabled,
    patrol_seconds,
    poll_seconds,
    report_to_user_id,
)

_RUNNING = True
_LOGGER = logging.getLogger("baisuwan-worker")

MAX_LOGIN_BACKOFF = 60.0
MESSAGE_LOOKBACK = 20


def _handle_stop(signum: int, frame: FrameType | None) -> None:
    del signum, frame
    global _RUNNING
    _RUNNING = False
    _LOGGER.info("收到停止信号,处理完当前这轮就退出")


def _log_operation(
    *,
    action: str,
    target_id: str,
    result: str,
    details: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> None:
    """她干的每件事都留痕,actor_type=agent —— 跟真人的操作分得清清楚楚。"""
    db = SessionLocal()
    try:
        create_operation_log(
            db,
            actor_type=ACTOR_TYPE,
            actor_id=AGENT_ID,
            action=action,
            target_type="c19_conversation",
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


class BaisuwanWorker:
    def __init__(self) -> None:
        self.client = ConsoleClient()
        self.cursor: str | None = None
        # 冷启动不立刻巡检:刚上线时她还没有任何"上次是什么样"的参照,
        # 而且重启不该变成一条主动消息。等第一个整节拍再说。
        self.next_patrol = time.monotonic() + patrol_seconds()

    # ---------- 启动 ----------

    def connect(self, *, should_stop) -> bool:
        """登录并把游标对到「现在」。登不上就退避重试,不放弃。"""
        backoff = 2.0
        while not should_stop():
            try:
                self.client.login()
                self.cursor = self.client.event_tail()
                _LOGGER.info("白苏婉上线,游标=%s", self.cursor)
                return True
            except (ConsoleAuthError, httpx.HTTPError) as exc:
                _LOGGER.warning("上线失败(%s),%.0f 秒后重试", exc, backoff)
                _sleep_interruptible(backoff, should_stop)
                backoff = min(backoff * 2, MAX_LOGIN_BACKOFF)
        return False

    # ---------- 一轮 ----------

    def run_once(self) -> bool:
        """拉一批事件并回复。返回是否处理了消息。"""
        page = self.client.events(cursor=self.cursor)
        events = page.get("events") or []
        next_cursor = page.get("next_cursor")
        if next_cursor:
            self.cursor = next_cursor
        if not events:
            return False

        # 同一个会话里连来几条,只回一次(把前几条当上下文),
        # 免得对方一口气打三行字、她回三遍。
        conversation_ids: list[str] = []
        for event in events:
            cid = event.get("conversation_id")
            if cid and cid not in conversation_ids:
                conversation_ids.append(cid)

        handled = False
        for conversation_id in conversation_ids:
            try:
                if self._handle_conversation(conversation_id):
                    handled = True
            except Exception as exc:  # noqa: BLE001
                _LOGGER.exception("处理会话 %s 失败", conversation_id)
                _log_operation(
                    action="agent.chat.reply",
                    target_id=conversation_id,
                    result="failure",
                    error_code="AGENT_REPLY_FAILED",
                    details={"error": str(exc)[:500]},
                )
        return handled

    def _handle_conversation(self, conversation_id: str) -> bool:
        records = self.client.messages(conversation_id, limit=MESSAGE_LOOKBACK)
        if not records:
            return False

        my_id = str(self.client.user_id)
        incoming = [
            record
            for record in records
            if str(record.get("sender_user_id")) != my_id
            and record.get("content_type") in {"text", "emoji"}
        ]
        if not incoming:
            # 只有她自己的消息 —— 这轮事件是她自己发言引起的回声,不能接话,
            # 否则就是自问自答的死循环。
            return False

        latest = max(incoming, key=lambda record: int(record.get("sequence") or 0))
        latest_sequence = int(latest.get("sequence") or 0)
        speaker_id = str(latest.get("sender_user_id"))

        # 她自己上一次发言之后对方才说的话,才需要回。避免重启后把历史重放一遍。
        my_last_sequence = max(
            (
                int(record.get("sequence") or 0)
                for record in records
                if str(record.get("sender_user_id")) == my_id
            ),
            default=0,
        )
        if latest_sequence <= my_last_sequence:
            return False

        user_message = str(latest.get("content") or "").strip()
        if not user_message:
            return False

        _LOGGER.info("会话 %s 收到 %s 的消息", conversation_id, speaker_id)
        reply = self._compose_reply(
            conversation_id=conversation_id,
            speaker_id=speaker_id,
            user_message=user_message,
            records=records,
            my_id=my_id,
        )
        self.client.send_message(
            conversation_id,
            text=reply["reply"],
            client_message_id=f"bsw-{uuid.uuid4().hex[:24]}",
        )
        self._persist_memory(speaker_id=speaker_id, reply=reply)
        _log_operation(
            action="agent.chat.reply",
            target_id=conversation_id,
            result="success",
            details={
                "speaker_user_id": speaker_id,
                "reply_chars": len(reply["reply"]),
                "memory_written": bool(reply.get("memory")),
            },
        )
        return True

    def _compose_reply(
        self,
        *,
        conversation_id: str,
        speaker_id: str,
        user_message: str,
        records: list[dict[str, Any]],
        my_id: str,
    ) -> dict[str, Any]:
        snapshot = self.client.content_snapshot()
        recent_turns = [
            {
                "role": "assistant" if str(record.get("sender_user_id")) == my_id else "user",
                "content": str(record.get("content") or "")[:1000],
            }
            for record in sorted(records, key=lambda item: int(item.get("sequence") or 0))
            if record.get("content_type") in {"text", "emoji"}
        ][:-1]

        messages = build_messages(
            user_message=user_message,
            speaker_name=f"用户{speaker_id}",
            snapshot=snapshot,
            memory_digest=memory.load_memory_digest(),
            conversation_notes=memory.load_conversation_notes(speaker_id),
            recent_turns=recent_turns,
        )
        try:
            return think(messages)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("模型调用失败,会话 %s", conversation_id)
            return {
                "reply": (
                    "我这边刚才没连上模型，这条先没答上来。\n\n"
                    "你再说一次试试；要是一直这样，可能是 DeepSeek 那头的问题，"
                    "不用管我，回头我自己会好。"
                ),
                "memory": None,
                "note": "",
                "error": str(exc)[:200],
            }

    def _persist_memory(self, *, speaker_id: str, reply: dict[str, Any]) -> None:
        # 「这两天别找我」——只有老板本人能让她闭嘴。别人说不算,否则任何
        # 同事都能把她对老板的提醒关掉。
        mute_days = reply.get("mute_days")
        if isinstance(mute_days, int) and str(speaker_id) == str(report_to_user_id()):
            state = patrol.load_state()
            until = patrol.set_mute(state, mute_days)
            patrol.save_state(state)
            _LOGGER.info("进入静默期,到 %s 为止", until)

        note = reply.get("note")
        if isinstance(note, str) and note.strip():
            try:
                memory.append_conversation_note(speaker_id, note)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("写对话笔记失败")

        fact = reply.get("memory")
        if not isinstance(fact, dict):
            return
        try:
            path = memory.write_memory(
                slug=str(fact.get("slug") or ""),
                description=str(fact.get("description") or ""),
                body=str(fact.get("body") or ""),
            )
            _LOGGER.info("写下一条记忆: %s", path.name)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("写记忆失败")

    # ---------- 主动巡检 ----------

    def patrol_once(self) -> bool:
        """巡一圈。够格打断老板就说一句,不够格就什么都不做。

        四道闸依次挡:静默期/一天一条 → 有没有发现 → 报过没有 → 找不找得到会话。
        任何一道没过就安静退出 —— 安静是默认值,开口才是例外。
        """
        state = patrol.load_state()
        if not patrol.may_speak(state):
            return False

        findings = patrol.collect_findings(self.client)
        finding = patrol.pick_one(findings, state)
        if finding is None:
            return False

        conversation_id = self.client.direct_conversation_with(report_to_user_id())
        if not conversation_id:
            _LOGGER.warning("找不到跟 %s 的会话,这条先不发", report_to_user_id())
            return False

        _LOGGER.info("主动开口: %s", finding.headline)
        try:
            reply = think(
                build_patrol_messages(
                    headline=finding.headline,
                    facts=finding.facts,
                    memory_digest=memory.load_memory_digest(),
                )
            )
        except Exception as exc:  # noqa: BLE001
            # 模型挂了就别发 —— 主动消息不像回话,没人在等,发一句"我出错了"
            # 纯属白打扰。下一轮再试。
            _LOGGER.warning("主动消息生成失败,这轮跳过: %s", exc)
            return False

        self.client.send_message(
            conversation_id,
            text=reply["reply"],
            client_message_id=f"bsw-p-{uuid.uuid4().hex[:22]}",
        )
        patrol.mark_spoke(state, finding)
        patrol.save_state(state)
        _log_operation(
            action="agent.patrol.report",
            target_id=conversation_id,
            result="success",
            details={
                "finding_key": finding.key,
                "kind": finding.kind,
                "headline": finding.headline,
                "fresh_findings": len(findings),
            },
        )
        return True

    # ---------- 主循环 ----------

    def run_forever(self, *, should_stop) -> None:
        if not self.connect(should_stop=should_stop):
            return
        interval = poll_seconds()
        while not should_stop():
            try:
                busy = self.run_once()
            except ConsoleAuthError:
                _LOGGER.warning("会话失效,重新上线")
                if not self.connect(should_stop=should_stop):
                    return
                continue
            except httpx.HTTPError as exc:
                _LOGGER.warning("控制台不通(%s),等一轮再试", exc)
                # 这正是 2026-08-31 那一周的样子：日志里全是这句，
                # 但没有任何人看得到。现在它会落进心跳表。
                _heartbeat(success=False, error=f"控制台不通: {exc!r}")
                busy = False
            except Exception as exc:  # noqa: BLE001
                _LOGGER.exception("这一轮出错,继续下一轮")
                _heartbeat(success=False, error=repr(exc))
                busy = False
            else:
                # 走完一轮没抛异常 = 这一轮干成了。心跳只认「干成」，
                # 不认「进程还在」——后者容器状态已经能回答，而它回答错了一个月。
                _heartbeat(success=True)
            if patrol_enabled() and time.monotonic() >= self.next_patrol:
                self.next_patrol = time.monotonic() + patrol_seconds()
                try:
                    self.patrol_once()
                except ConsoleAuthError:
                    _LOGGER.warning("巡检时会话失效,下一轮重新上线")
                    raise
                except Exception:  # noqa: BLE001
                    # 巡检出错绝不能拖垮聊天 —— 她首要的身份是能说话的人。
                    _LOGGER.exception("巡检出错,继续下一轮")

            if not busy:
                _sleep_interruptible(interval, should_stop)


def _heartbeat(*, success: bool, error: str = "") -> None:
    """记一次业务心跳。**任何异常都不许冒出去** —— 监控不该拖垮被监控的人。

    判据是「这一轮有没有真的干成活」，不是「进程还活着」：
    2026-08-31 体检时容器一直 Up，而她连续七天一件事没干成。
    """
    try:
        from ....db.session import SessionLocal
        from ....services.worker_heartbeat import record_failure, record_success

        with SessionLocal() as db:
            if success:
                record_success(
                    db,
                    worker_name="baisuwan-worker",
                    module_key="agent.baisuwan",
                    expected_interval_seconds=900,
                )
            else:
                record_failure(
                    db,
                    worker_name="baisuwan-worker",
                    module_key="agent.baisuwan",
                    error=error,
                    expected_interval_seconds=900,
                )
    except Exception:  # noqa: BLE001
        pass

def _sleep_interruptible(seconds: float, should_stop) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if should_stop():
            return
        time.sleep(min(0.5, max(0.05, deadline - time.monotonic())))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # 轮询每 3 秒一次,httpx 的 INFO 一天两万八千行,会把她自己的日志全埋掉。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    worker = BaisuwanWorker()
    try:
        worker.run_forever(should_stop=lambda: not _RUNNING)
    finally:
        worker.client.close()
    _LOGGER.info("白苏婉下线")


if __name__ == "__main__":
    main()
