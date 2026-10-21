"""Claude 官方 Messages API（原生协议，裸 HTTP）。

2026-10-21 换血之前，控制台调 Claude 走的是 4sapi 中转，路由里的 ``ClaudeAdapter``
只换了个地址：没有 ``x-api-key`` / ``anthropic-version`` 头，``system`` 不单拎，
不带 ``max_tokens``，图片块被压成 JSON 文字——换到官方口一条都过不去。
这里把「OpenAI 格式的调用参数 → Anthropic 请求体」「回包 → 文字 + 用量」集中成一处，
统一路由（``ai_provider_router.AnthropicAdapter``）和直连调用方（brand_guard、R-A）共用。

不用官方 SDK 的原因：路由是一套多家供应商共用的裸 HTTP 适配层，自带墙钟总预算
（分块读 + deadline，见 ``ai_provider_router._post_json``）；为一家供应商把 SDK 和它的
HTTP 栈装进 15 个镜像，换来的是两套超时语义并存。

模型行为要点（2026-10 Claude 5.5 代）：
- Opus 5.5 / Haiku 5.5 的思考关不掉（``thinking: disabled`` 返 400），只能用
  ``output_config.effort`` 控制深浅；Opus 5.5 默认 medium，这里按角色显式给。
- ``temperature`` / ``top_p`` 非默认值返 400，所以 OpenAI 习惯里的 ``temperature: 0`` 一律丢弃。
- 回包里先有 ``thinking`` 块（默认空文字）再有 ``text`` 块，只取 text。
- ``stop_reason == "refusal"`` 是安全分类器拒答，HTTP 仍是 200，必须当失败处理。
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

ANTHROPIC_API_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
MESSAGES_ENDPOINT = "/v1/messages"
MODELS_ENDPOINT = "/v1/models"
ANTHROPIC_HOSTS = frozenset({"api.anthropic.com"})

DEFAULT_MAX_TOKENS = 16000
# 思考也占输出 token。调用方按 OpenAI 习惯给的 max_tokens（比如 300）在这里会被思考吃光、
# 一个字不吐，所以设个下限；只按实际用量计费，放大上限不多花钱。
MIN_MAX_TOKENS = 8000

# Opus 5.5 被安全分类器拒答时，由服务端按拒答类别自动转给能答的模型（同一次调用内）。
# 官方建议对 Opus 5.5 默认打开；出问题可用 AI_CLAUDE_REFUSAL_FALLBACK=0 关掉。
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_REFUSAL_FALLBACK_MODELS = frozenset({"claude-opus-5-5"})

_JSON_ONLY_INSTRUCTION = "Respond with a single valid JSON object and nothing else."


class ClaudeRefusalError(RuntimeError):
    """模型被安全分类器拒答（HTTP 200，stop_reason=refusal）。"""

    def __init__(self, category: str | None) -> None:
        self.category = category
        super().__init__(f"claude_refusal:{category or 'unknown'}")


def is_anthropic_url(url: str | None) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return host in ANTHROPIC_HOSTS


def raw_key(header_value: str) -> str:
    value = (header_value or "").strip()
    return value[7:].strip() if value.lower().startswith("bearer ") else value


def headers_for(api_key: str, model: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-api-key": raw_key(api_key),
        "anthropic-version": ANTHROPIC_VERSION,
    }
    if _refusal_fallback_enabled(model):
        headers["anthropic-beta"] = REFUSAL_FALLBACK_BETA
    return headers


def _refusal_fallback_enabled(model: str | None) -> bool:
    if (model or "") not in _REFUSAL_FALLBACK_MODELS:
        return False
    return os.getenv("AI_CLAUDE_REFUSAL_FALLBACK", "1").strip().lower() not in {"0", "false", "off", "no"}


def _image_block(url: str) -> dict[str, Any] | None:
    url = url.strip()
    if url.startswith("data:"):
        header, _, data = url.partition(",")
        if ";base64" not in header or not data:
            return None
        media_type = header[5:].split(";", 1)[0] or "image/png"
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
    if url.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _content_blocks(content: Any) -> str | list[dict[str, Any]]:
    """OpenAI 格式的 content → Anthropic 格式。字符串原样；列表逐块翻译。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return json.dumps(content, ensure_ascii=False, default=str)
    blocks: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            blocks.append({"type": "text", "text": item})
            continue
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text" and isinstance(item.get("text"), str):
            blocks.append({"type": "text", "text": item["text"]})
        elif kind == "image_url":
            image_url = item.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else image_url
            block = _image_block(str(url or ""))
            if block is not None:
                blocks.append(block)
        elif kind in {"image", "document"} and isinstance(item.get("source"), dict):
            blocks.append(item)
    return blocks or ""


def _system_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text"))
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    return json.dumps(content, ensure_ascii=False, default=str)


def build_body(
    *,
    model: str,
    messages: list[dict[str, Any]],
    effort: str | None = None,
    max_tokens: int | None = None,
    json_only: bool = False,
    system: str | None = None,
) -> dict[str, Any]:
    """OpenAI 风格的 messages（可含 system 角色、image_url 块）→ Messages API 请求体。"""
    system_parts = [system] if system else []
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if role == "system":
            text = _system_text(content)
            if text:
                system_parts.append(text)
            continue
        converted.append(
            {
                "role": "assistant" if role == "assistant" else "user",
                "content": _content_blocks(content),
            }
        )
    if not converted or converted[0]["role"] != "user":
        converted.insert(0, {"role": "user", "content": "Continue."})
    # 新一代模型不接受末尾的 assistant 预填（400）。
    while converted and converted[-1]["role"] == "assistant":
        converted.pop()
    if json_only:
        system_parts.append(_JSON_ONLY_INSTRUCTION)
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max(int(max_tokens or DEFAULT_MAX_TOKENS), MIN_MAX_TOKENS),
        "messages": converted,
    }
    if system_parts:
        body["system"] = "\n\n".join(part for part in system_parts if part)
    if effort:
        body["output_config"] = {"effort": effort}
    if _refusal_fallback_enabled(model):
        body["fallbacks"] = "default"
    return body


def response_text(response: dict[str, Any]) -> str:
    """只拼 text 块；拒答抛 ClaudeRefusalError。"""
    if response.get("stop_reason") == "refusal":
        details = response.get("stop_details")
        category = details.get("category") if isinstance(details, dict) else None
        raise ClaudeRefusalError(category)
    content = response.get("content")
    if not isinstance(content, list):
        return ""
    return "\n".join(
        item["text"]
        for item in content
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)
    ).strip()


def wants_json(payload: dict[str, Any]) -> bool:
    response_format = payload.get("response_format")
    return isinstance(response_format, dict) and response_format.get("type") in {"json_object", "json_schema"}
