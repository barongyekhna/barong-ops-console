"""amz-agents-worker:一个进程、四个 C19 身份。

    python -m backend.app.modules.amz_series.agents.worker_main

每名员工各自:登录 → 从「现在」订阅事件 → 有人说话就取快照、取记忆 → 一次 flash(人设焊死)→ 回消息;
每 patrol 节拍看一眼自己名下 severity=bad 的建议,按四条规矩最多开口一次。

护栏全在代码里:
- 说话人不是 owner、也没有任何店铺授权 → 只回一句「我只跟被授权的人聊店铺」,快照一个字不给;
- 影子期没有任何写端点:C19Client 只有听和说两根指头,数据库这边只读;
- 一个身份登不上(密码没配 / 后端没起)不拖累其余三位,各自退避;
- 心跳按身份分开:amz-agents-worker:{username},一轮走完没抛异常才写。
"""

from __future__ import annotations

import logging
import signal
import time
import uuid
from dataclasses import dataclass, field
from types import FrameType
from typing import Any, Callable

import httpx

from ....db.session import SessionLocal
from ....models.user import User
from ....repositories.operation_logs import create_operation_log
from ...agent_series.common.c19_client import C19Client, ConsoleAuthError
from ...agent_series.common.memory_store import MemoryStore
from ..catalog import AGENT_HOME_COMPANY, store_spec
from ..constants import AGENTS_WORKER_NAME, EMPLOYEE_PASSWORD_ENVS, EMPLOYEE_USERNAMES, EMPLOYEES, MODULE_KEY
from ..persona import enforce_style, persona_for
from ..suggestions import list_suggestions, suggestion_view
from . import brain, speech
from .config import (
    ACTOR_TYPE,
    MESSAGE_LOOKBACK,
    heartbeat_interval_seconds,
    patrol_enabled,
    patrol_seconds,
    poll_seconds,
    report_to_user_ids,
)
from .context import employee_snapshot, speaker_store_codes

_LOGGER = logging.getLogger("amz-agents-worker")
_RUNNING = True
MAX_LOGIN_BACKOFF = 60.0

REPLY_NOT_GRANTED = "{address},亚马逊店铺的数据我只跟 owner 和拿到店铺授权的人聊。你需要的话,请老板在「亚马逊 → 管理」里给你开授权,我再详细说。"
REPLY_OFFLINE = "{address},我这边刚才没连上模型,这条先没答上来。你再说一次试试;要是一直这样,不用管我,回头我自己会好。"


def _handle_stop(signum: int, frame: FrameType | None) -> None:
    del signum, frame
    global _RUNNING
    _RUNNING = False
    _LOGGER.info("收到停止信号,处理完当前这轮就退出")


def _sleep_interruptible(seconds: float, should_stop: Callable[[], bool]) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not should_stop():
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


def _heartbeat(username: str, *, success: bool, error: str = "") -> None:
    """按身份记心跳。任何异常都不许冒出去——监控不该拖垮被监控的人。"""
    try:
        from ....services.worker_heartbeat import record_failure, record_success  # noqa: PLC0415

        with SessionLocal() as db:
            name = f"{AGENTS_WORKER_NAME}:{username}"
            if success:
                record_success(db, worker_name=name, module_key=MODULE_KEY, expected_interval_seconds=heartbeat_interval_seconds())
            else:
                record_failure(db, worker_name=name, module_key=MODULE_KEY, error=error, expected_interval_seconds=heartbeat_interval_seconds())
    except Exception:  # noqa: BLE001
        pass


def _log_operation(*, actor_id: str, action: str, target_type: str, target_id: str, result: str, details: dict[str, Any] | None = None, error_code: str | None = None) -> None:
    db = SessionLocal()
    try:
        create_operation_log(db, actor_type=ACTOR_TYPE, actor_id=actor_id, action=action, target_type=target_type, target_id=target_id, result=result, error_code=error_code, details=details)
        db.commit()
    except Exception:  # noqa: BLE001
        _LOGGER.exception("写 operation_log 失败")
        db.rollback()
    finally:
        db.close()


def _styled(employee: str, template: str) -> str:
    return enforce_style(employee, template.format(address=persona_for(employee).address))


@dataclass
class EmployeeRuntime:
    """一个身份的全部运行态。四份互不共享。"""

    employee: str
    client: Any
    store: MemoryStore
    cursor: str | None = None
    online: bool = False
    backoff: float = 2.0
    retry_at: float = 0.0
    next_patrol: float = field(default_factory=lambda: time.monotonic() + patrol_seconds())

    @property
    def username(self) -> str:
        return EMPLOYEE_USERNAMES[self.employee]

    @property
    def actor_id(self) -> str:
        return f"amz.{self.username}"


def default_runtimes() -> list[EmployeeRuntime]:
    out: list[EmployeeRuntime] = []
    for employee in EMPLOYEES:
        username = EMPLOYEE_USERNAMES[employee]
        out.append(
            EmployeeRuntime(
                employee=employee,
                client=C19Client(username=username, password_env=EMPLOYEE_PASSWORD_ENVS[employee]),
                store=MemoryStore(username=username, index_title=f"{persona_for(employee).name}的记忆"),
            )
        )
    return out


class AmzAgentsWorker:
    def __init__(
        self,
        *,
        runtimes: list[EmployeeRuntime] | None = None,
        session_factory=None,
        think=None,
        snapshot=None,
        clock: Callable[[], float] | None = None,
        today: Callable[[], str] | None = None,
        hour: Callable[[], int] | None = None,
    ) -> None:
        self.runtimes = runtimes or default_runtimes()
        self.session_factory = session_factory or SessionLocal
        self.think = think or brain.think
        self.snapshot = snapshot or employee_snapshot
        self.clock = clock or time.monotonic
        self.today = today or speech.local_today
        self.hour = hour or speech.local_hour

    # ---------- 上线(各自退避,不互相拖累) ----------

    def connect(self, rt: EmployeeRuntime) -> bool:
        if rt.online:
            return True
        if self.clock() < rt.retry_at:
            return False
        try:
            rt.client.login()
            rt.cursor = rt.client.event_tail()
        except (ConsoleAuthError, httpx.HTTPError) as exc:
            _LOGGER.warning("%s 上线失败(%s),%.0f 秒后重试", rt.username, exc, rt.backoff)
            rt.retry_at = self.clock() + rt.backoff
            rt.backoff = min(rt.backoff * 2, MAX_LOGIN_BACKOFF)
            _heartbeat(rt.username, success=False, error=f"登不上控制台: {exc!r}"[:500])
            return False
        rt.online = True
        rt.backoff = 2.0
        _LOGGER.info("%s(%s)上线,从游标 %s 开始听", persona_for(rt.employee).name, rt.username, rt.cursor)
        return True

    # ---------- 一轮 ----------

    def run_once(self, rt: EmployeeRuntime) -> bool:
        page = rt.client.events(cursor=rt.cursor)
        events = page.get("events") or []
        if page.get("next_cursor"):
            rt.cursor = page["next_cursor"]
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
                if self.handle_conversation(rt, cid):
                    handled = True
            except Exception as exc:  # noqa: BLE001
                _LOGGER.exception("%s 处理会话 %s 失败", rt.username, cid)
                _log_operation(actor_id=rt.actor_id, action="agent.chat.reply", target_type="c19_conversation", target_id=cid, result="failure", error_code="AGENT_REPLY_FAILED", details={"error": str(exc)[:500]})
        return handled

    def handle_conversation(self, rt: EmployeeRuntime, conversation_id: str) -> bool:
        records = rt.client.messages(conversation_id, limit=MESSAGE_LOOKBACK)
        if not records:
            return False
        my_id = str(rt.client.user_id)
        incoming = [r for r in records if str(r.get("sender_user_id")) != my_id and r.get("content_type") in {"text", "emoji"}]
        if not incoming:
            return False  # 只有自己的消息 = 自己发言的回声,接话就是自问自答死循环
        latest = max(incoming, key=lambda r: int(r.get("sequence") or 0))
        my_last = max((int(r.get("sequence") or 0) for r in records if str(r.get("sender_user_id")) == my_id), default=0)
        if int(latest.get("sequence") or 0) <= my_last:
            return False
        text = str(latest.get("content") or "").strip()
        if not text:
            return False
        speaker_id = str(latest.get("sender_user_id"))
        recent_turns = [
            {"role": "assistant" if str(r.get("sender_user_id")) == my_id else "user", "content": str(r.get("content") or "")[:1000]}
            for r in sorted(records, key=lambda item: int(item.get("sequence") or 0))
            if r.get("content_type") in {"text", "emoji"}
        ][:-1]
        reply = self.reply_for(rt, speaker_id=speaker_id, text=text, recent_turns=recent_turns)
        rt.client.send_message(conversation_id, text=reply["reply"], client_message_id=f"amz-{uuid.uuid4().hex[:24]}")
        self._persist(rt, speaker_id=speaker_id, reply=reply)
        _log_operation(actor_id=rt.actor_id, action="agent.chat.reply", target_type="c19_conversation", target_id=conversation_id, result="success", details={"speaker_user_id": speaker_id, "reply_chars": len(reply["reply"]), "gated": bool(reply.get("gated"))})
        return True

    def reply_for(self, rt: EmployeeRuntime, *, speaker_id: str, text: str, recent_turns: list[dict[str, str]] | None = None) -> dict[str, Any]:
        db = self.session_factory()
        try:
            speaker = db.get(User, int(speaker_id)) if speaker_id.isdigit() else None
            store_codes = speaker_store_codes(db, speaker)
            if store_codes is not None and not store_codes:
                # 没授权:一个数字都不给,连快照都不取。
                return {"reply": _styled(rt.employee, REPLY_NOT_GRANTED), "note": "", "mute_days": None, "gated": True}
            snapshot = self.snapshot(db, employee=rt.employee, store_codes=store_codes)
        finally:
            db.close()
        speaker_name = getattr(speaker, "username", None) or f"用户{speaker_id}"
        messages = brain.build_chat_messages(
            rt.employee,
            user_message=text,
            speaker_name=str(speaker_name),
            snapshot=snapshot,
            memory_digest=rt.store.load_index(),
            conversation_notes=rt.store.load_conversation_notes(speaker_id),
            recent_turns=recent_turns or [],
        )
        try:
            return self.think(rt.employee, messages, org_id=AGENT_HOME_COMPANY.org_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("%s 模型调用失败", rt.username)
            _log_operation(actor_id=rt.actor_id, action="agent.chat.brain", target_type="user", target_id=speaker_id, result="failure", error_code="AGENT_AI_UNAVAILABLE", details={"error": str(exc)[:300]})
            return {"reply": _styled(rt.employee, REPLY_OFFLINE), "note": "", "mute_days": None, "error": str(exc)[:200]}

    def _persist(self, rt: EmployeeRuntime, *, speaker_id: str, reply: dict[str, Any]) -> None:
        mute_days = reply.get("mute_days")
        # 「这两天别找我」只有收主动消息的人说了才算,别的同事说不算。
        if isinstance(mute_days, int) and speaker_id in report_to_user_ids():
            state = speech.normalize_state(rt.store.load_state(speech.STATE_NAME, None))
            until = speech.set_mute(state, mute_days, today=self.today())
            rt.store.save_state(speech.STATE_NAME, state)
            _LOGGER.info("%s 进入静默期,到 %s 为止", rt.username, until)
        note = reply.get("note")
        if isinstance(note, str) and note.strip():
            try:
                rt.store.append_conversation_note(speaker_id, note)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("写对话笔记失败")

    # ---------- 主动开口 ----------

    def urgent_suggestions(self, rt: EmployeeRuntime) -> list[dict[str, Any]]:
        db = self.session_factory()
        try:
            rows = list_suggestions(db, store_codes=None, employee=rt.employee, status="open", limit=200)
            return [suggestion_view(r) for r in rows if r.severity in speech.SPEAK_SEVERITIES]
        finally:
            db.close()

    def patrol_once(self, rt: EmployeeRuntime) -> bool:
        state = speech.normalize_state(rt.store.load_state(speech.STATE_NAME, None))
        today = self.today()
        if not speech.may_speak(state, today=today, hour=self.hour()):
            return False  # 说过了 / 静默期 / 深夜
        finding = speech.pick_one(self.urgent_suggestions(rt), state)
        if finding is None:
            return False
        spec = store_spec(str(finding.get("store_code") or ""))
        org_id = spec.company.org_id if spec is not None else AGENT_HOME_COMPANY.org_id
        messages = brain.build_speak_messages(rt.employee, suggestion=finding, memory_digest=rt.store.load_index())
        try:
            reply = self.think(rt.employee, messages, org_id=org_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("%s 主动开口时模型没接通,这次不说: %s", rt.username, exc)
            return False
        sent_to: list[str] = []
        for user_id in report_to_user_ids():
            cid = rt.client.direct_conversation_with(user_id)
            if not cid:
                continue
            rt.client.send_message(cid, text=reply["reply"], client_message_id=f"amz-p-{uuid.uuid4().hex[:22]}")
            sent_to.append(user_id)
        if not sent_to:
            return False
        speech.mark_spoke(state, str(finding["id"]), today=today)
        rt.store.save_state(speech.STATE_NAME, state)
        _log_operation(actor_id=rt.actor_id, action="agent.patrol.report", target_type="amz_suggestion", target_id=str(finding["id"]), result="success", details={"store_code": finding.get("store_code"), "sent_to": sent_to})
        return True

    # ---------- 主循环 ----------

    def tick(self, rt: EmployeeRuntime) -> bool:
        """一个身份走一轮。返回是否忙(处理了消息)。"""
        if not self.connect(rt):
            return False
        try:
            busy = self.run_once(rt)
        except ConsoleAuthError as exc:
            rt.online = False
            _heartbeat(rt.username, success=False, error=f"会话失效: {exc!r}"[:500])
            return False
        except httpx.HTTPError as exc:
            _LOGGER.warning("%s 控制台暂时够不着: %s", rt.username, exc)
            _heartbeat(rt.username, success=False, error=f"控制台够不着: {exc!r}"[:500])
            return False
        _heartbeat(rt.username, success=True)
        if patrol_enabled() and self.clock() >= rt.next_patrol:
            rt.next_patrol = self.clock() + patrol_seconds()
            try:
                self.patrol_once(rt)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("%s 巡检失败(不影响聊天)", rt.username)
        return busy

    def run_forever(self, *, should_stop: Callable[[], bool]) -> None:
        interval = poll_seconds()
        while not should_stop():
            busy = False
            for rt in self.runtimes:
                if self.tick(rt):
                    busy = True
            if not busy:
                _sleep_interruptible(interval, should_stop)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    AmzAgentsWorker().run_forever(should_stop=lambda: not _RUNNING)
    _LOGGER.info("四名员工下线")


if __name__ == "__main__":
    main()
