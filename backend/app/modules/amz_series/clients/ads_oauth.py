"""广告 API 的授权通道:start(存钥匙对、出授权链接)→ 老板在广告后台点一下 → complete(换令牌、拉 profile、存密钥)。

为什么要有这一段而不是让老板复制粘贴:授权码只活五分钟,而且刷新令牌不该经过聊天窗。
钥匙对先加密放在店铺 metadata 里(同一把主钥),成功后整份 JSON 进密钥管理(alias ``ads:{store}``),
metadata 里的临时数据即刻清掉。四家公司都走这一条。
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....models.api_keys import ApiKeyModuleBindingRecord, ApiKeyRecord
from ....schemas.api_key_orchestration import ApiKeyBindingCreateRequest, ApiKeyCreateRequest, ApiKeyUpdateRequest, KeyType
from ....services.api_key_orchestration import _decrypt_key_value, _encrypt_key_value, create_api_key, create_api_key_binding, update_api_key
from ....services.data_isolation import without_org_data_isolation
from ..constants import KEY_ALIAS_ADS_PREFIX, MODULE_KEY
from ..models import AmzStore
from ..service import AmzServiceError

_LOGGER = logging.getLogger("amz.ads_oauth")

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
SCOPE = "advertising::campaign_management"
REDIRECT_URI = "https://ops.barongyekhna.com/amz/ads-callback"
AUTHORIZE_HOST_BY_REGION = {"na": "https://www.amazon.com/ap/oa", "eu": "https://eu.account.amazon.com/ap/oa", "fe": "https://apac.account.amazon.com/ap/oa"}
ADS_HOST_BY_REGION = {"na": "https://advertising-api.amazon.com", "eu": "https://advertising-api-eu.amazon.com", "fe": "https://advertising-api-fe.amazon.com"}
PENDING_KEY = "ads_oauth"
PENDING_TTL_SECONDS = 3600


def ads_alias(store_code: str) -> str:
    return f"{KEY_ALIAS_ADS_PREFIX}{store_code.lower()}"


def authorize_url(*, client_id: str, region: str, state: str, redirect_uri: str = REDIRECT_URI) -> str:
    base = AUTHORIZE_HOST_BY_REGION[region]
    return f"{base}?{urlencode({'client_id': client_id, 'scope': SCOPE, 'response_type': 'code', 'redirect_uri': redirect_uri, 'state': state})}"


def start(db: Session, *, store: AmzStore, client_id: str, client_secret: str, actor_user_id: int) -> str:
    """把钥匙对加密存进店铺 metadata,返回授权链接。不 commit。"""
    client_id, client_secret = client_id.strip(), client_secret.strip()
    if not client_id.startswith("amzn1.application-oa2-client.") or not client_secret.startswith("amzn1.oa2-cs."):
        raise AmzServiceError("钥匙对的样子不对:客户端编码以 amzn1.application-oa2-client. 开头,密钥以 amzn1.oa2-cs. 开头", status_code=422, code="amz_ads_client_pair_invalid")
    region = (store.region or "na").lower()
    if region not in AUTHORIZE_HOST_BY_REGION:
        raise AmzServiceError(f"unknown region {region}", status_code=422, code="amz_region_invalid")
    state = f"{store.store_code}.{secrets.token_urlsafe(18)}"
    meta = dict(store.metadata_json or {})
    meta[PENDING_KEY] = {
        "client_id": client_id,
        "client_secret_enc": _encrypt_key_value(client_secret),
        "state": state,
        "created_at": datetime.now(UTC).isoformat(),
        "by_user_id": actor_user_id,
    }
    store.metadata_json = meta
    db.add(store)
    db.flush()
    return authorize_url(client_id=client_id, region=region, state=state)


def parse_state(state: str) -> str:
    code, _, nonce = (state or "").partition(".")
    if not code or not nonce:
        raise AmzServiceError("state 不完整", status_code=422, code="amz_ads_state_invalid")
    return code.lower()


def exchange_code(client: httpx.Client, *, code: str, client_id: str, client_secret: str, redirect_uri: str = REDIRECT_URI) -> dict[str, Any]:
    response = client.post(LWA_TOKEN_URL, data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": client_id, "client_secret": client_secret})
    if response.status_code != 200:
        raise AmzServiceError(f"LWA 换令牌失败 HTTP {response.status_code}: {response.text[:200]}", status_code=502, code="amz_ads_token_exchange_failed")
    body = response.json()
    if not body.get("refresh_token") or not body.get("access_token"):
        raise AmzServiceError("LWA 没有返回刷新令牌", status_code=502, code="amz_ads_no_refresh_token")
    return body


def fetch_profiles(client: httpx.Client, *, region: str, access_token: str, client_id: str) -> list[dict[str, Any]]:
    response = client.get(f"{ADS_HOST_BY_REGION[region]}/v2/profiles", headers={"Authorization": f"Bearer {access_token}", "Amazon-Advertising-API-ClientId": client_id, "User-Agent": "BarongOpsConsole/0.1 (Language=Python)"})
    if response.status_code != 200:
        raise AmzServiceError(f"拉广告 profile 失败 HTTP {response.status_code}: {response.text[:200]}", status_code=502, code="amz_ads_profiles_failed")
    payload = response.json()
    return [p for p in payload if isinstance(p, dict)] if isinstance(payload, list) else []


def pick_profiles(profiles: list[dict[str, Any]], *, country: str) -> list[dict[str, Any]]:
    """这家店的国家、卖家类型的 profile。一家公司的广告账号可能带别国 profile(欧洲站一账号多国),只留本店的。"""
    out = []
    for p in profiles:
        if str(p.get("countryCode") or "").upper() != country.upper():
            continue
        if str((p.get("accountInfo") or {}).get("type") or "").lower() not in ("seller", "vendor", ""):
            continue
        out.append({"profileId": str(p.get("profileId")), "countryCode": p.get("countryCode"), "currencyCode": p.get("currencyCode"), "timezone": p.get("timezone"), "accountInfo": p.get("accountInfo")})
    return out


def _existing_key(db: Session, *, org_id: str, alias: str) -> ApiKeyRecord | None:
    binding = db.scalar(select(ApiKeyModuleBindingRecord).where(ApiKeyModuleBindingRecord.org_id == org_id, ApiKeyModuleBindingRecord.module_id == MODULE_KEY, ApiKeyModuleBindingRecord.key_alias == alias, ApiKeyModuleBindingRecord.status == "active"))
    if binding is None:
        return None
    return db.scalar(select(ApiKeyRecord).where(ApiKeyRecord.key_id == binding.key_id, ApiKeyRecord.status == "active"))


def complete(db: Session, *, code: str, state: str, actor_user_id: int, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """授权码 → 刷新令牌 → profile → 密钥管理。不 commit。"""
    store_code = parse_state(state)
    store = db.get(AmzStore, store_code)
    if store is None:
        raise AmzServiceError(f"unknown store {store_code}", status_code=404, code="amz_store_not_found")
    pending = dict((store.metadata_json or {}).get(PENDING_KEY) or {})
    if not pending or pending.get("state") != state:
        raise AmzServiceError("这条授权链接已过期或不是这家店的,请重新点「开始授权」", status_code=409, code="amz_ads_state_mismatch")
    started = datetime.fromisoformat(str(pending.get("created_at")))
    if (datetime.now(UTC) - started).total_seconds() > PENDING_TTL_SECONDS:
        raise AmzServiceError("授权链接已过期(一小时),请重新开始", status_code=409, code="amz_ads_state_expired")
    client_id = str(pending["client_id"])
    client_secret = _decrypt_key_value(str(pending["client_secret_enc"]))
    region = (store.region or "na").lower()

    with httpx.Client(timeout=30.0, transport=transport) as http:
        tokens = exchange_code(http, code=code, client_id=client_id, client_secret=client_secret)
        profiles = fetch_profiles(http, region=region, access_token=str(tokens["access_token"]), client_id=client_id)
    mine = pick_profiles(profiles, country=store.country)
    if not mine:
        raise AmzServiceError(f"这个广告账号下没有 {store.country} 的卖家 profile(共 {len(profiles)} 个 profile)。是不是用错了账号?", status_code=422, code="amz_ads_no_profile_for_store")

    payload = json.dumps({"client_id": client_id, "client_secret": client_secret, "refresh_token": tokens["refresh_token"], "region": region, "profile_ids": [p["profileId"] for p in mine], "profiles": mine}, ensure_ascii=False)
    alias = ads_alias(store.store_code)
    name = f"Amazon Ads API {store.display_name} {store.store_code}"
    with without_org_data_isolation():
        existing = _existing_key(db, org_id=store.company_org_id, alias=alias)
        if existing is not None:
            update_api_key(db, key_id=existing.key_id, payload=ApiKeyUpdateRequest(key_value=payload, name=name), actor_user_id=str(actor_user_id))
            key_id = existing.key_id
        else:
            key = create_api_key(db, org_id=store.company_org_id, payload=ApiKeyCreateRequest(name=name, url=ADS_HOST_BY_REGION[region], key_value=payload, key_type=KeyType.AMAZON_ADS_API), actor_user_id=str(actor_user_id))
            create_api_key_binding(db, org_id=store.company_org_id, payload=ApiKeyBindingCreateRequest(module_id=MODULE_KEY, key_id=key.key_id, key_alias=alias), actor_user_id=str(actor_user_id))
            key_id = key.key_id
    meta = dict(store.metadata_json or {})
    meta.pop(PENDING_KEY, None)
    meta["ads_connected_at"] = datetime.now(UTC).isoformat()
    meta["ads_profile_ids"] = [p["profileId"] for p in mine]
    store.metadata_json = meta
    db.add(store)
    db.flush()
    return {"store_code": store.store_code, "key_id": key_id, "alias": alias, "profiles": mine, "all_profiles": len(profiles)}


__all__ = ["ADS_HOST_BY_REGION", "REDIRECT_URI", "SCOPE", "ads_alias", "authorize_url", "complete", "exchange_code", "fetch_profiles", "parse_state", "pick_profiles", "start"]
