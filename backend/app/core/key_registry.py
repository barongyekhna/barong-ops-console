from __future__ import annotations

from copy import deepcopy
from typing import Any


KEY_TYPE_REGISTRY: dict[str, dict[str, Any]] = {
    "custom": {
        "type": "custom",
        "name": "Custom API",
        "description": "Custom backend-injected API key",
        "provider": "custom",
        "auth_type": "api_key",
        "enabled": True,
        "scope": [],
        "validation_endpoint": None,
        "default_url": None,
        "default_alias": "default",
        "adapter": None,
        "module_ids": [],
    },
    "deepseek": {
        "type": "deepseek",
        "name": "DeepSeek",
        "description": "DeepSeek AI API",
        "provider": "deepseek",
        "auth_type": "api_key",
        "enabled": True,
        "scope": ["K", "R-A"],
        "validation_endpoint": None,
        "default_url": "https://api.deepseek.com",
        "default_alias": "deepseek",
        "adapter": "DeepSeekAdapter",
        "module_ids": ["k.product_knowledge", "r.analysis"],
    },
    "openai": {
        "type": "openai",
        "name": "OpenAI",
        "description": "OpenAI-compatible AI API",
        "provider": "openai",
        "auth_type": "api_key",
        "enabled": True,
        "scope": ["K", "I", "R-A"],
        "validation_endpoint": None,
        "default_url": "https://api.openai.com/v1",
        "default_alias": "chatgpt",
        "adapter": "OpenAIAdapter",
        "module_ids": ["k.product_knowledge", "i.image_system", "r.analysis"],
    },
    "chatgpt": {
        "type": "chatgpt",
        "name": "ChatGPT / 4sapi",
        "description": "ChatGPT-compatible AI API",
        "provider": "chatgpt",
        "auth_type": "api_key",
        "enabled": True,
        "scope": ["K", "I", "R-A"],
        "validation_endpoint": None,
        "default_url": "https://api.openai.com/v1",
        "default_alias": "chatgpt",
        "adapter": "OpenAIAdapter",
        "module_ids": ["k.product_knowledge", "i.image_system", "r.analysis"],
    },
    "claude_opus": {
        "type": "claude_opus",
        "name": "Claude Opus",
        "description": "Anthropic Claude API",
        "provider": "claude",
        "auth_type": "api_key",
        "enabled": True,
        "scope": ["K", "R-A"],
        "validation_endpoint": None,
        "default_url": "https://api.anthropic.com",
        "default_alias": "claude_opus",
        "adapter": "ClaudeAdapter",
        "module_ids": ["k.product_knowledge", "r.analysis"],
    },
    "serp": {
        "type": "serp",
        "name": "SERP",
        "description": "Search engine result provider API",
        "provider": "serp",
        "auth_type": "api_key",
        "enabled": True,
        "scope": ["K", "R-A"],
        "validation_endpoint": None,
        "default_url": "https://google.serper.dev",
        "default_alias": "serp",
        "adapter": "SerperAdapter",
        "module_ids": ["k.product_knowledge", "r.analysis"],
    },
    "alibaba1688": {
        "type": "alibaba1688",
        "name": "1688 Official API",
        "description": "1688 Open Platform AppKey, AppSecret, and access token payload",
        "provider": "alibaba1688",
        "auth_type": "api_key",
        "enabled": True,
        "scope": ["R-A"],
        "validation_endpoint": None,
        "default_url": "https://open.1688.com",
        "default_alias": "alibaba1688",
        "adapter": "Alibaba1688OpenApiAdapter",
        "module_ids": ["r.analysis"],
    },
    "n8n": {
        "type": "n8n",
        "name": "n8n Webhook",
        "description": "n8n webhook execution key",
        "provider": "n8n",
        "auth_type": "api_key",
        "enabled": True,
        "scope": ["Integration"],
        "validation_endpoint": None,
        "default_url": "https://n8n.example.com",
        "default_alias": "n8n",
        "adapter": "WebhookAdapter",
        "module_ids": ["integration.n8n_test_bridge"],
    },
    "keepa": {
        "type": "keepa",
        "name": "Keepa API",
        "description": "Amazon ASIN market intelligence API",
        "provider": "keepa",
        "auth_type": "api_key",
        "enabled": True,
        "scope": ["R-W"],
        "validation_endpoint": "https://api.keepa.com/token?key={key}",
        "default_url": "https://api.keepa.com",
        "default_alias": "keepa",
        "adapter": "KeepaAdapter",
        "module_ids": ["r.warehouse"],
    },
    "rainforest": {
        "type": "rainforest",
        "name": "Rainforest API",
        "description": "Real-time Amazon page-one search/product data for R-A competition metrics",
        "provider": "rainforest",
        "auth_type": "api_key",
        "enabled": True,
        "scope": ["R-A"],
        "validation_endpoint": None,
        "default_url": "https://api.rainforestapi.com",
        "default_alias": "rainforest",
        "adapter": None,
        "module_ids": ["r.analysis"],
    },
    "google_ads": {
        "type": "google_ads",
        "name": "Google Ads API",
        "description": "Google Ads Keyword Planner OAuth credential payload for R-A DTC SEO signals; runtime pending Basic review",
        "provider": "google_ads",
        "auth_type": "oauth_json",
        "enabled": True,
        "scope": ["R-A"],
        "validation_endpoint": None,
        "default_url": "https://googleads.googleapis.com",
        "default_alias": "google_ads",
        "adapter": "GoogleAdsKeywordPlannerAdapter",
        "runtime_status": "pending_basic_review",
        "runtime_enabled": False,
        "module_ids": ["r.analysis"],
    },
}

KEY_TYPE_MARKERS: dict[str, tuple[str, ...]] = {
    "keepa": ("keepa", "api.keepa.com"),
    "deepseek": ("deepseek",),
    "openai": ("openai",),
    "chatgpt": ("chatgpt", "4sapi"),
    "claude_opus": ("claude", "anthropic", "opus"),
    "serp": ("serp", "serper"),
    "alibaba1688": ("1688", "alibaba1688", "open.1688.com", "阿里巴巴开放平台"),
    "n8n": ("n8n", "webhook"),
    "rainforest": ("rainforest", "rainforestapi", "api.rainforestapi.com"),
    "google_ads": ("google_ads", "google ads", "googleads", "keyword planner"),
}


def normalize_key_type(value: str | None) -> str:
    normalized = (value or "custom").strip().lower().replace("-", "_")
    if normalized == "claude":
        normalized = "claude_opus"
    if normalized == "serper":
        normalized = "serp"
    if normalized in {"1688", "alibaba_1688", "alibaba"}:
        normalized = "alibaba1688"
    if normalized in {"googleads", "google_ads_api", "keyword_planner"}:
        normalized = "google_ads"
    if normalized not in KEY_TYPE_REGISTRY:
        raise ValueError("unknown_key_type")
    return normalized


def key_type_definition(key_type: str | None) -> dict[str, Any]:
    return deepcopy(KEY_TYPE_REGISTRY[normalize_key_type(key_type)])


def list_key_type_definitions() -> list[dict[str, Any]]:
    preferred_order = [
        "deepseek",
        "openai",
        "keepa",
        "alibaba1688",
        "chatgpt",
        "claude_opus",
        "serp",
        "rainforest",
        "google_ads",
        "n8n",
        "custom",
    ]
    return [key_type_definition(key_type) for key_type in preferred_order]


def metadata_for_key_type(key_type: str | None) -> dict[str, Any]:
    definition = key_type_definition(key_type)
    return {
        "key_type": definition["type"],
        "provider": definition["provider"],
        "auth_type": definition["auth_type"],
        "scope": list(definition["scope"]),
        "validation_endpoint": definition["validation_endpoint"],
        "default_alias": definition["default_alias"],
        "adapter": definition["adapter"],
    }


def infer_key_type_from_record(
    *,
    name: str,
    url: str,
    metadata: dict[str, Any] | None,
) -> str:
    metadata = metadata or {}
    explicit = metadata.get("key_type")
    if explicit:
        try:
            return normalize_key_type(str(explicit))
        except ValueError:
            pass

    haystack = " ".join(
        [
            name,
            url,
            str(metadata.get("provider") or ""),
            str(metadata.get("key_alias") or ""),
            str(metadata.get("default_alias") or ""),
        ]
    ).lower()
    for key_type, markers in KEY_TYPE_MARKERS.items():
        if any(marker in haystack for marker in markers):
            return key_type
    return "custom"


def key_type_allows_module(key_type: str | None, module_id: str) -> bool:
    definition = key_type_definition(key_type)
    module_ids = definition.get("module_ids") or []
    return not module_ids or module_id in module_ids
