"""Minimal, read-only provider probes with strict outbound host validation."""

from __future__ import annotations

import ipaddress
import json
import socket
from base64 import b64encode
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


HEALTHY = "healthy"
WARNING_STATUSES = frozenset(("pending_review", "rate_limited"))
FAILURE_STATUSES = frozenset(
    ("invalid", "malformed", "provider_error", "unreachable", "unsupported")
)

FOUR_S_API_HOSTS = frozenset(("4sapi.com", "www.4sapi.com"))
DEEPSEEK_HOSTS = frozenset(("api.deepseek.com",))
SERPER_HOSTS = frozenset(("google.serper.dev",))
KEEPA_HOSTS = frozenset(("api.keepa.com",))
# 独立站 WP 桥凭据(H 站点健康):单站点系统,站点域名与全后端其它硬编码一致
WORDPRESS_HOSTS = frozenset(("barongyekhna.com", "www.barongyekhna.com"))
TRACK17_HOSTS = frozenset(("api.17track.net",))
RAINFOREST_HOSTS = frozenset(("api.rainforestapi.com",))
ALIBABA_HOSTS = frozenset(("gw.open.1688.com",))
GOOGLE_OAUTH_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ADS_API_ROOT = "https://googleads.googleapis.com"
GOOGLE_ADS_HEALTH_VERSION = "v24"


@dataclass(frozen=True)
class ProbeTarget:
    key_id: str
    org_id: str
    name: str
    url: str
    key_hash_prefix: str
    key_type: str
    aliases: tuple[str, ...]
    secret_value: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    load_error: str | None = None


@dataclass(frozen=True)
class ProbeResult:
    adapter: str
    status: str
    reason_code: str
    latency_ms: int
    checked_at: datetime
    http_status: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


class UnsafeProbeTarget(ValueError):
    pass


def _host(value: str) -> str:
    return (urlsplit(value).hostname or "").lower().rstrip(".")


def _normalized_aliases(target: ProbeTarget) -> set[str]:
    return {
        str(value).strip().lower().replace("-", "_")
        for value in target.aliases
        if str(value).strip()
    }


def adapter_for_target(target: ProbeTarget) -> str:
    key_type = target.key_type.strip().lower().replace("-", "_")
    aliases = _normalized_aliases(target)
    hostname = _host(target.url)

    if key_type == "google_ads":
        return "google_ads"
    if key_type == "alibaba1688":
        return "alibaba1688"
    if key_type == "keepa" or hostname in KEEPA_HOSTS or "keepa" in aliases:
        return "keepa"
    if (
        key_type == "rainforest"
        or hostname in RAINFOREST_HOSTS
        or "rainforest" in aliases
    ):
        return "rainforest"
    if key_type == "serp" or hostname in SERPER_HOSTS or aliases & {"serp", "serper"}:
        return "serper"
    if (
        key_type == "deepseek"
        or hostname in DEEPSEEK_HOSTS
        or "deepseek" in aliases
    ):
        return "deepseek"
    if hostname in FOUR_S_API_HOSTS:
        return "4sapi_openai_compatible"
    if aliases & {"chatgpt", "claude", "claude_opus", "4sapi"}:
        return "blocked_proxy_route"
    if key_type in {"openai", "chatgpt", "claude_opus"}:
        return "blocked_proxy_route"
    if key_type == "n8n" or "n8n" in aliases:
        return "n8n"
    if key_type == "wordpress" or "wordpress" in aliases:
        return "wordpress"
    if key_type == "track17" or "track17" in aliases or hostname in TRACK17_HOSTS:
        return "track17"
    return "unsupported"


def _public_addresses(hostname: str, port: int) -> tuple[str, ...]:
    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        }
    except OSError as exc:
        raise UnsafeProbeTarget("dns_resolution_failed") from exc
    if not addresses:
        raise UnsafeProbeTarget("dns_resolution_failed")
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise UnsafeProbeTarget("dns_address_invalid") from exc
        if not parsed.is_global:
            raise UnsafeProbeTarget("non_public_destination")
    return tuple(sorted(addresses))


def _validate_url(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    enforce_public_network: bool,
) -> str:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https":
        raise UnsafeProbeTarget("https_required")
    if hostname not in allowed_hosts:
        raise UnsafeProbeTarget("provider_host_mismatch")
    if parsed.username or parsed.password or parsed.fragment:
        raise UnsafeProbeTarget("url_credentials_or_fragment_forbidden")
    if enforce_public_network:
        _public_addresses(hostname, parsed.port or 443)
    return url


def _request(
    method: str,
    url: str,
    *,
    allowed_hosts: frozenset[str],
    enforce_public_network: bool,
    transport: httpx.BaseTransport | None,
    **kwargs: Any,
) -> httpx.Response:
    _validate_url(
        url,
        allowed_hosts=allowed_hosts,
        enforce_public_network=enforce_public_network,
    )
    timeout = httpx.Timeout(12.0, connect=5.0)
    with httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        transport=transport,
    ) as client:
        return client.request(method, url, **kwargs)


def _json_dict(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _finish(
    *,
    adapter: str,
    started: float,
    status: str,
    reason_code: str,
    http_status: int | None = None,
    details: dict[str, Any] | None = None,
) -> ProbeResult:
    return ProbeResult(
        adapter=adapter,
        status=status,
        reason_code=reason_code,
        latency_ms=max(0, round((perf_counter() - started) * 1000)),
        checked_at=datetime.now(UTC),
        http_status=http_status,
        details=details or {},
    )


def _status_from_http(
    *,
    adapter: str,
    started: float,
    response: httpx.Response,
    success_reason: str,
    details: dict[str, Any] | None = None,
) -> ProbeResult:
    if 200 <= response.status_code < 300:
        return _finish(
            adapter=adapter,
            started=started,
            status=HEALTHY,
            reason_code=success_reason,
            http_status=response.status_code,
            details=details,
        )
    if response.status_code in {401, 403}:
        status, reason = "invalid", "authentication_rejected"
    elif response.status_code == 402:
        # OpenAI 兼容口的「余额不足」（DeepSeek: {"error":{"message":"Insufficient Balance"}}）。
        status, reason = "provider_error", "provider_credits_exhausted"
    elif response.status_code == 429:
        status, reason = "rate_limited", "provider_rate_limited"
    elif response.status_code >= 500:
        status, reason = "provider_error", "provider_server_error"
    else:
        status, reason = "provider_error", "unexpected_provider_response"
    return _finish(
        adapter=adapter,
        started=started,
        status=status,
        reason_code=reason,
        http_status=response.status_code,
    )


def _models_url(base_url: str, *, force_four_s_api: bool = False) -> str:
    parsed = urlsplit(base_url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    scheme = "https" if force_four_s_api and hostname in FOUR_S_API_HOSTS else parsed.scheme
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = f"{path}/models"
    else:
        path = f"{path}/v1/models" if force_four_s_api else f"{path}/models"
    return urlunsplit((scheme, parsed.netloc, path, "", ""))


def _probe_openai_compatible(
    target: ProbeTarget,
    *,
    adapter: str,
    allowed_hosts: frozenset[str],
    force_four_s_api: bool,
    enforce_public_network: bool,
    transport: httpx.BaseTransport | None,
) -> ProbeResult:
    started = perf_counter()
    response = _request(
        "GET",
        _models_url(target.url, force_four_s_api=force_four_s_api),
        allowed_hosts=allowed_hosts,
        enforce_public_network=enforce_public_network,
        transport=transport,
        headers={"Authorization": f"Bearer {target.secret_value}"},
    )
    details: dict[str, Any] = {}
    payload = _json_dict(response)
    if response.status_code == 200:
        models = payload.get("data") if payload else None
        if not isinstance(models, list):
            return _finish(
                adapter=adapter,
                started=started,
                status="provider_error",
                reason_code="models_response_invalid",
                http_status=response.status_code,
            )
        details["models_visible"] = len(models)
        if adapter == "deepseek":
            # models 列表在余额 0 时照样 200（2026-09-04 假绿 17.5 万条 402），
            # 再查一次零消耗的 /user/balance 才算真健康。
            balance_result = _deepseek_balance_check(
                target,
                adapter=adapter,
                started=started,
                details=details,
                enforce_public_network=enforce_public_network,
                transport=transport,
            )
            if balance_result is not None:
                return balance_result
    return _status_from_http(
        adapter=adapter,
        started=started,
        response=response,
        success_reason="models_list_ok",
        details=details,
    )


def _deepseek_balance_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/user/balance", "", ""))


def _deepseek_balance_check(
    target: ProbeTarget,
    *,
    adapter: str,
    started: float,
    details: dict[str, Any],
    enforce_public_network: bool,
    transport: httpx.BaseTransport | None,
) -> ProbeResult | None:
    """DeepSeek 余额：GET /user/balance → {"is_available": bool, "balance_infos": [...]}.

    余额为 0 或 is_available=false → provider_error/provider_credits_exhausted。
    余额接口本身不通（非 200 / 解析失败）不算探针失败，只在 details 里记一笔，
    让 models 列表的判定照旧。
    """
    try:
        response = _request(
            "GET",
            _deepseek_balance_url(target.url),
            allowed_hosts=DEEPSEEK_HOSTS,
            enforce_public_network=enforce_public_network,
            transport=transport,
            headers={"Authorization": f"Bearer {target.secret_value}"},
        )
    except Exception:
        details["balance_probe"] = "unreachable"
        return None
    if response.status_code == 402:
        details["balance_probe"] = "http_402"
        return _finish(
            adapter=adapter,
            started=started,
            status="provider_error",
            reason_code="provider_credits_exhausted",
            http_status=402,
            details=details,
        )
    payload = _json_dict(response)
    if response.status_code != 200 or payload is None:
        details["balance_probe"] = f"http_{response.status_code}"
        return None
    infos = payload.get("balance_infos")
    total_balance: float | None = None
    currency: str | None = None
    if isinstance(infos, list):
        for item in infos:
            if not isinstance(item, dict):
                continue
            try:
                value = float(str(item.get("total_balance", "")).strip() or "nan")
            except ValueError:
                continue
            if value != value:  # NaN
                continue
            if total_balance is None or value > total_balance:
                total_balance = value
                currency = str(item.get("currency") or "") or None
    available = payload.get("is_available")
    details["balance"] = {"currency": currency, "total_balance": total_balance}
    details["balance_probe"] = "ok"
    exhausted = available is False or (total_balance is not None and total_balance <= 0)
    if exhausted:
        return _finish(
            adapter=adapter,
            started=started,
            status="provider_error",
            reason_code="provider_credits_exhausted",
            http_status=200,
            details=details,
        )
    return None


def _probe_serper(
    target: ProbeTarget,
    *,
    enforce_public_network: bool,
    transport: httpx.BaseTransport | None,
) -> ProbeResult:
    started = perf_counter()
    response = _request(
        "POST",
        "https://google.serper.dev/search",
        allowed_hosts=SERPER_HOSTS,
        enforce_public_network=enforce_public_network,
        transport=transport,
        headers={"X-API-KEY": str(target.secret_value), "Content-Type": "application/json"},
        json={"q": "barong key health", "num": 1},
    )
    if response.status_code == 200 and _json_dict(response) is None:
        return _finish(
            adapter="serper",
            started=started,
            status="provider_error",
            reason_code="search_response_invalid",
            http_status=200,
        )
    if response.status_code == 400:
        # Serper 额度耗尽走 400 {"message": "Not enough credits"}——
        # 给出可行动的 reason(充值),别混进笼统的 unexpected_provider_response
        payload = _json_dict(response) or {}
        if "not enough credits" in str(payload.get("message", "")).lower():
            return _finish(
                adapter="serper",
                started=started,
                status="provider_error",
                reason_code="provider_credits_exhausted",
                http_status=400,
            )
    return _status_from_http(
        adapter="serper",
        started=started,
        response=response,
        success_reason="minimal_search_ok",
        details={"credits_used_by_probe": 1} if response.status_code == 200 else None,
    )


def _probe_keepa(
    target: ProbeTarget,
    *,
    enforce_public_network: bool,
    transport: httpx.BaseTransport | None,
) -> ProbeResult:
    started = perf_counter()
    response = _request(
        "GET",
        "https://api.keepa.com/token",
        allowed_hosts=KEEPA_HOSTS,
        enforce_public_network=enforce_public_network,
        transport=transport,
        params={"key": target.secret_value},
    )
    details: dict[str, Any] = {}
    payload = _json_dict(response)
    if response.status_code == 200:
        if payload is None:
            return _finish(
                adapter="keepa",
                started=started,
                status="provider_error",
                reason_code="token_response_invalid",
                http_status=200,
            )
        for source, destination in (
            ("tokensLeft", "tokens_left"),
            ("refillRate", "refill_rate"),
            ("refillIn", "refill_in_ms"),
        ):
            value = payload.get(source)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                details[destination] = value
    return _status_from_http(
        adapter="keepa",
        started=started,
        response=response,
        success_reason="token_status_ok",
        details=details,
    )


def _probe_rainforest(
    target: ProbeTarget,
    *,
    enforce_public_network: bool,
    transport: httpx.BaseTransport | None,
) -> ProbeResult:
    started = perf_counter()
    response = _request(
        "GET",
        "https://api.rainforestapi.com/account",
        allowed_hosts=RAINFOREST_HOSTS,
        enforce_public_network=enforce_public_network,
        transport=transport,
        params={"api_key": target.secret_value},
    )
    if response.status_code == 200 and _json_dict(response) is None:
        return _finish(
            adapter="rainforest",
            started=started,
            status="provider_error",
            reason_code="account_response_invalid",
            http_status=200,
        )
    return _status_from_http(
        adapter="rainforest",
        started=started,
        response=response,
        success_reason="account_status_ok",
    )


def _parse_secret_json(target: ProbeTarget) -> dict[str, Any] | None:
    try:
        payload = json.loads(str(target.secret_value or ""))
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _google_pending_response(response: httpx.Response) -> bool:
    if response.status_code not in {401, 403}:
        return False
    body = response.text[:4000].upper()
    return any(
        marker in body
        for marker in (
            "DEVELOPER_TOKEN_NOT_APPROVED",
            "DEVELOPER_TOKEN_PROHIBITED",
            "DEVELOPER_TOKEN",
            "BASIC ACCESS",
            "TEST ACCOUNT",
        )
    )


def _probe_google_ads(
    target: ProbeTarget,
    *,
    enforce_public_network: bool,
    transport: httpx.BaseTransport | None,
) -> ProbeResult:
    adapter = "google_ads"
    started = perf_counter()
    payload = _parse_secret_json(target)
    required = (
        "developer_token",
        "client_id",
        "client_secret",
        "refresh_token",
        "customer_id",
    )
    if payload is None or any(not str(payload.get(key) or "").strip() for key in required):
        return _finish(
            adapter=adapter,
            started=started,
            status="malformed",
            reason_code="oauth_payload_incomplete",
        )
    oauth_response = _request(
        "POST",
        GOOGLE_OAUTH_URL,
        allowed_hosts=frozenset(("oauth2.googleapis.com",)),
        enforce_public_network=enforce_public_network,
        transport=transport,
        data={
            "client_id": str(payload["client_id"]),
            "client_secret": str(payload["client_secret"]),
            "refresh_token": str(payload["refresh_token"]),
            "grant_type": "refresh_token",
        },
    )
    oauth_payload = _json_dict(oauth_response)
    access_token = str((oauth_payload or {}).get("access_token") or "").strip()
    if oauth_response.status_code != 200 or not access_token:
        return _finish(
            adapter=adapter,
            started=started,
            status="invalid" if oauth_response.status_code < 500 else "provider_error",
            reason_code="oauth_refresh_rejected",
            http_status=oauth_response.status_code,
        )

    customer_id = str(payload["customer_id"]).replace("-", "").strip()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": str(payload["developer_token"]),
        "Content-Type": "application/json",
    }
    login_customer_id = str(payload.get("login_customer_id") or "").replace("-", "").strip()
    if login_customer_id:
        headers["login-customer-id"] = login_customer_id
    probe_response = _request(
        "POST",
        f"{GOOGLE_ADS_API_ROOT}/{GOOGLE_ADS_HEALTH_VERSION}/customers/"
        f"{customer_id}:generateKeywordIdeas",
        allowed_hosts=frozenset(("googleads.googleapis.com",)),
        enforce_public_network=enforce_public_network,
        transport=transport,
        headers=headers,
        json={
            "language": "languageConstants/1000",
            "geoTargetConstants": ["geoTargetConstants/2840"],
            "keywordSeed": {"keywords": ["health check"]},
            "pageSize": 1,
        },
    )
    if _google_pending_response(probe_response):
        return _finish(
            adapter=adapter,
            started=started,
            status="pending_review",
            reason_code="basic_access_review_pending",
            http_status=probe_response.status_code,
            details={"oauth_valid": True, "api_version": GOOGLE_ADS_HEALTH_VERSION},
        )
    return _status_from_http(
        adapter=adapter,
        started=started,
        response=probe_response,
        success_reason="keyword_ideas_probe_ok",
        details={"oauth_valid": True, "api_version": GOOGLE_ADS_HEALTH_VERSION},
    )


def _expiry_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return _expiry_timestamp(float(text))
        except ValueError:
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _probe_alibaba1688(
    target: ProbeTarget,
    *,
    enforce_public_network: bool,
    transport: httpx.BaseTransport | None,
) -> ProbeResult:
    adapter = "alibaba1688"
    started = perf_counter()
    payload = _parse_secret_json(target)
    aliases = {
        "app_key": ("app_key", "appKey"),
        "app_secret": ("app_secret", "appSecret"),
        "access_token": ("access_token", "accessToken"),
    }
    if payload is None or any(
        not any(str(payload.get(field) or "").strip() for field in fields)
        for fields in aliases.values()
    ):
        return _finish(
            adapter=adapter,
            started=started,
            status="malformed",
            reason_code="credential_payload_incomplete",
        )
    expires_at = payload.get("expires_at") or payload.get("expiresAt")
    expiry = _expiry_timestamp(expires_at)
    if expires_at is not None and expiry is None:
        return _finish(
            adapter=adapter,
            started=started,
            status="malformed",
            reason_code="credential_expiry_invalid",
        )
    if expiry is not None and expiry <= datetime.now(UTC):
        return _finish(
            adapter=adapter,
            started=started,
            status="invalid",
            reason_code="access_token_expired",
        )

    # 1688 exposes no stable zero-cost credential introspection endpoint. The
    # monitor validates the complete credential envelope and official gateway;
    # business API calls remain exclusively in R-A to avoid consuming quota.
    response = _request(
        "GET",
        "https://gw.open.1688.com",
        allowed_hosts=ALIBABA_HOSTS,
        enforce_public_network=enforce_public_network,
        transport=transport,
    )
    if response.status_code >= 500:
        return _finish(
            adapter=adapter,
            started=started,
            status="provider_error",
            reason_code="gateway_server_error",
            http_status=response.status_code,
        )
    return _finish(
        adapter=adapter,
        started=started,
        status=HEALTHY,
        reason_code="credential_structure_and_gateway_ok",
        http_status=response.status_code,
        details={
            "credential_fields_valid": True,
            "gateway_reachable": True,
            "check_depth": "non_consuming",
        },
    )


def _probe_n8n(
    target: ProbeTarget,
    *,
    enforce_public_network: bool,
    transport: httpx.BaseTransport | None,
) -> ProbeResult:
    adapter = "n8n"
    started = perf_counter()
    parsed = urlsplit(target.url)
    if not parsed.path.rstrip("/").endswith("/api/v1"):
        return _finish(
            adapter=adapter,
            started=started,
            status="unsupported",
            reason_code="non_mutating_probe_not_configured",
        )
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        return _finish(
            adapter=adapter,
            started=started,
            status="malformed",
            reason_code="provider_url_invalid",
        )
    url = urlunsplit(("https", parsed.netloc, f"{parsed.path.rstrip('/')}/workflows", "limit=1", ""))
    response = _request(
        "GET",
        url,
        allowed_hosts=frozenset((hostname,)),
        enforce_public_network=enforce_public_network,
        transport=transport,
        headers={"X-N8N-API-KEY": str(target.secret_value)},
    )
    return _status_from_http(
        adapter=adapter,
        started=started,
        response=response,
        success_reason="workflow_list_ok",
    )


def _probe_wordpress(
    target: ProbeTarget,
    *,
    enforce_public_network: bool,
    transport: httpx.BaseTransport | None,
) -> ProbeResult:
    """WP 桥凭据最小检测:Basic Auth 打 /wp-json/wp/v2/users/me(只读)。

    密钥值是 JSON {"base_url","user","app_password"}(H 站点健康 WP 桥口径)。
    """

    adapter = "wordpress"
    started = perf_counter()
    try:
        payload = json.loads(str(target.secret_value))
    except (TypeError, ValueError):
        payload = None
    if not isinstance(payload, dict):
        return _finish(
            adapter=adapter,
            started=started,
            status="malformed",
            reason_code="wordpress_secret_not_json",
        )
    base_url = str(payload.get("base_url") or "").strip().rstrip("/")
    user = str(payload.get("user") or "").strip()
    app_password = str(payload.get("app_password") or "").strip()
    if not base_url or not user or not app_password:
        return _finish(
            adapter=adapter,
            started=started,
            status="malformed",
            reason_code="wordpress_secret_fields_missing",
        )
    token = b64encode(f"{user}:{app_password}".encode("utf-8")).decode("ascii")
    response = _request(
        "GET",
        f"{base_url}/wp-json/wp/v2/users/me",
        allowed_hosts=WORDPRESS_HOSTS,
        enforce_public_network=enforce_public_network,
        transport=transport,
        headers={"Authorization": f"Basic {token}"},
    )
    return _status_from_http(
        adapter=adapter,
        started=started,
        response=response,
        success_reason="wp_auth_ok",
    )


def _probe_track17(
    target: ProbeTarget,
    *,
    enforce_public_network: bool,
    transport: httpx.BaseTransport | None,
) -> ProbeResult:
    """17TRACK 最小检测:打 getquota 额度接口(零消耗,只验 17token)。

    17TRACK 的鉴权失败通常也回 HTTP 200,错误码在 body 的 code 字段
    (-1801xxxx 段为密钥/鉴权类错误)。
    """

    adapter = "track17"
    started = perf_counter()
    response = _request(
        "POST",
        "https://api.17track.net/track/v2.2/getquota",
        allowed_hosts=TRACK17_HOSTS,
        enforce_public_network=enforce_public_network,
        transport=transport,
        headers={
            "17token": str(target.secret_value),
            "Content-Type": "application/json",
        },
        json={},
    )
    if response.status_code == 200:
        payload = _json_dict(response) or {}
        code = payload.get("code")
        if code == 0:
            return _finish(
                adapter=adapter,
                started=started,
                status=HEALTHY,
                reason_code="quota_ok",
                http_status=200,
            )
        # 只有鉴权段(-181000xx,如 -18010002=key 不存在)才判密钥失效;
        # -1801 段靠后的编号(如额度类)一律 provider_error,避免误报换钥匙。
        if isinstance(code, int) and -18010099 <= code <= -18010000:
            return _finish(
                adapter=adapter,
                started=started,
                status="invalid",
                reason_code="authentication_rejected",
                http_status=200,
            )
        return _finish(
            adapter=adapter,
            started=started,
            status="provider_error",
            reason_code=f"track17_code_{code}",
            http_status=200,
        )
    return _status_from_http(
        adapter=adapter,
        started=started,
        response=response,
        success_reason="quota_ok",
    )


def probe_target(
    target: ProbeTarget,
    *,
    enforce_public_network: bool = True,
    transport: httpx.BaseTransport | None = None,
) -> ProbeResult:
    adapter = adapter_for_target(target)
    started = perf_counter()
    if target.load_error or not str(target.secret_value or "").strip():
        return _finish(
            adapter=adapter,
            started=started,
            status="malformed",
            reason_code=target.load_error or "empty_secret",
        )
    if adapter == "blocked_proxy_route":
        return _finish(
            adapter=adapter,
            started=started,
            status="malformed",
            reason_code="required_4sapi_proxy_route_missing",
        )
    if adapter == "4sapi_openai_compatible":
        return _probe_openai_compatible(
            target,
            adapter=adapter,
            allowed_hosts=FOUR_S_API_HOSTS,
            force_four_s_api=True,
            enforce_public_network=enforce_public_network,
            transport=transport,
        )
    if adapter == "deepseek":
        return _probe_openai_compatible(
            target,
            adapter=adapter,
            allowed_hosts=DEEPSEEK_HOSTS,
            force_four_s_api=False,
            enforce_public_network=enforce_public_network,
            transport=transport,
        )
    if adapter == "serper":
        return _probe_serper(
            target,
            enforce_public_network=enforce_public_network,
            transport=transport,
        )
    if adapter == "keepa":
        return _probe_keepa(
            target,
            enforce_public_network=enforce_public_network,
            transport=transport,
        )
    if adapter == "rainforest":
        return _probe_rainforest(
            target,
            enforce_public_network=enforce_public_network,
            transport=transport,
        )
    if adapter == "google_ads":
        return _probe_google_ads(
            target,
            enforce_public_network=enforce_public_network,
            transport=transport,
        )
    if adapter == "alibaba1688":
        return _probe_alibaba1688(
            target,
            enforce_public_network=enforce_public_network,
            transport=transport,
        )
    if adapter == "n8n":
        return _probe_n8n(
            target,
            enforce_public_network=enforce_public_network,
            transport=transport,
        )
    if adapter == "wordpress":
        return _probe_wordpress(
            target,
            enforce_public_network=enforce_public_network,
            transport=transport,
        )
    if adapter == "track17":
        return _probe_track17(
            target,
            enforce_public_network=enforce_public_network,
            transport=transport,
        )
    return _finish(
        adapter=adapter,
        started=started,
        status="unsupported",
        reason_code="probe_adapter_not_available",
    )


def safe_probe_target(target: ProbeTarget) -> ProbeResult:
    """Never return an exception string because provider errors can contain secrets."""

    started = perf_counter()
    adapter = adapter_for_target(target)
    try:
        return probe_target(target)
    except UnsafeProbeTarget as exc:
        return _finish(
            adapter=adapter,
            started=started,
            status="malformed" if str(exc) != "dns_resolution_failed" else "unreachable",
            reason_code=str(exc),
        )
    except (httpx.TimeoutException, httpx.NetworkError):
        return _finish(
            adapter=adapter,
            started=started,
            status="unreachable",
            reason_code="provider_network_error",
        )
    except httpx.HTTPError:
        return _finish(
            adapter=adapter,
            started=started,
            status="provider_error",
            reason_code="provider_http_error",
        )
    except Exception:
        return _finish(
            adapter=adapter,
            started=started,
            status="provider_error",
            reason_code="probe_internal_error",
        )
