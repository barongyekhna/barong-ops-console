from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy.orm import Session

from .api_key_orchestration import (
    ApiKeyInjectionContext,
    ApiKeyIsolationError,
    KEEPA_KEY_ALIAS,
    KEEPA_KEY_TYPE,
    R_WAREHOUSE_MODULE_ID,
    resolve_module_api_key_for_injection,
)


@dataclass(frozen=True)
class RWKeepaIngestionContext:
    org_id: str
    module_id: str
    key_id: str
    key_alias: str
    adapter: str
    provider: str
    auth_type: str
    base_url: str
    token_check_url: str


def _keepa_token_check_url(context: ApiKeyInjectionContext) -> str:
    key_value = context.query_param_value
    if not key_value:
        raise ApiKeyIsolationError("keepa_query_key_unavailable")
    return (
        f"{context.url.rstrip('/')}/token?key="
        f"{quote(key_value, safe='')}"
    )


def resolve_keepa_context_for_asin_ingestion(
    db: Session,
    *,
    org_id: str,
) -> RWKeepaIngestionContext:
    context = resolve_module_api_key_for_injection(
        db,
        org_id=org_id,
        module_id=R_WAREHOUSE_MODULE_ID,
        key_alias=KEEPA_KEY_ALIAS,
    )
    if context.key_type != KEEPA_KEY_TYPE or context.adapter != "KeepaAdapter":
        raise ApiKeyIsolationError("keepa_adapter_not_bound")
    return RWKeepaIngestionContext(
        org_id=context.org_id,
        module_id=context.module_id,
        key_id=context.key_id,
        key_alias=context.key_alias,
        adapter=context.adapter,
        provider=context.provider,
        auth_type=context.auth_type,
        base_url=context.url.rstrip("/"),
        token_check_url=_keepa_token_check_url(context),
    )


def keepa_ingestion_runtime_status(
    db: Session,
    *,
    org_id: str,
) -> dict[str, object]:
    try:
        context = resolve_keepa_context_for_asin_ingestion(db, org_id=org_id)
    except ApiKeyIsolationError as exc:
        return {
            "keepa_key_bound": False,
            "ingestion_service_ready": False,
            "adapter": "KeepaAdapter",
            "provider": "keepa",
            "required_key_alias": KEEPA_KEY_ALIAS,
            "reason": str(exc),
        }
    return {
        "keepa_key_bound": True,
        "ingestion_service_ready": True,
        "adapter": context.adapter,
        "provider": context.provider,
        "required_key_alias": context.key_alias,
        "key_id": context.key_id,
        "pipeline": "Keepa API -> async worker -> memory buffer -> batch writer -> product DB",
        "db_write_mode": "buffered_batch",
        "api_key_usage_mode": "in_memory_aggregate_60s",
    }
