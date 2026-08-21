"""数字员工用的 C19 通讯客户端(参数化版)。

员工的手上只有「听」和「说」两根指头:登录、拉事件、读消息、发消息、找私聊。
没有任何业务写端点——不是靠自觉,是方法根本不存在。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ....core.config import get_settings

_LOGGER = logging.getLogger("agent.c19")

LOGIN_PATH = "/api/public/auth/login"
C19_PREFIX = "/api/app/c19"
MAX_MESSAGE_CHARS = 3900  # MessageCreateRequest 上限 4000


def console_base_url() -> str:
    return os.getenv("AGENT_CONSOLE_BASE_URL", "http://console_backend:8000").rstrip("/")


class ConsoleAuthError(RuntimeError):
    """登录不上 —— 密码错、账号被停用、或者后端没起来。"""


class C19Client:
    def __init__(
        self,
        *,
        username: str,
        password_env: str,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._username = username
        self._password_env = password_env
        self._base_url = (base_url or console_base_url()).rstrip("/")
        self._client = httpx.Client(base_url=self._base_url, timeout=timeout)
        self._cookie_name = get_settings().auth_session_cookie_name
        self.user_id: int | None = None

    def close(self) -> None:
        self._client.close()

    # ---------- 认证 ----------

    def login(self) -> None:
        password = os.getenv(self._password_env) or None
        if not password:
            raise ConsoleAuthError(f"{self._password_env} 未配置,{self._username} 登不上控制台。")
        response = self._client.post(
            LOGIN_PATH, json={"username": self._username, "password": password}
        )
        if response.status_code != 200:
            raise ConsoleAuthError(
                f"登录失败 HTTP {response.status_code}: {response.text[:200]}"
            )
        body = response.json()
        token = body.get("session_token")
        if not token:
            raise ConsoleAuthError("登录响应里没有 session_token。")
        # 生产的会话 cookie 是 Secure 的,worker 走内网明文 http,httpx 会丢掉
        # Set-Cookie —— 所以从响应体拿 token 手工设 cookie。
        self._client.cookies.set(self._cookie_name, token)
        user = body.get("user") or {}
        self.user_id = int(user["id"]) if user.get("id") is not None else None
        _LOGGER.info("%s 已登录控制台 user_id=%s", self._username, self.user_id)

    def _get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        response = self._client.get(path, params=clean)
        if response.status_code == 401:
            _LOGGER.info("会话过期,重新登录")
            self.login()
            response = self._client.get(path, params=clean)
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        response = self._client.post(path, json=body)
        if response.status_code == 401:
            self.login()
            response = self._client.post(path, json=body)
        return response

    # ---------- 听 ----------

    def event_tail(self) -> str | None:
        """冷启动从「现在」开始,不重放历史。"""
        return self._get(f"{C19_PREFIX}/events/tail").get("cursor")

    def events(self, *, cursor: str | None, limit: int = 100) -> dict[str, Any]:
        return self._get(f"{C19_PREFIX}/events", cursor=cursor, limit=limit)

    def messages(self, conversation_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        payload = self._get(f"{C19_PREFIX}/conversations/{conversation_id}/messages", limit=limit)
        return list(payload.get("records") or [])

    # ---------- 说 ----------

    def send_message(self, conversation_id: str, *, text: str, client_message_id: str) -> None:
        body = text.strip() or "（我这边没生成出内容，你再说一次？）"
        if len(body) > MAX_MESSAGE_CHARS:
            body = body[:MAX_MESSAGE_CHARS] + "\n…（太长了先截到这）"
        response = self._post(
            f"{C19_PREFIX}/conversations/{conversation_id}/messages",
            {"client_message_id": client_message_id, "content_type": "text", "content": body},
        )
        response.raise_for_status()

    def direct_conversation_with(self, peer_user_id: str) -> str | None:
        payload = self._get(f"{C19_PREFIX}/conversations", limit=100)
        for row in payload.get("items") or []:
            if not isinstance(row, dict) or row.get("type") != "direct":
                continue
            peer = row.get("direct_peer") or {}
            if str(peer.get("user_id")) == str(peer_user_id):
                return str(row.get("conversation_id"))
        response = self._post(f"{C19_PREFIX}/conversations/direct", {"peer_user_id": int(peer_user_id)})
        if response.status_code >= 400:
            _LOGGER.warning("建私聊会话失败 %s: %s", response.status_code, response.text[:200])
            return None
        return str((response.json() or {}).get("conversation_id") or "") or None
