"""AI 分工：调用方说「要什么档次的活」，不说「用哪家哪个模型」。

2026-10-21 用户定的分层（AI 换血）：
- ``bulk``   低级、大量的活 → DeepSeek flash
- ``fast``   要一点判断但量不小（识别、分类、作图指令）→ Claude Haiku 5.5
- ``judge``  把关、终审、决策 → Claude Opus 5.5
- ``writer`` 面向美国买家的英文成稿（文章、产品文案）→ Claude Opus 5.5

每个角色都能用环境变量换：``AI_ROLE_<角色>_PROVIDER`` / ``_MODEL`` / ``_EFFORT``。
比如英文文案换 DeepSeek 的 5 品盲测有了结论，只改 ``AI_ROLE_WRITER_*`` 两个变量，不动代码。

Claude 当天花费到了上限（``AI_CLAUDE_DAILY_BUDGET_USD``，见 ai_usage_ledger）就把这次调用
降级给 DeepSeek flash 照常干活，结果上带 ``degraded`` 标记（用户 10-21 拍板）。
降级只由预算触发；Claude 调用本身失败**不会**悄悄转去别家 —— 那正是换血要堵的暗门。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from . import anthropic_messages
from .ai_usage_ledger import (
    AIUsage,
    claude_budget_exhausted,
    record_ai_usage,
    usage_from_response,
)

ROLE_BULK = "bulk"
ROLE_FAST = "fast"
ROLE_JUDGE = "judge"
ROLE_WRITER = "writer"

_ROLE_DEFAULTS: dict[str, tuple[str, str, str | None]] = {
    ROLE_BULK: ("deepseek", "deepseek-flash", None),
    ROLE_FAST: ("claude", "claude-haiku-5-5", "low"),
    ROLE_JUDGE: ("claude", "claude-opus-5-5", "medium"),
    ROLE_WRITER: ("claude", "claude-opus-5-5", "medium"),
}
ROLES = frozenset(_ROLE_DEFAULTS)

DEGRADE_PROVIDER = "deepseek"
DEGRADE_MODEL = "deepseek-flash"
DEEPSEEK_API_BASE = "https://api.deepseek.com"


@dataclass(frozen=True)
class RoleTarget:
    role: str
    provider: str
    model: str
    effort: str | None


def resolve_role(role: str) -> RoleTarget:
    name = role.strip().lower()
    if name not in _ROLE_DEFAULTS:
        raise ValueError(f"unknown_ai_role:{role}")
    provider, model, effort = _ROLE_DEFAULTS[name]
    prefix = f"AI_ROLE_{name.upper()}_"
    provider = os.getenv(prefix + "PROVIDER", "").strip().lower() or provider
    model = os.getenv(prefix + "MODEL", "").strip() or model
    effort = os.getenv(prefix + "EFFORT", "").strip().lower() or effort
    if provider not in {"claude", "deepseek"}:
        raise ValueError(f"unsupported_ai_role_provider:{provider}")
    return RoleTarget(role=name, provider=provider, model=model, effort=effort if provider == "claude" else None)


def is_role(value: str | None) -> bool:
    return (value or "").strip().lower() in ROLES


@dataclass(frozen=True)
class DirectCompletion:
    text: str
    provider: str
    model: str
    degraded: bool
    usage: AIUsage


class DirectCompletionError(RuntimeError):
    def __init__(self, code: str, message: str, *, provider: str, model: str, http_status: int | None = None) -> None:
        self.code = code
        self.provider = provider
        self.model = model
        self.http_status = http_status
        super().__init__(message)


def complete(
    role: str,
    *,
    messages: list[dict[str, Any]],
    module: str,
    task: str,
    anthropic_key: str | None,
    deepseek_key: str | None,
    deepseek_base_url: str | None = None,
    json_only: bool = False,
    max_tokens: int | None = None,
    timeout_seconds: float = 240.0,
    org_ref: str | None = None,
) -> DirectCompletion:
    """给不走统一路由的直连调用方（brand_guard、R-A）用：按角色调一次，自带台账和预算降级。

    ``messages`` 用 OpenAI 格式（可含 system 角色和 image_url 块），两家都能吃。
    """
    target = resolve_role(role)
    provider, model, degraded = target.provider, target.model, False
    if provider == "claude" and claude_budget_exhausted():
        provider, model, degraded = DEGRADE_PROVIDER, DEGRADE_MODEL, True
    if provider == "claude" and not anthropic_key:
        raise DirectCompletionError("AI_KEY_MISSING", "anthropic key missing", provider=provider, model=model)
    if provider == "deepseek" and not deepseek_key:
        raise DirectCompletionError("AI_KEY_MISSING", "deepseek key missing", provider=provider, model=model)

    from .ai_provider_router import ProviderRequest, _post_json

    if provider == "claude":
        request = ProviderRequest(
            url=anthropic_messages.ANTHROPIC_API_BASE + anthropic_messages.MESSAGES_ENDPOINT,
            headers=anthropic_messages.headers_for(str(anthropic_key), model),
            body=anthropic_messages.build_body(
                model=model,
                messages=messages,
                effort=target.effort,
                max_tokens=max_tokens,
                json_only=json_only,
            ),
        )
    else:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            # DeepSeek V4 默认开思考，40 倍成本（2026-09-07）。家规：永远关着。
            "thinking": {"type": "disabled"},
        }
        if json_only:
            body["response_format"] = {"type": "json_object"}
        if max_tokens:
            body["max_tokens"] = int(max_tokens)
        base = (deepseek_base_url or DEEPSEEK_API_BASE).rstrip("/")
        request = ProviderRequest(
            url=f"{base}/v1/chat/completions",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {anthropic_messages.raw_key(str(deepseek_key))}",
            },
            body=body,
        )

    started = perf_counter()
    try:
        raw = _post_json(request=request, timeout_seconds=timeout_seconds, deadline=started + timeout_seconds)
        if provider == "claude":
            text = anthropic_messages.response_text(raw)
        else:
            choices = raw.get("choices") or []
            message = choices[0].get("message") if choices and isinstance(choices[0], dict) else None
            text = str((message or {}).get("content") or "").strip()
    except Exception as exc:  # noqa: BLE001 —— 记账后原样抛给调用方
        http_status = getattr(exc, "code", None)
        code = "AI_REFUSAL" if isinstance(exc, anthropic_messages.ClaudeRefusalError) else (
            f"HTTP_{http_status}" if isinstance(http_status, int) else exc.__class__.__name__
        )
        record_ai_usage(
            provider=provider, model=model, module=module, task=task, success=False,
            degraded=degraded, latency_ms=(perf_counter() - started) * 1000, org_ref=org_ref, error_code=code,
        )
        raise DirectCompletionError(
            code, f"{provider} call failed: {code}", provider=provider, model=model,
            http_status=http_status if isinstance(http_status, int) else None,
        ) from exc
    usage = usage_from_response(raw)
    record_ai_usage(
        provider=provider, model=model, module=module, task=task, usage=usage,
        degraded=degraded, latency_ms=(perf_counter() - started) * 1000, org_ref=org_ref,
    )
    return DirectCompletion(text=text, provider=provider, model=model, degraded=degraded, usage=usage)


def parse_json_object(text: str) -> dict[str, Any] | None:
    from .ai_provider_router import _parse_json_text

    return _parse_json_text(text) if text else None


__all__ = [
    "ROLES",
    "ROLE_BULK",
    "ROLE_FAST",
    "ROLE_JUDGE",
    "ROLE_WRITER",
    "DirectCompletion",
    "DirectCompletionError",
    "RoleTarget",
    "complete",
    "is_role",
    "parse_json_object",
    "resolve_role",
]
