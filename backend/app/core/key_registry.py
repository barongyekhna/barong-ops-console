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
    # 2026-10-21 换血:Claude 改走官方 API(Max 订阅送的额度)。官方钥匙单独一个类型,
    # 注入头是 x-api-key;路由的 Claude 绑定别名也换成 anthropic,4sapi 时代的
    # claude_opus 钥匙从此不会再被文字调用取到。
    "anthropic": {
        "type": "anthropic",
        "name": "Anthropic(Claude 官方)",
        "description": "Claude 官方 API(Haiku / Opus)",
        "provider": "claude",
        "auth_type": "api_key",
        "enabled": True,
        "scope": ["K", "R-A", "GEO", "SEO", "A"],
        "validation_endpoint": None,
        "default_url": "https://api.anthropic.com",
        "default_alias": "anthropic",
        "adapter": "AnthropicAdapter",
        "module_ids": ["k.product_knowledge", "r.analysis", "amz.ops"],
    },
    "claude_opus": {
        "type": "claude_opus",
        "name": "Claude Opus(4sapi 中转,已退役)",
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
        "module_ids": ["r.warehouse", "amz.ops"],
    },
    # A 系列(2026-09-15):两种 JSON 凭据类型,与 google_ads 同一套 oauth_json 路子。
    # secret 是一行 JSON:sp_api {client_id, client_secret, refresh_token, region(na|eu|fe)},
    # ads_api 再加 profile_ids: [..]。一家公司一把 sp_api(alias sp_api),一店一把 ads(alias ads:<store>)。
    "amazon_sp_api": {
        "type": "amazon_sp_api",
        "name": "Amazon SP-API (private app)",
        "description": "Selling Partner API LWA credential payload for one company's private application",
        "provider": "amazon",
        "auth_type": "oauth_json",
        "enabled": True,
        "scope": ["A"],
        "validation_endpoint": None,
        "default_url": "https://sellingpartnerapi-na.amazon.com",
        "default_alias": "sp_api",
        "adapter": "AmazonSpApiAdapter",
        "module_ids": ["amz.ops"],
    },
    "amazon_ads_api": {
        "type": "amazon_ads_api",
        "name": "Amazon Ads API",
        "description": "Amazon Advertising API LWA credential payload plus the store's profile ids",
        "provider": "amazon",
        "auth_type": "oauth_json",
        "enabled": True,
        "scope": ["A"],
        "validation_endpoint": None,
        "default_url": "https://advertising-api.amazon.com",
        "default_alias": "ads",
        "adapter": "AmazonAdsAdapter",
        "module_ids": ["amz.ops"],
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
    "google_search_console": {
        "type": "google_search_console",
        "name": "Google Search Console(服务账号)",
        "description": "苏青禾读 barongyekhna.com 的搜索表现(词/页的展现、点击、排名)做搜索缺口;粘服务账号 JSON 钥匙,只读",
        "provider": "google",
        "auth_type": "oauth_json",
        "enabled": True,
        "scope": ["SQH"],
        "validation_endpoint": None,
        "default_url": "https://searchconsole.googleapis.com",
        "default_alias": "gsc",
        "adapter": "GoogleSearchConsoleAdapter",
        "module_ids": ["k.product_knowledge"],
    },
    "track17": {
        "type": "track17",
        "name": "17TRACK",
        "description": "17TRACK shipment registration and tracking API",
        "provider": "track17",
        "auth_type": "api_key",
        "enabled": True,
        "scope": ["W-S"],
        "validation_endpoint": None,
        "default_url": "https://api.17track.net",
        "default_alias": "track17",
        "adapter": None,
        "module_ids": ["w.site_ops"],
    },
}

KEY_TYPE_MARKERS: dict[str, tuple[str, ...]] = {
    "keepa": ("keepa", "api.keepa.com"),
    "deepseek": ("deepseek",),
    "openai": ("openai",),
    "chatgpt": ("chatgpt", "4sapi"),
    "anthropic": ("api.anthropic.com",),
    "claude_opus": ("claude", "anthropic", "opus"),
    "serp": ("serp", "serper"),
    "alibaba1688": ("1688", "alibaba1688", "open.1688.com", "阿里巴巴开放平台"),
    "n8n": ("n8n", "webhook"),
    "rainforest": ("rainforest", "rainforestapi", "api.rainforestapi.com"),
    "google_ads": ("google_ads", "google ads", "googleads", "keyword planner"),
    "track17": ("track17", "17track", "api.17track.net"),
    "amazon_sp_api": ("amazon_sp_api", "sp_api", "spapi", "sellingpartnerapi"),
    "amazon_ads_api": ("amazon_ads_api", "amazon_ads", "advertising-api.amazon.com"),
    "google_search_console": ("google_search_console", "gsc", "search_console", "searchconsole.googleapis.com"),
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
    if normalized in {"17track", "17_track"}:
        normalized = "track17"
    if normalized in {"sp_api", "spapi", "selling_partner_api"}:
        normalized = "amazon_sp_api"
    if normalized in {"amazon_ads", "ads_api", "amazon_advertising"}:
        normalized = "amazon_ads_api"
    if normalized in {"gsc", "search_console", "google_gsc"}:
        normalized = "google_search_console"
    if normalized not in KEY_TYPE_REGISTRY:
        raise ValueError("unknown_key_type")
    return normalized


def key_type_definition(key_type: str | None) -> dict[str, Any]:
    return deepcopy(KEY_TYPE_REGISTRY[normalize_key_type(key_type)])


def list_key_type_definitions() -> list[dict[str, Any]]:
    preferred_order = [
        "deepseek",
        "anthropic",
        "openai",
        "keepa",
        "alibaba1688",
        "chatgpt",
        "claude_opus",
        "serp",
        "rainforest",
        "google_ads",
        "amazon_sp_api",
        "amazon_ads_api",
        "google_search_console",
        "track17",
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
