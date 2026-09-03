"""白苏婉调控制台的 HTTP 客户端。

**这个类就是她的手,而这只手上只有只读的指头。**

除了 login 和「在 C19 里说话」之外,这里没有实现任何一个写端点 —— 不是靠
她自觉不点,是这些方法根本不存在。加上她的权限只有 *.read(调写端点会被
_require_geo_permission 403),两道护栏各自独立成立。

她走 HTTP 而不是直接连库,是刻意的:这样所有调用都过一遍权限链,以后给她
开绿灯动作时,护栏自动生效,不用重新发明。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ....core.config import get_settings
from .constants import AGENT_USERNAME, agent_password, console_base_url

_LOGGER = logging.getLogger("baisuwan.client")

LOGIN_PATH = "/api/public/auth/login"
C19_PREFIX = "/api/app/c19"
GEO_PREFIX = "/api/app/geo"
SEO_PREFIX = "/api/app/seo"

# 每类快照最多带回多少条。给模型看的是「现在什么状态」,不是全量导出。
SNAPSHOT_LIMIT = 20


class ConsoleAuthError(RuntimeError):
    """登录不上 —— 密码错、账号被停用、或者后端没起来。"""


class ConsoleClient:
    def __init__(self, *, base_url: str | None = None, timeout: float = 30.0) -> None:
        self._base_url = (base_url or console_base_url()).rstrip("/")
        self._client = httpx.Client(base_url=self._base_url, timeout=timeout)
        self._cookie_name = get_settings().auth_session_cookie_name
        self.user_id: int | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ConsoleClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ---------- 认证 ----------

    def login(self) -> None:
        password = agent_password()
        if not password:
            raise ConsoleAuthError("BAISUWAN_PASSWORD 未配置,白苏婉登不上控制台。")

        response = self._client.post(
            LOGIN_PATH,
            json={"username": AGENT_USERNAME, "password": password},
        )
        if response.status_code != 200:
            raise ConsoleAuthError(
                f"登录失败 HTTP {response.status_code}: {response.text[:200]}"
            )
        body = response.json()
        token = body.get("session_token")
        if not token:
            raise ConsoleAuthError("登录响应里没有 session_token。")

        # 从响应体拿 token 手工设 cookie,而不是靠 Set-Cookie 自动落袋:
        # 生产的会话 cookie 是 Secure 的,而 worker 走内网明文 http,
        # httpx 会直接丢掉那张 cookie,于是每个请求都 401。
        self._client.cookies.set(self._cookie_name, token)
        user = body.get("user") or {}
        self.user_id = int(user["id"]) if user.get("id") is not None else None
        _LOGGER.info("已登录控制台 user_id=%s", self.user_id)

    def _get(self, path: str, **params: Any) -> Any:
        response = self._client.get(path, params={k: v for k, v in params.items() if v is not None})
        if response.status_code == 401:
            _LOGGER.info("会话过期,重新登录")
            self.login()
            response = self._client.get(
                path, params={k: v for k, v in params.items() if v is not None}
            )
        response.raise_for_status()
        return response.json()

    # ---------- C19:听 ----------

    def event_tail(self) -> str | None:
        """当前事件流的尾部游标 —— 冷启动从「现在」开始,不重放历史。"""
        return self._get(f"{C19_PREFIX}/events/tail").get("cursor")

    def events(self, *, cursor: str | None, limit: int = 100) -> dict[str, Any]:
        return self._get(f"{C19_PREFIX}/events", cursor=cursor, limit=limit)

    def messages(self, conversation_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        payload = self._get(
            f"{C19_PREFIX}/conversations/{conversation_id}/messages", limit=limit
        )
        # ChatRecordPageRead 的字段是 records,不是 items。
        return list(payload.get("records") or [])

    # ---------- C19:说(她唯一的写操作) ----------

    def send_message(self, conversation_id: str, *, text: str, client_message_id: str) -> None:
        # content 上限 4000 字符(MessageCreateRequest),超了整条请求会被拒,
        # 与其让她的回答凭空消失,不如截断后明说。
        body = text.strip() or "（我这边没生成出内容，你再说一次？）"
        if len(body) > 3900:
            body = body[:3900] + "\n…（后面还有，太长了先截到这）"

        response = self._client.post(
            f"{C19_PREFIX}/conversations/{conversation_id}/messages",
            json={
                "client_message_id": client_message_id,
                "content_type": "text",
                "content": body,
            },
        )
        if response.status_code == 401:
            self.login()
            response = self._client.post(
                f"{C19_PREFIX}/conversations/{conversation_id}/messages",
                json={
                    "client_message_id": client_message_id,
                    "content_type": "text",
                    "content": body,
                },
            )
        response.raise_for_status()

    def direct_conversation_with(self, peer_user_id: str) -> str | None:
        """找到跟某个人的私聊会话,主动消息发到这里。

        先找现成的;实在没有才建一个。建会话确实是个写操作,但它只是「开一个
        对话框」—— 她的手上仍然只有说话这一个动作,碰不到任何业务数据。
        """
        payload = self._get(f"{C19_PREFIX}/conversations", limit=100)
        for row in payload.get("items") or []:
            if not isinstance(row, dict) or row.get("type") != "direct":
                continue
            peer = row.get("direct_peer") or {}
            if str(peer.get("user_id")) == str(peer_user_id):
                return str(row.get("conversation_id"))

        response = self._client.post(
            f"{C19_PREFIX}/conversations/direct",
            json={"peer_user_id": int(peer_user_id)},
        )
        if response.status_code == 401:
            self.login()
            response = self._client.post(
                f"{C19_PREFIX}/conversations/direct",
                json={"peer_user_id": int(peer_user_id)},
            )
        if response.status_code >= 400:
            _LOGGER.warning("建私聊会话失败 %s: %s", response.status_code, response.text[:200])
            return None
        return str((response.json() or {}).get("conversation_id") or "") or None

    # ---------- 巡检用的只读接口 ----------

    def clusters(self) -> dict[str, Any]:
        return _disambiguate("geo_clusters", self._get(f"{GEO_PREFIX}/clusters"))

    def cluster_items(self, cluster_id: str) -> dict[str, Any]:
        return self._get(f"{GEO_PREFIX}/clusters/{cluster_id}")

    def cluster_jobs(self, cluster_id: str) -> dict[str, Any]:
        return self._get(f"{GEO_PREFIX}/clusters/{cluster_id}/jobs")

    def cluster_publishes(self, cluster_id: str) -> dict[str, Any]:
        return self._get(f"{GEO_PREFIX}/clusters/{cluster_id}/publishes")

    def seo_items(self) -> dict[str, Any]:
        return self._get(f"{SEO_PREFIX}/items")

    def monitor(self) -> dict[str, Any]:
        return self._get(f"{GEO_PREFIX}/monitor")

    # ---------- 只读快照 ----------

    def content_snapshot(self) -> dict[str, Any]:
        """一份「内容链现在什么状态」的快照,全部来自 GET。

        任何一块取不到都不该让她哑掉 —— 缺哪块就在快照里标明缺了,
        让她照实说「这部分我看不到」,而不是编一个数字。
        """
        snapshot: dict[str, Any] = {}
        for key, loader in (
            ("geo_clusters", lambda: self._get(f"{GEO_PREFIX}/clusters")),
            ("geo_monitor", lambda: self._get(f"{GEO_PREFIX}/monitor")),
            ("seo_facts", lambda: self._get(f"{SEO_PREFIX}/facts")),
            ("seo_topics", lambda: self._get(f"{SEO_PREFIX}/topics")),
            ("seo_items", lambda: self._get(f"{SEO_PREFIX}/items")),
            ("seo_health", lambda: self._get(f"{SEO_PREFIX}/content-health")),
        ):
            try:
                # 先消歧再裁剪:计数必须按完整列表算,裁剪之后再数就是错的。
                snapshot[key] = _trim(_disambiguate(key, loader()))
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("快照 %s 取不到: %s", key, exc)
                snapshot[key] = {"unavailable": str(exc)[:200]}
        return snapshot

    def cluster_detail(self, cluster_id: str) -> dict[str, Any]:
        detail: dict[str, Any] = {}
        for key, path in (
            ("jobs", f"{GEO_PREFIX}/clusters/{cluster_id}/jobs"),
            ("publishes", f"{GEO_PREFIX}/clusters/{cluster_id}/publishes"),
            ("critique", f"{GEO_PREFIX}/clusters/{cluster_id}/critique-summary"),
        ):
            try:
                detail[key] = _trim(self._get(path))
            except Exception as exc:  # noqa: BLE001
                detail[key] = {"unavailable": str(exc)[:200]}
        return detail


def _disambiguate(key: str, payload: Any) -> Any:
    """把原始 API 里「光看名字猜不出在数什么」的字段改成自解释的名字。

    2026-08-21 实际踩过:``/geo/clusters`` 每个簇带一个 ``item_count``,那是
    **内容条目**数;她读成了产品数,于是把「2 个产品」说成「7 个产品」——
    数字来自真实字段,只是字段名骗了她。

    治本是让名字自己说清楚,而不是在提示词里补一句「注意 item_count 是……」:
    提示词是软的,模型可以忽略;名字是硬的,读到什么就是什么。顺手把计数直接
    算好给她,省掉「自己数一遍列表」这一步 —— 少一步就少一个出错的地方。
    """
    if not isinstance(payload, dict):
        return payload

    if key == "geo_clusters":
        clusters = payload.get("clusters")
        if isinstance(clusters, list):
            payload = dict(payload)
            payload["clusters"] = [
                _annotate_cluster(cluster) if isinstance(cluster, dict) else cluster
                for cluster in clusters
            ]
    elif key == "seo_health":
        if "count" in payload:
            payload = dict(payload)
            payload["stranded_count"] = payload.pop("count")
    return payload


def _annotate_cluster(cluster: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(cluster)
    if "item_count" in annotated:
        annotated["content_item_count"] = annotated.pop("item_count")
    for source, target in (
        ("product_ids", "product_count"),
        ("pending_product_ids", "pending_product_count"),
        ("picked_questions", "picked_question_count"),
    ):
        value = annotated.get(source)
        if isinstance(value, list):
            annotated[target] = len(value)
    return annotated


def _trim(payload: Any) -> Any:
    """把列表压到 SNAPSHOT_LIMIT 条,免得把整库塞进提示词。"""
    if isinstance(payload, dict):
        trimmed: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, list):
                trimmed[key] = value[:SNAPSHOT_LIMIT]
                if len(value) > SNAPSHOT_LIMIT:
                    trimmed[f"{key}_total"] = len(value)
            else:
                trimmed[key] = value
        return trimmed
    if isinstance(payload, list):
        return payload[:SNAPSHOT_LIMIT]
    return payload
