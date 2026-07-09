from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.provider_config import ProviderConfigRecord

PROVIDER_ALIASES = {
    "serp": "serp",
    "serper": "serp",
    "chatgpt": "chatgpt",
    "openai": "chatgpt",
    "4sapi": "chatgpt",
    "ai_provider": "chatgpt",
    "claude": "claude",
    "claude_opus": "claude",
    "anthropic": "claude",
    "deepseek": "deepseek",
    "keepa": "keepa",
    "google_ads": "google_ads",
    "googleads": "google_ads",
    "keyword_planner": "google_ads",
}

PROVIDER_KEY_ALIASES = {
    "serp": "serp",
    "chatgpt": "chatgpt",
    "claude": "claude_opus",
    "deepseek": "deepseek",
    "keepa": "keepa",
    "google_ads": "google_ads",
}


class ProviderConfigError(ValueError):
    pass


def normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower().replace("-", "_")
    canonical = PROVIDER_ALIASES.get(normalized)
    if canonical is None:
        raise ProviderConfigError(f"unsupported_provider:{provider}")
    return canonical


def provider_key_alias(provider: str) -> str:
    return PROVIDER_KEY_ALIASES[normalize_provider(provider)]


def get_provider_config(
    db: Session,
    *,
    org_id: str,
    module_id: str,
    provider: str,
) -> ProviderConfigRecord | None:
    canonical = normalize_provider(provider)
    return db.scalar(
        select(ProviderConfigRecord).where(
            ProviderConfigRecord.org_id == org_id,
            ProviderConfigRecord.module_id == module_id,
            ProviderConfigRecord.provider == canonical,
            ProviderConfigRecord.status == "active",
        )
    )


def upsert_provider_config(
    db: Session,
    *,
    org_id: str,
    module_id: str,
    provider: str,
    base_url: str,
    source_key_id: str | None,
    metadata: Mapping[str, Any] | None = None,
) -> ProviderConfigRecord:
    canonical = normalize_provider(provider)
    normalized_url = base_url.strip().rstrip("/")
    if not normalized_url:
        raise ProviderConfigError("provider_base_url_required")
    record = db.scalar(
        select(ProviderConfigRecord).where(
            ProviderConfigRecord.org_id == org_id,
            ProviderConfigRecord.module_id == module_id,
            ProviderConfigRecord.provider == canonical,
        )
    )
    if record is None:
        record = ProviderConfigRecord(
            org_id=org_id,
            module_id=module_id,
            provider=canonical,
            base_url=normalized_url,
            source_key_id=source_key_id,
            status="active",
            metadata_json=dict(metadata or {}),
        )
    else:
        record.base_url = normalized_url
        record.source_key_id = source_key_id
        record.status = "active"
        record.metadata_json = {
            **(record.metadata_json or {}),
            **dict(metadata or {}),
        }
    db.add(record)
    db.flush()
    return record


def provider_registry_mapping() -> dict[str, dict[str, str | None]]:
    return {
        "serp": {
            "adapter": "SerperAdapter",
            "default_key_alias": "serp",
            "endpoint": "/search",
        },
        "chatgpt": {
            "adapter": "OpenAIAdapter",
            "default_key_alias": "chatgpt",
            "endpoint": "/v1/chat/completions",
        },
        "claude": {
            "adapter": "ClaudeAdapter",
            "default_key_alias": "claude_opus",
            "endpoint": "/v1/messages",
        },
        "deepseek": {
            "adapter": "DeepSeekAdapter",
            "default_key_alias": "deepseek",
            "endpoint": "/chat/completions",
        },
        "keepa": {
            "adapter": "KeepaAdapter",
            "default_key_alias": "keepa",
            "endpoint": "/token",
        },
        "google_ads": {
            "adapter": "GoogleAdsKeywordPlannerAdapter",
            "default_key_alias": "google_ads",
            "endpoint": "/v*/customers/*:generateKeywordIdeas",
        },
    }
