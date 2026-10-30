"""谷歌服务账号(service account)换 access token(10-30,苏青禾接 Search Console 用)。

服务账号 JSON 钥匙里有 client_email / private_key / token_uri;拿私钥签一个 RS256 的 JWT,POST 到 token_uri 换 1 小时的 access token。
不装 google-auth(镜像里没有,也不想为一个接口拖一整套 SDK):只用 `cryptography` 签名 + httpx。
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

TOKEN_URI_DEFAULT = "https://oauth2.googleapis.com/token"
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
REQUIRED_FIELDS = ("type", "client_email", "private_key", "token_uri")


class ServiceAccountError(RuntimeError):
    """钥匙 JSON 不对、签名失败、换 token 被拒都走这个。"""


@dataclass(frozen=True)
class ServiceAccount:
    client_email: str
    private_key_pem: str
    token_uri: str
    project_id: str


def parse_service_account(raw: str | dict[str, Any]) -> ServiceAccount:
    """钥匙 JSON → 结构;缺字段、不是 service_account 类型 → ServiceAccountError。"""
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError) as exc:
        raise ServiceAccountError("json_invalid") from exc
    if not isinstance(payload, dict):
        raise ServiceAccountError("json_invalid")
    missing = [f for f in REQUIRED_FIELDS if not str(payload.get(f) or "").strip()]
    if missing:
        raise ServiceAccountError("json_missing_fields:" + ",".join(missing))
    if str(payload.get("type")).strip() != "service_account":
        raise ServiceAccountError("not_service_account")
    pem = str(payload["private_key"]).replace("\\n", "\n")
    if "PRIVATE KEY" not in pem:
        raise ServiceAccountError("private_key_invalid")
    return ServiceAccount(
        client_email=str(payload["client_email"]).strip(),
        private_key_pem=pem,
        token_uri=str(payload.get("token_uri") or TOKEN_URI_DEFAULT).strip(),
        project_id=str(payload.get("project_id") or "").strip(),
    )


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_assertion(account: ServiceAccount, *, scope: str, now: float | None = None, lifetime_s: int = 3600) -> str:
    """RS256 签名的 JWT(header.claims.signature)。exp 最多 1 小时,这是谷歌的上限。"""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as exc:  # pragma: no cover —— 镜像里没装 cryptography 就明说
        raise ServiceAccountError("cryptography_missing") from exc

    issued = int(now if now is not None else time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iss": account.client_email, "scope": scope, "aud": account.token_uri, "iat": issued, "exp": issued + min(max(60, lifetime_s), 3600)}
    signing_input = f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}.{_b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    try:
        key = serialization.load_pem_private_key(account.private_key_pem.encode(), password=None)
        signature = key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:  # noqa: BLE001 —— 私钥坏了
        raise ServiceAccountError("private_key_invalid") from exc
    return f"{signing_input}.{_b64url(signature)}"


def decode_claims(assertion: str) -> dict[str, Any]:
    """只给测试和排错用:把 JWT 的 claims 段解回来(不验签)。"""
    part = assertion.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def fetch_access_token(account: ServiceAccount, *, scope: str, transport: httpx.BaseTransport | None = None, timeout: float = 15.0) -> tuple[str, int]:
    """(access_token, expires_in 秒)。谷歌不给 token 或非 200 → ServiceAccountError。"""
    assertion = build_assertion(account, scope=scope)
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=5.0), trust_env=False, transport=transport) as client:
        response = client.post(account.token_uri, data={"grant_type": JWT_BEARER_GRANT, "assertion": assertion})
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    token = str((payload or {}).get("access_token") or "").strip() if isinstance(payload, dict) else ""
    if response.status_code != 200 or not token:
        detail = (payload or {}).get("error_description") or (payload or {}).get("error") if isinstance(payload, dict) else ""
        raise ServiceAccountError(f"token_rejected:{response.status_code}:{str(detail)[:120]}")
    return token, int((payload or {}).get("expires_in") or 3600)
