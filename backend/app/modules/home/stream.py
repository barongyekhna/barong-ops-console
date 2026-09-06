"""主页 SSE 流：一条连接喂全部卡片。

照 C19 `_event_page_stream` 的路子：短命流（到期即关，客户端 `retry: 2000` 重连
并顺带复验会话）、每轮 `validate_session`、任何异常直接关流。

浏览器同域并发连接上限 6 条，所以整个主页**只能有这一条**长连接。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from time import monotonic

import anyio
from fastapi import Request

from ...api.deps import get_audit_context
from ...core.config import get_settings
from ...db.session import managed_read_session
from ...services.auth_service import InvalidSessionError, validate_session
from ...services.data_isolation import (
    OrgDataIsolationUserContext,
    org_data_isolation_context,
)
from .context import resolve_home_access
from .registry import STORE_CARDS, HomeCardSpec, allowed, load_cards
from .schemas import HomeCardRead


def card_digest(card: HomeCardRead) -> str:
    """内部卡的 freshness 每轮都变，剔掉再比；外部卡的采集时间在 extra 里照样参与。"""
    payload = card.model_dump_json(exclude={"freshness"})
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _frame(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


async def home_card_stream(
    *,
    request: Request,
    session_id: str,
    actor_user_id: int,
    org_id: str,
    initial_cards: list[HomeCardRead],
    specs: tuple[HomeCardSpec, ...] = STORE_CARDS,
    expected_org_type: str = "store",
) -> AsyncIterator[str]:
    settings = get_settings()
    poll_seconds = float(settings.home_stream_poll_seconds)
    deadline = monotonic() + float(settings.home_stream_lifetime_seconds)
    digests: dict[str, str] = {card.card_id: card_digest(card) for card in initial_cards}
    last_run: dict[str, float] = {spec.card_id: monotonic() for spec in specs}
    audit = get_audit_context(request)

    yield "retry: 2000\n\n"
    while monotonic() < deadline:
        await asyncio.sleep(poll_seconds)
        if await request.is_disconnected():
            return
        try:
            with managed_read_session() as live_db:
                current_session = validate_session(
                    live_db, session_id=session_id, audit=audit
                )
                user = current_session.user
                if int(user.id) != actor_user_id:
                    return
                access = resolve_home_access(live_db, user=user, org_id=org_id)
                if (
                    access is None
                    or access.org_type != expected_org_type
                    or access.workspace_key != org_id
                ):
                    return

                now = monotonic()
                due = [
                    spec
                    for spec in specs
                    if now - last_run[spec.card_id] >= spec.min_refresh_seconds
                ]
                isolation = OrgDataIsolationUserContext(
                    org_id=org_id,
                    user_id=str(user.id),
                    role=str(user.role),
                    source="home_stream",
                    strict=False,
                )

                def _load() -> list[HomeCardRead]:
                    # 中间件之外没有隔离上下文；在线程里自己重建一份。
                    with org_data_isolation_context(isolation):
                        return load_cards(live_db, access=access, user=user, specs=due)

                cards = await anyio.to_thread.run_sync(_load)
                for spec in due:
                    last_run[spec.card_id] = now
        except InvalidSessionError:
            return
        except Exception:  # noqa: BLE001 - 关流让客户端重连，细节不过 SSE
            return

        loaded_ids = {card.card_id for card in cards}
        emitted = False
        for spec in due:
            if spec.card_id in digests and spec.card_id not in loaded_ids and not allowed(spec, access):
                digests.pop(spec.card_id, None)
                yield _frame("card-removed", json.dumps({"card_id": spec.card_id}))
                emitted = True
        for card in cards:
            digest = card_digest(card)
            if digests.get(card.card_id) == digest:
                continue
            digests[card.card_id] = digest
            yield _frame("card", card.model_dump_json())
            emitted = True
        if not emitted:
            yield ": keep-alive\n\n"
