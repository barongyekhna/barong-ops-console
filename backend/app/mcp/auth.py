"""MCP 服务通用鉴权(模块无关):Bearer 个人钥匙 → 真人 User。

下一个模块开 MCP 口子直接复用:
    app = TokenGuard(mcp_app, open_prefixes=(...))
    ... 工具体里 ``user_id = actor_user_id(ctx)`` 取当前人,再按本模块权限放行。

为什么不用 ContextVar:FastMCP 无状态模式把工具协程 spawn 在 lifespan 的 task
group 里(streamable_http_manager),外层中间件设的 ContextVar 工具体看不见;
但 transport 用同一个 ASGI ``scope`` 造 Starlette ``Request``,所以把用户 id
放进 ``scope["state"]``,工具体经 ``ctx.request_context.request.state`` 就能读到。
"""

from __future__ import annotations

from typing import Any

import anyio
from starlette.responses import JSONResponse

from ..db.session import SessionLocal
from ..services.mcp_token_service import resolve_user_by_token

_BEARER_PREFIX = b"bearer "
STATE_USER_ID = "mcp_user_id"
STATE_USERNAME = "mcp_username"


def _client_ip(scope: dict[str, Any]) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == b"x-forwarded-for":
            return value.decode("latin-1").split(",")[0].strip() or None
    client = scope.get("client")
    return str(client[0]) if client else None


def _presented_token(scope: dict[str, Any]) -> str:
    for key, value in scope.get("headers") or []:
        if key == b"authorization":
            if value[:7].lower() == _BEARER_PREFIX:
                return value[len(_BEARER_PREFIX):].strip().decode("latin-1")
            return ""
    return ""


class TokenGuard:
    """除 ``open_prefixes`` 外一律要 ``Authorization: Bearer <个人钥匙>``;认不出 → 401。

    每次请求查库(钥匙停用/账号停用即刻生效)。认出来的 user_id 放进
    ``scope["state"]``,交给下游。
    """

    def __init__(self, app: Any, *, open_prefixes: tuple[str, ...]) -> None:
        self._app = app
        self._open_prefixes = open_prefixes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        if any(path.startswith(prefix) for prefix in self._open_prefixes):
            await self._app(scope, receive, send)
            return
        presented = _presented_token(scope)
        resolved: tuple[int, str] | None = None
        if presented:
            ip = _client_ip(scope)

            def _lookup() -> tuple[int, str] | None:
                with SessionLocal() as db:
                    user = resolve_user_by_token(db, presented, ip_address=ip)
                    if user is None:
                        return None
                    db.commit()  # last_used 节流写
                    return int(user.id), str(user.username)

            resolved = await anyio.to_thread.run_sync(_lookup)
        if resolved is None:
            response = JSONResponse(
                {
                    "error": "unauthorized",
                    "message": "MCP 个人钥匙缺失、错误或已停用;请到控制台「设置」重置后重新接入。",
                },
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        state[STATE_USER_ID] = resolved[0]
        state[STATE_USERNAME] = resolved[1]
        await self._app(scope, receive, send)


def actor_user_id(ctx: Any) -> int:
    """从 FastMCP ``Context`` 取 TokenGuard 认出来的用户 id;取不到 = 编程错误,fail-closed。"""
    try:
        request = ctx.request_context.request
        value = getattr(request.state, STATE_USER_ID)
    except Exception as exc:  # noqa: BLE001
        raise PermissionError("MCP request carries no authenticated user") from exc
    if value is None:
        raise PermissionError("MCP request carries no authenticated user")
    return int(value)


__all__ = ["STATE_USER_ID", "STATE_USERNAME", "TokenGuard", "actor_user_id"]
