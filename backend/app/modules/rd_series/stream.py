"""RD 系列 · 一条 SSE 喂完远程桌面的全部实时消息。

照主页 `home_card_stream` 的路子:短命流(到期即关,客户端 `retry` 重连并顺带复验
会话)、每轮 `validate_session`、任何异常直接关流。

**轮询是自适应的**,这是和主页流最大的不同。主页 3 秒一轮就够,但 WebRTC 握手要
来回递好几轮 offer/answer/ice,3 秒一轮能把建连拖到半分钟。所以:手上没有活会话时
慢轮(省数据库),一旦有会话在建连或进行中就切到快轮(400ms)。会话结束自动降回去。

一条流同时喂三种消息:
- ``request``  有人要控制我的机器(被控端据此弹原生框)
- ``session``  我参与的某个会话状态变了(被同意/被拒绝/被挂断)
- ``signal``   对方递过来的 WebRTC 信封
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from time import monotonic

from fastapi import Request

from ...api.deps import get_audit_context
from ...db.session import managed_read_session
from ...services.auth_service import InvalidSessionError, validate_session
from . import service
from .models import STATE_ACTIVE, STATE_CONSENTED, STATE_REQUESTED

# 手上没有活会话:慢轮,只是在等「有人要连我」
IDLE_POLL_SECONDS = 2.0
# 有会话在建连/进行中:快轮,握手要靠它来回递
BUSY_POLL_SECONDS = 0.4
# 流的寿命。到点关掉让客户端重连,顺带复验会话是不是还有效
STREAM_LIFETIME_SECONDS = 55.0


def _frame(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _session_payload(session) -> dict[str, object]:
    return {
        "id": str(session.id),
        "device_id": str(session.device_id),
        "device_name": session.device.name if session.device else None,
        "controller_user_id": session.controller_user_id,
        "state": session.state,
        "consent_mode": session.consent_mode,
    }


async def rd_stream(
    *, request: Request, session_id: str, actor_user_id: int
) -> AsyncIterator[str]:
    deadline = monotonic() + STREAM_LIFETIME_SECONDS
    # 已经推过的:会话按「id → 上次推的状态」,信令按游标
    seen_states: dict[str, str] = {}
    signal_cursor: dict[str, int] = {}
    announced_requests: set[str] = set()
    poll = IDLE_POLL_SECONDS

    yield "retry: 2000\n\n"
    while monotonic() < deadline:
        await asyncio.sleep(poll)
        if await request.is_disconnected():
            return
        try:
            with managed_read_session() as live_db:
                current = validate_session(
                    live_db, session_id=session_id, audit=get_audit_context(request)
                )
                user = current.user
                if int(user.id) != actor_user_id:
                    return

                busy = False

                # 1) 要在我的机器上弹框的请求
                for pending in service.pending_requests_for_owner(live_db, user=user):
                    busy = True
                    key = str(pending.id)
                    if key not in announced_requests:
                        announced_requests.add(key)
                        yield _frame("request", _session_payload(pending))

                # 2) 我参与的会话的状态变化 + 3) 对方递来的信令
                for sess in service.sessions_for_party(live_db, user=user):
                    key = str(sess.id)
                    if sess.state in (STATE_REQUESTED, STATE_CONSENTED, STATE_ACTIVE):
                        busy = True
                    if seen_states.get(key) != sess.state:
                        seen_states[key] = sess.state
                        yield _frame("session", _session_payload(sess))
                    if sess.state in (STATE_CONSENTED, STATE_ACTIVE):
                        after = signal_cursor.get(key, 0)
                        for sig in service.pull_signals(
                            live_db, user=user, session_id=sess.id, after_id=after
                        ):
                            signal_cursor[key] = sig.id
                            yield _frame(
                                "signal",
                                {
                                    "session_id": key,
                                    "id": sig.id,
                                    "kind": sig.kind,
                                    "payload": sig.payload,
                                },
                            )

                poll = BUSY_POLL_SECONDS if busy else IDLE_POLL_SECONDS
        except InvalidSessionError:
            return
        except Exception:
            # 流里出任何岔子都直接关,让客户端重连重来,绝不把半截状态喂下去
            return
