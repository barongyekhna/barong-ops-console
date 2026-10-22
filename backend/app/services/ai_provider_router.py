from __future__ import annotations

import json
import os
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.organization import OrganizationRecord
from ..models.user import User
from . import anthropic_messages
from .ai_roles import DEGRADE_MODEL, DEGRADE_PROVIDER, is_role, resolve_role
from .ai_usage_ledger import claude_budget_exhausted, record_ai_usage, usage_from_response
from .event_collector import emit_event
from .module_execution_gate import (
    ModuleExecutionContext,
    ModuleExecutionGateError,
    ModuleExecutionKey,
    require_module_execution_ready,
)
from .provider_config_service import (
    ProviderConfigError,
    get_provider_config,
    normalize_provider,
    provider_key_alias,
    provider_registry_mapping,
    upsert_provider_config,
)

# 2026-10-21 换血：调用方优先传「角色」（bulk / fast / judge / writer，见 ai_roles），
# 由角色决定供应商和模型。"chatgpt" 已退役 —— 4sapi 只留生图，文字调用一律报错而不是悄悄转发。
AIProvider = Literal["serp", "claude", "deepseek", "bulk", "fast", "judge", "writer"]
AITaskType = Literal[
    "search",
    "chat",
    "generate",
    "selling_points",
    "selling_points_translation",
    "selling_points_copy",
    "content_analysis",
    "agent_chat",
]

MODEL_REGISTRY: dict[str, dict[str, str | None]] = {
    "serp": {
        "default": None,
        "search": None,
    },
    # 2026-09-11:DeepSeek 把 V4 系列收成了一个型号。官方口现在只认
    # deepseek-flash(= V4.1 Flash)和 deepseek-v4-pro,后者 2026-09-14 12:00
    # (北京)起也全部路由到 V4.1 Flash 并按 Flash 价计费 —— pro 这档事实上没了。
    # deepseek-v4-flash / deepseek-chat 官方只是"临时"保留的别名(实探都已转发到
    # deepseek-flash),别名哪天撤掉就是全线 400,所以这里一律写正名。
    # 坑:deepseek-v4.1-flash 是中转商(OpenRouter)的叫法,官方口实探返 400
    # "supported API model names are deepseek-flash, deepseek-v4-pro"。
    # 只剩一个型号,原先 pro/flash 的快慢分层(pro 中位 19.5s / flash 6.3s,
    # 2026-08-03 实测)暂时失去意义;task_type 条目一条不删,等官方放出
    # V4.1 Pro 再按需要往回填,免得将来又有人悄悄落到 default。
    "deepseek": {
        "default": "deepseek-flash",
        "chat": "deepseek-flash",
        "generate": "deepseek-flash",
        "selling_points": "deepseek-flash",
        # 卖点三阶段里的后两刀都是"照着已有卖点改写",不需要顶配推理。
        # 此前这两个 task_type 在注册表里没条目,悄悄落到 default。
        "selling_points_translation": "deepseek-flash",
        "selling_points_copy": "deepseek-flash",
        # GEO 审稿助读:逐篇解读(翻译/GEO 作用/为什么这么写),量大且不需要
        # 顶配推理,用户拍板走便宜的一档(2026-07-28)。
        "content_analysis": "deepseek-flash",
        # 数字员工(白苏婉)在 C19 通讯里的对话。刻意不复用 "chat" —— 那条
        # 落 default=pro,中位数 19.5s,聊天窗里等 20 秒等于死机。护栏在代码里
        # (动作白名单 + 权限位)而不在模型脑子里,所以这里可以放心用便宜的一档。
        "agent_chat": "deepseek-flash",
    },
    # 2026-10-21 换血:Claude 改走官方 API(Max 订阅送的额度)。直接写 provider="claude"
    # 的老调用按「终审」档处理;新代码请传角色(ai_roles)。
    "claude": {
        "default": "claude-opus-5-5",
        "chat": "claude-opus-5-5",
        "generate": "claude-opus-5-5",
    },
}

# 2026-10-21 清空:这张表曾让失败的调用悄悄转去别家(DeepSeek 失败转 GPT、Claude 失败转 GPT、
# GPT 失败转 Claude),而且调用方传 fallback_provider=None 也挡不住(旧代码用的是 `or`)。
# 换血后 Claude 是有额度上限的,这扇暗门会把大活压到 Claude 上吃光额度。
# 现在跨供应商只有两种情况:调用方明确传了 fallback_provider;或 Claude 当天预算用完按家规降级。
DEFAULT_FALLBACK_PROVIDERS: dict[str, str] = {}
# 同一供应商内遇到通道级 503 换下一个模型。4sapi 时代的 GPT/Claude 降级链随中转一起退役;
# 官方口没有「分组掉线」这回事,目前不需要链。
MODEL_FALLBACKS: dict[str, list[str]] = {}
# 240s:降级到低档模型(如 5.2-high)生成整页文案实测会超过 150s;
# 生成类任务全部走异步 job,放宽超时不影响交互体验(2026-07-22)。
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 240.0
DEFAULT_PROVIDER_MAX_ATTEMPTS = 1
# 一次 execute() 的墙钟总预算(含同 provider 模型降级 + 跨 provider fallback)。
# 上面那个 240s 只是 socket 单次操作超时,管不住"慢慢滴响应体"——台账里出现过
# 单次 deepseek 调用 903s 仍 success(2026-08-03)。而 fallback 链会再开一份
# 全新的 240s 预算,所以旧的真实上限是 ~480s 而非 240s。
# 420s 的取值:卖点生成 p50=100s、p95 仍在 200s 以内,420s 能容纳绝大多数正常
# 生成;超出的多半是上游抽风,与其让它占着 worker 槽位把整条 K 队列拖死,
# 不如失败掉让运营重点一次。
DEFAULT_PROVIDER_TOTAL_BUDGET_SECONDS = float(
    os.getenv("AI_PROVIDER_TOTAL_BUDGET_SECONDS", "420")
)


class AIProviderExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        provider: str,
        task_type: str,
        status_code: int = 502,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.provider = provider
        self.task_type = task_type
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)

    def structured_error(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "provider": self.provider,
            "task_type": self.task_type,
            "details": self.details,
        }


class AIModelRouter:
    @classmethod
    def resolve_model(cls, *, provider: str, task_type: str) -> str | None:
        canonical = normalize_provider(provider)
        provider_models = MODEL_REGISTRY.get(canonical, {})
        if task_type in provider_models:
            return provider_models[task_type]
        return provider_models.get("default")

    @classmethod
    def registry(cls) -> dict[str, dict[str, str | None]]:
        return {
            provider: dict(models)
            for provider, models in MODEL_REGISTRY.items()
        }


@dataclass(frozen=True)
class ProviderRequest:
    url: str
    headers: dict[str, str]
    body: dict[str, Any]


class BaseProviderAdapter:
    endpoint_map: dict[str, str] = {}

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        header_name: str,
        key_alias: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.header_name = header_name
        self.key_alias = key_alias

    def endpoint_for(self, task_type: str) -> str:
        endpoint = self.endpoint_map.get(task_type) or self.endpoint_map["default"]
        return endpoint if endpoint.startswith("/") else f"/{endpoint}"

    def build_request(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        model: str | None,
    ) -> ProviderRequest:
        endpoint = self.endpoint_for(task_type)
        return ProviderRequest(
            url=f"{self.base_url}{endpoint}",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                self.header_name: self.api_key,
            },
            body=self.request_builder(
                task_type=task_type,
                payload=payload,
                model=model,
            ),
        )

    def request_builder(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        model: str | None,
    ) -> dict[str, Any]:
        messages = _messages_from_payload(payload)
        return {
            **payload,
            "model": model,
            "messages": messages,
            "task_type": task_type,
        }

    def response_parser(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = _parse_provider_content(response)
        return parsed if parsed is not None else response


class SerperAdapter(BaseProviderAdapter):
    endpoint_map = {
        "default": "/search",
        "search": "/search",
    }

    def build_request(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        model: str | None,
    ) -> ProviderRequest:
        request = super().build_request(
            task_type=task_type,
            payload=payload,
            model=model,
        )
        headers = dict(request.headers)
        headers["X-API-KEY"] = self.api_key.removeprefix("Bearer ").strip()
        headers.pop("Authorization", None)
        return ProviderRequest(
            url=request.url,
            headers=headers,
            body=self.request_builder(
                task_type=task_type,
                payload=payload,
                model=model,
            ),
        )

    def request_builder(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        model: str | None,
    ) -> dict[str, Any]:
        query = payload.get("query") or payload.get("main_keyword")
        market = str(payload.get("target_market") or payload.get("market") or "US").strip()
        body: dict[str, Any] = {
            **payload,
            "model": model,
            "messages": _messages_from_payload(payload),
            "task_type": task_type,
            "q": str(query or "").strip(),
            "gl": market.lower()[:2] or "us",
            "num": 10,
        }
        if payload.get("target_language"):
            body["hl"] = str(payload["target_language"]).split("-")[0].lower()
        return body


class OpenAIAdapter(BaseProviderAdapter):
    endpoint_map = {
        "default": "/v1/chat/completions",
        "chat": "/v1/chat/completions",
        "generate": "/v1/chat/completions",
        "selling_points": "/v1/chat/completions",
    }

    # OpenAI-compatible chat APIs (incl. 4sapi) reject unknown top-level params
    # (e.g. HTTP 400 "Unknown parameter: 'instruction'"), so send a clean body
    # instead of spreading the whole payload. All caller context is preserved
    # inside `messages` via _messages_from_payload.
    _PASSTHROUGH_PARAMS = (
        "temperature",
        "top_p",
        "max_tokens",
        "max_completion_tokens",
        "response_format",
        "stop",
        "seed",
        "stream",
        "thinking",
    )

    def request_builder(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        model: str | None,
    ) -> dict[str, Any]:
        del task_type
        body: dict[str, Any] = {
            "model": model,
            "messages": _messages_from_payload(payload),
        }
        for key in self._PASSTHROUGH_PARAMS:
            if payload.get(key) is not None:
                body[key] = payload[key]
        return body


class AnthropicAdapter(BaseProviderAdapter):
    """Claude 官方 Messages API。协议细节都在 anthropic_messages 里。"""

    endpoint_map = {"default": anthropic_messages.MESSAGES_ENDPOINT}
    effort: str | None = None

    def build_request(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        model: str | None,
    ) -> ProviderRequest:
        # 只认官方地址:4sapi 时代的 claude_opus 钥匙绝不能被这里拿去打中转。
        if not anthropic_messages.is_anthropic_url(self.base_url):
            raise ValueError("anthropic_adapter_requires_official_api_url")
        max_tokens = payload.get("max_tokens") or payload.get("max_completion_tokens")
        return ProviderRequest(
            url=f"{self.base_url}{self.endpoint_for(task_type)}",
            headers=anthropic_messages.headers_for(self.api_key, model),
            body=anthropic_messages.build_body(
                model=str(model),
                messages=_messages_from_payload(payload),
                effort=self.effort,
                max_tokens=int(max_tokens) if max_tokens else None,
                json_only=anthropic_messages.wants_json(payload),
                system=payload.get("system") if isinstance(payload.get("system"), str) else None,
            ),
        )

    def response_parser(self, response: dict[str, Any]) -> dict[str, Any]:
        text = anthropic_messages.response_text(response)
        return _parse_json_text(text) or {"content": text}


class DeepSeekAdapter(OpenAIAdapter):
    endpoint_map = {
        "default": "/v1/chat/completions",
        "chat": "/v1/chat/completions",
        "generate": "/v1/chat/completions",
        "selling_points": "/v1/chat/completions",
    }

    def request_builder(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        model: str | None,
    ) -> dict[str, Any]:
        body = super().request_builder(task_type=task_type, payload=payload, model=model)
        # DeepSeek V4 默认开思考模式：2026-09-07 实测同一份 JSON 抽取开着 69s/9375
        # 推理 token，关掉 1.5s/203 token。控制台这些任务（卖点/批评/智能体意图）
        # 都不需要它想；调用方显式传 thinking 时尊重调用方。
        if "thinking" not in body:
            from r_system_v2.rw.ai.model_config import deepseek_thinking_extras

            body.update(deepseek_thinking_extras(model))
        return body


ADAPTERS = {
    "serp": SerperAdapter,
    "claude": AnthropicAdapter,
    "deepseek": DeepSeekAdapter,
}


def _messages_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    messages = payload.get("messages")
    if isinstance(messages, list) and all(isinstance(item, dict) for item in messages):
        normalized = []
        for item in messages:
            role = str(item.get("role") or "user")
            content = item.get("content")
            # 2026-10-21:列表形式的 content(文字块 + image_url 图片块)原样保留。
            # 旧代码把它 json.dumps 成一段文字 —— A 系列两道看图门因此从上线起就没把图
            # 真正发给过模型,模型拿到的是一串 base64 字符(测试打桩没抓到)。
            if not isinstance(content, (str, list)):
                content = json.dumps(content, ensure_ascii=False, default=str)
            normalized.append({"role": role, "content": content})
        return normalized
    prompt = payload.get("prompt") or payload.get("query")
    if not isinstance(prompt, str):
        prompt = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
    return [{"role": "user", "content": prompt}]


def _parse_json_text(value: str) -> dict[str, Any] | None:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _parse_provider_content(response: dict[str, Any]) -> dict[str, Any] | None:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return _parse_json_text(content) or {"content": content}
    content = response.get("content")
    if isinstance(content, list) and content:
        texts = [
            item.get("text")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        joined = "\n".join(texts).strip()
        if joined:
            return _parse_json_text(joined) or {"content": joined}
    if isinstance(content, str):
        return _parse_json_text(content) or {"content": content}
    return None


_READ_CHUNK_BYTES = 65536


def _post_json(
    *,
    request: ProviderRequest,
    timeout_seconds: float,
    deadline: float | None = None,
) -> dict[str, Any]:
    """打一次 provider,受 socket 超时**和**墙钟 deadline 双重约束。

    ``urlopen(timeout=)`` 只是 socket 单次操作超时,不是总时长。只要对端
    (或它前面的负载均衡)先发响应头、再一块一块慢慢滴响应体,每两次 recv
    的间隔都小于 timeout,这个超时就永远不会触发——总时长可以拉到任意长。

    实证(2026-08-03,event_streams 台账 40 条 selling_points 事件):
    单次 deepseek 调用出现过 409s / 900.5s / 903.2s 的 **success**,
    全部 attempt=1、无降级记录,而当时 timeout 配的是 240s。所以必须
    在分块读的循环里自己累计计时。
    """

    data = json.dumps(request.body).encode("utf-8")
    url_request = UrlRequest(
        request.url,
        data=data,
        headers=request.headers,
        method="POST",
    )

    def _check_deadline() -> None:
        if deadline is not None and perf_counter() >= deadline:
            raise TimeoutError("provider_total_budget_exhausted")

    _check_deadline()
    socket_timeout = timeout_seconds
    if deadline is not None:
        socket_timeout = max(1.0, min(timeout_seconds, deadline - perf_counter()))

    with urlopen(url_request, timeout=socket_timeout) as response:
        chunks: list[bytes] = []
        while True:
            _check_deadline()
            chunk = response.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            chunks.append(chunk)
        body = b"".join(chunks).decode("utf-8")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("provider_response_not_object")
    return parsed


class AIExecutionRouter:
    def __init__(
        self,
        db: Session,
        *,
        timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_PROVIDER_MAX_ATTEMPTS,
        total_budget_seconds: float = DEFAULT_PROVIDER_TOTAL_BUDGET_SECONDS,
    ) -> None:
        self.db = db
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self.total_budget_seconds = total_budget_seconds

    def execute(
        self,
        *,
        provider: str,
        task_type: AITaskType,
        payload: dict[str, Any],
        org: str,
        module_id: str = "k.product_knowledge",
        user: User | None = None,
        request: Request | None = None,
        execution_context: ModuleExecutionContext | None = None,
        fallback_provider: str | None = None,
        usage_label: str | None = None,
    ) -> dict[str, Any]:
        """``usage_label``:台账里记在谁名下(默认是模块 id)。数字员工共用 K 的钥匙,
        但花费要能按人查(比如苏青禾记成 ``suqinghe``)。"""
        model_override: str | None = None
        effort: str | None = None
        if is_role(provider):
            target = resolve_role(provider)
            canonical_provider, model_override, effort = target.provider, target.model, target.effort
        else:
            canonical_provider = normalize_provider(provider)
        if canonical_provider == "chatgpt":
            # 4sapi 只留生图(用户 10-19 拍板)。这里报错而不是转发,漏改的调用方会当场暴露。
            raise AIProviderExecutionError(
                "AI_PROVIDER_RETIRED",
                "ChatGPT text calls are retired; pass an AI role (bulk/fast/judge/writer).",
                provider="chatgpt",
                task_type=task_type,
                status_code=500,
            )
        degraded = False
        if canonical_provider == "claude" and claude_budget_exhausted():
            # 家规(10-21):Claude 当天额度用完,降级给 DeepSeek 照常干活,并标明是降级做的。
            canonical_provider, model_override, effort, degraded = DEGRADE_PROVIDER, DEGRADE_MODEL, None, True
        org_record = self._resolve_org(org)
        context = execution_context or require_module_execution_ready(
            self.db,
            module_id=module_id,
            user=user,
            request=request,
            explicit_org_id=org_record.org_id,
            key_requirements={
                canonical_provider: provider_key_alias(canonical_provider)
            },
        )
        self._validate_context_org(context=context, org_record=org_record)
        if degraded and self._find_key(context, canonical_provider) is None:
            # 调用方预先备好的上下文里只有 Claude 钥匙:为降级单独取一把 DeepSeek 钥匙。
            # 取不到就当场报错(模块没绑 DeepSeek),绝不拿 Claude 钥匙去打 DeepSeek。
            context = require_module_execution_ready(
                self.db,
                module_id=module_id,
                user=user,
                request=request,
                explicit_org_id=org_record.org_id,
                key_requirements={canonical_provider: provider_key_alias(canonical_provider)},
            )
            self._validate_context_org(context=context, org_record=org_record)
        key = self._key_for_provider(context, canonical_provider)
        if degraded:
            self._emit_degraded_event(org_id=org_record.org_id, task_type=task_type, module_id=module_id)
        # 墙钟总预算在这里起算,贯穿模型降级链与 provider fallback。
        # 不设它的话,一次 execute() 的真实上限是 timeout×(降级次数+fallback),
        # 而不是 timeout。
        result = self._execute_with_key(
            provider=canonical_provider,
            task_type=task_type,
            payload=payload,
            org_record=org_record,
            module_id=context.control_module_id,
            key=key,
            execution_context=context,
            fallback_provider=fallback_provider,
            fallback_allowed=True,
            deadline=perf_counter() + self.total_budget_seconds,
            model_override=model_override,
            effort=effort,
            degraded=degraded,
            usage_label=usage_label,
        )
        if degraded:
            result = {**result, "_ai_degraded": True}
        return result

    def _execute_with_key(
        self,
        *,
        provider: str,
        task_type: AITaskType,
        payload: dict[str, Any],
        org_record: OrganizationRecord,
        module_id: str,
        key: ModuleExecutionKey,
        execution_context: ModuleExecutionContext,
        fallback_provider: str | None,
        fallback_allowed: bool,
        deadline: float | None = None,
        model_override: str | None = None,
        effort: str | None = None,
        degraded: bool = False,
        usage_label: str | None = None,
    ) -> dict[str, Any]:
        model = model_override or AIModelRouter.resolve_model(provider=provider, task_type=task_type)
        config = upsert_provider_config(
            self.db,
            org_id=org_record.org_id,
            module_id=module_id,
            provider=provider,
            base_url=key.url,
            source_key_id=key.key_id,
            metadata={
                "source": "ai_execution_router",
                "key_alias": key.key_alias,
            },
        )
        config = (
            get_provider_config(
                self.db,
                org_id=org_record.org_id,
                module_id=module_id,
                provider=provider,
            )
            or config
        )
        adapter = ADAPTERS[provider](
            base_url=config.base_url,
            api_key=key.header_value,
            header_name=key.header_name,
            key_alias=key.key_alias,
        )
        if isinstance(adapter, AnthropicAdapter):
            adapter.effort = effort
        base_url = config.base_url
        endpoint_called = adapter.endpoint_for(task_type)
        self._release_db_transaction()
        # 首选模型 + 同 provider 内的降级序列;仅通道级 503 才向下换模型
        model_candidates = [model] + [
            candidate
            for candidate in MODEL_FALLBACKS.get(provider, [])
            if candidate and candidate != model
        ]
        last_error: AIProviderExecutionError | None = None
        for active_model in model_candidates:
            try:
                provider_request = adapter.build_request(
                    task_type=task_type,
                    payload=payload,
                    model=active_model,
                )
            except ValueError as exc:
                raise AIProviderExecutionError(
                    "AI_PROVIDER_MISCONFIGURED",
                    f"AI provider '{provider}' key is not usable: {exc}",
                    provider=provider,
                    task_type=task_type,
                    status_code=500,
                    details={"model": active_model, "base_url": base_url},
                ) from exc
            channel_down = False
            for attempt in range(1, self.max_attempts + 1):
                started = perf_counter()
                try:
                    raw_response = _post_json(
                        request=provider_request,
                        timeout_seconds=self.timeout_seconds,
                        deadline=deadline,
                    )
                    parsed = adapter.response_parser(raw_response)
                    latency_ms = (perf_counter() - started) * 1000
                    record_ai_usage(
                        provider=provider,
                        model=active_model,
                        module=usage_label or module_id,
                        task=task_type,
                        usage=usage_from_response(raw_response),
                        degraded=degraded,
                        latency_ms=latency_ms,
                        org_ref=org_record.org_id,
                    )
                    self._emit_execution_event(
                        provider=provider,
                        task_type=task_type,
                        org_id=org_record.org_id,
                        status="success",
                        latency_ms=latency_ms,
                        base_url=base_url,
                        endpoint_called=endpoint_called,
                        key_alias=key.key_alias,
                        model=active_model,
                        attempt=attempt,
                    )
                    self._release_db_transaction()
                    return parsed
                except HTTPError as exc:
                    channel_down = exc.code == 503
                    last_error = AIProviderExecutionError(
                        "AI_PROVIDER_HTTP_ERROR",
                        f"AI provider '{provider}' returned HTTP {exc.code}.",
                        provider=provider,
                        task_type=task_type,
                        status_code=502,
                        details={
                            "http_status": exc.code,
                            "attempt": attempt,
                            "model": active_model,
                        },
                    )
                except anthropic_messages.ClaudeRefusalError as exc:
                    last_error = AIProviderExecutionError(
                        "AI_PROVIDER_REFUSAL",
                        f"AI provider '{provider}' declined the request ({exc.category or 'unknown'}).",
                        provider=provider,
                        task_type=task_type,
                        status_code=422,
                        details={"attempt": attempt, "model": active_model, "category": exc.category},
                    )
                except TimeoutError as exc:
                    last_error = AIProviderExecutionError(
                        "AI_PROVIDER_TIMEOUT",
                        f"AI provider '{provider}' request timed out.",
                        provider=provider,
                        task_type=task_type,
                        status_code=504,
                        details={"attempt": attempt, "model": active_model},
                    )
                except (URLError, json.JSONDecodeError, ValueError) as exc:
                    # 连接阶段超时时 urlopen 抛的是 URLError(reason=socket.timeout),
                    # 会落到这里被报成 REQUEST_FAILED —— 明明是超时却不叫超时,
                    # 排查时看错误码会被带偏。按 reason 还原它的真身。
                    timed_out = isinstance(exc, URLError) and isinstance(
                        getattr(exc, "reason", None), TimeoutError
                    )
                    last_error = AIProviderExecutionError(
                        "AI_PROVIDER_TIMEOUT" if timed_out else "AI_PROVIDER_REQUEST_FAILED",
                        (
                            f"AI provider '{provider}' request timed out."
                            if timed_out
                            else f"AI provider '{provider}' request failed."
                        ),
                        provider=provider,
                        task_type=task_type,
                        status_code=504 if timed_out else 502,
                        details={
                            "attempt": attempt,
                            "error_class": exc.__class__.__name__,
                            "model": active_model,
                        },
                    )
                latency_ms = (perf_counter() - started) * 1000
                record_ai_usage(
                    provider=provider,
                    model=active_model,
                    module=usage_label or module_id,
                    task=task_type,
                    success=False,
                    degraded=degraded,
                    latency_ms=latency_ms,
                    org_ref=org_record.org_id,
                    error_code=last_error.code if last_error else None,
                )
                self._emit_execution_event(
                    provider=provider,
                    task_type=task_type,
                    org_id=org_record.org_id,
                    status="failed",
                    latency_ms=latency_ms,
                    base_url=base_url,
                    endpoint_called=endpoint_called,
                    key_alias=key.key_alias,
                    model=active_model,
                    attempt=attempt,
                    error=last_error.structured_error() if last_error else None,
                )
                self._release_db_transaction()
            if not channel_down:
                break

        # 只认调用方明确传的 fallback_provider(换血前这里会用 DEFAULT_FALLBACK_PROVIDERS 兜底)。
        resolved_fallback = fallback_provider
        # 预算耗尽就别再开一份全新的 240s 去打备胎 —— 那正是"名义 240s 上限
        # 实际能跑 480s"的来源。宁可现在就失败,让上层重试。
        budget_left = deadline is None or perf_counter() < deadline
        if fallback_allowed and resolved_fallback and budget_left:
            try:
                fallback = normalize_provider(resolved_fallback)
                fallback_key = self._key_for_provider(execution_context, fallback)
                return self._execute_with_key(
                    provider=fallback,
                    task_type=task_type,
                    payload=payload,
                    org_record=org_record,
                    module_id=module_id,
                    key=fallback_key,
                    execution_context=execution_context,
                    fallback_provider=None,
                    fallback_allowed=False,
                    deadline=deadline,
                    usage_label=usage_label,
                )
            except (ProviderConfigError, AIProviderExecutionError):
                pass

        raise last_error or AIProviderExecutionError(
            "AI_PROVIDER_REQUEST_FAILED",
            f"AI provider '{provider}' request failed.",
            provider=provider,
            task_type=task_type,
        )

    def _release_db_transaction(self) -> None:
        if not self.db.in_transaction():
            return
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _resolve_org(self, org: str) -> OrganizationRecord:
        candidate = org.strip()
        if not candidate:
            raise AIProviderExecutionError(
                "AI_PROVIDER_ORG_REQUIRED",
                "AI execution requires an organization.",
                provider="unknown",
                task_type="chat",
                status_code=403,
            )
        if candidate.startswith("org_"):
            record = self.db.get(OrganizationRecord, candidate)
        else:
            record = self.db.scalar(
                select(OrganizationRecord).where(
                    OrganizationRecord.org_name == candidate,
                    OrganizationRecord.status != "deleted",
                )
            )
        if record is None:
            raise AIProviderExecutionError(
                "AI_PROVIDER_ORG_NOT_FOUND",
                "AI execution organization was not found.",
                provider="unknown",
                task_type="chat",
                status_code=404,
                details={"org": candidate},
            )
        return record

    def _validate_context_org(
        self,
        *,
        context: ModuleExecutionContext,
        org_record: OrganizationRecord,
    ) -> None:
        if context.org_id != org_record.org_id:
            raise AIProviderExecutionError(
                "AI_PROVIDER_ORG_MISMATCH",
                "AI execution organization does not match execution gate context.",
                provider="unknown",
                task_type="chat",
                status_code=403,
                details={
                    "context_org_id": context.org_id,
                    "requested_org_id": org_record.org_id,
                },
            )

    @staticmethod
    def _find_key(
        context: ModuleExecutionContext,
        provider: str,
    ) -> ModuleExecutionKey | None:
        expected_alias = provider_key_alias(provider)
        accepted_aliases = {provider, expected_alias}
        for step, key in context.keys.items():
            if step in accepted_aliases or key.key_alias in accepted_aliases:
                return key
            try:
                if normalize_provider(key.key_alias) == provider:
                    return key
            except ProviderConfigError:
                continue
        return None

    def _key_for_provider(
        self,
        context: ModuleExecutionContext,
        provider: str,
    ) -> ModuleExecutionKey:
        # 2026-10-21 删掉了「上下文里只有一把钥匙就用它」的兜底:换血后同一个上下文里的钥匙
        # 可能属于别家(比如降级时只剩 Claude 钥匙),拿错钥匙打错供应商比报错更糟。
        key = self._find_key(context, provider)
        if key is not None:
            return key
        raise AIProviderExecutionError(
            "AI_PROVIDER_KEY_MISSING",
            f"Resolved execution context does not include provider '{provider}'.",
            provider=provider,
            task_type="chat",
            status_code=403,
            details={"available_steps": sorted(context.keys)},
        )

    def _emit_degraded_event(self, *, org_id: str, task_type: str, module_id: str) -> None:
        emit_event(
            event_type="ai_provider.degraded",
            module="system",
            action="ai_provider.degraded",
            source="backend",
            status="success",
            org_id=org_id,
            payload={
                "reason": "claude_daily_budget_exhausted",
                "provider_used": DEGRADE_PROVIDER,
                "model": DEGRADE_MODEL,
                "task_type": task_type,
                "module_id": module_id,
            },
        )

    def _emit_execution_event(
        self,
        *,
        provider: str,
        task_type: str,
        org_id: str,
        status: Literal["success", "failed"],
        latency_ms: float,
        base_url: str,
        endpoint_called: str,
        key_alias: str,
        model: str | None,
        attempt: int,
        error: dict[str, Any] | None = None,
    ) -> None:
        emit_event(
            event_type="ai_provider.execute",
            module="system",
            action="ai_provider.execute",
            source="backend",
            status=status,
            org_id=org_id,
            latency_ms=latency_ms,
            payload={
                "provider_used": provider,
                "base_url_used": base_url,
                "endpoint_called": endpoint_called,
                "api_key_alias": key_alias,
                "task_type": task_type,
                "model": model,
                "attempt": attempt,
                "success": status == "success",
                "error": error,
            },
        )


def provider_execution_report_static_mapping() -> dict[str, Any]:
    return {
        "model_registry": AIModelRouter.registry(),
        "provider_registry_mapping": provider_registry_mapping(),
        "execution_flow": [
            "resolve provider",
            "resolve model",
            "resolve endpoint",
            "inject api key",
            "execute request",
        ],
    }
