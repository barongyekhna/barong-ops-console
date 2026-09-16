"""SP-API 客户端:LWA 令牌缓存 + 限速退避 + 报表 create → poll → download → gunzip。

家规:
- 凭据从密钥管理取(公司组织 × amz.ops × alias sp_api),不落文件不进环境变量;
- 每店自报家门的 User-Agent、可选的出口 IP(``AMZ_EGRESS_IP_{STORE}`` 或 amz_stores.egress_ip);
- 只走官方 API;这里只有读端点,写端点等 A3 的执行器和梯子。

限速(官方):createReport 0.0167/s(突发 15)、getReport 2/s、getReportDocument 0.0167/s(突发 15)。
429 退避 2/4/8/16/32 秒,最多五次;401 重取一次令牌。
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

import httpx
from sqlalchemy.orm import Session

from ....services.api_key_orchestration import ApiKeyIsolationError, resolve_module_api_key_for_injection
from ....services.data_isolation import without_org_data_isolation
from ..constants import KEY_ALIAS_SP_API, MODULE_KEY
from ..models import AmzStore

_LOGGER = logging.getLogger("amz.sp_api")

LWA_URL = "https://api.amazon.com/auth/o2/token"
HOSTS_BY_REGION = {
    "na": "sellingpartnerapi-na.amazon.com",
    "eu": "sellingpartnerapi-eu.amazon.com",
    "fe": "sellingpartnerapi-fe.amazon.com",
}
REPORTS_PREFIX = "/reports/2021-06-30"
TOKEN_SAFETY_SECONDS = 60
MAX_RETRIES = 5
TERMINAL_STATUSES = ("DONE", "CANCELLED", "FATAL")


class SpApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class SpApiReportFailed(SpApiError):
    def __init__(self, report_type: str, status: str, details: str) -> None:
        super().__init__(f"{report_type} {status}: {details}", code=status)
        self.report_type = report_type
        self.report_status = status
        self.details = details


@dataclass(frozen=True)
class SpApiCredentials:
    client_id: str
    client_secret: str
    refresh_token: str
    region: str

    @classmethod
    def from_json(cls, raw: str) -> "SpApiCredentials":
        data = json.loads(raw)
        region = str(data.get("region") or "na").lower()
        if region not in HOSTS_BY_REGION:
            raise SpApiError(f"unknown region {region!r}", code="bad_region")
        for key in ("client_id", "client_secret", "refresh_token"):
            if not str(data.get(key) or "").strip():
                raise SpApiError(f"credential missing {key}", code="incomplete")
        return cls(str(data["client_id"]).strip(), str(data["client_secret"]).strip(), str(data["refresh_token"]).strip(), region)


def load_credentials(db: Session, store: AmzStore) -> SpApiCredentials:
    """密钥管理 → 凭据。api_keys 表带 org_id,worker 里没有会话组织,要显式关掉隔离。"""
    with without_org_data_isolation():
        ctx = resolve_module_api_key_for_injection(db, org_id=store.company_org_id, module_id=MODULE_KEY, key_alias=KEY_ALIAS_SP_API)
    return SpApiCredentials.from_json(ctx.header_value)


def has_credentials(db: Session, store: AmzStore) -> bool:
    try:
        load_credentials(db, store)
    except (ApiKeyIsolationError, SpApiError, ValueError):
        return False
    return True


def default_user_agent(store_code: str) -> str:
    return f"BarongOpsConsole-{store_code}/0.1 (Language=Python; Platform=Linux)"


def egress_ip_for(store: AmzStore) -> str | None:
    return (os.getenv(f"AMZ_EGRESS_IP_{store.store_code.upper()}") or store.egress_ip or "").strip() or None


class SpApiClient:
    def __init__(
        self,
        credentials: SpApiCredentials,
        *,
        store_code: str,
        marketplace_id: str,
        user_agent: str | None = None,
        egress_ip: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        timeout: float = 60.0,
    ) -> None:
        self.credentials = credentials
        self.store_code = store_code
        self.marketplace_id = marketplace_id
        self.user_agent = user_agent or default_user_agent(store_code)
        self.base_url = f"https://{HOSTS_BY_REGION[credentials.region]}"
        self._sleep = sleep
        self._clock = clock
        if transport is None and egress_ip:
            transport = httpx.HTTPTransport(local_address=egress_ip)
        self._http = httpx.Client(timeout=timeout, transport=transport)
        self._token: str | None = None
        self._token_expires_at = 0.0
        self.calls = 0

    @classmethod
    def for_store(cls, db: Session, store: AmzStore, **kwargs: Any) -> "SpApiClient":
        return cls(
            load_credentials(db, store),
            store_code=store.store_code,
            marketplace_id=store.marketplace_id,
            user_agent=store.user_agent or None,
            egress_ip=egress_ip_for(store),
            **kwargs,
        )

    def close(self) -> None:
        self._http.close()

    # ---------- LWA ----------

    def token(self, *, force: bool = False) -> str:
        if not force and self._token and self._clock() < self._token_expires_at - TOKEN_SAFETY_SECONDS:
            return self._token
        response = self._http.post(
            LWA_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.credentials.refresh_token,
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
            },
            headers={"User-Agent": self.user_agent},
        )
        if response.status_code != 200:
            raise SpApiError(f"LWA refresh rejected HTTP {response.status_code}: {response.text[:200]}", status=response.status_code, code="lwa_rejected")
        body = response.json()
        self._token = str(body.get("access_token") or "")
        if not self._token:
            raise SpApiError("LWA response without access_token", code="lwa_no_token")
        self._token_expires_at = self._clock() + float(body.get("expires_in") or 3600)
        return self._token

    # ---------- 通用请求 ----------

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        backoff = 2.0
        refreshed = False
        for attempt in range(MAX_RETRIES + 1):
            headers = {"x-amz-access-token": self.token(), "User-Agent": self.user_agent, "Accept": "application/json"}
            self.calls += 1
            response = self._http.request(method, url, params=params, json=json_body, headers=headers)
            if response.status_code == 401 and not refreshed:
                refreshed = True
                self.token(force=True)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= MAX_RETRIES:
                    raise SpApiError(f"{method} {path} HTTP {response.status_code} after retries", status=response.status_code, code="rate_limited" if response.status_code == 429 else "server_error")
                self._sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                continue
            if response.status_code >= 400:
                code, message = _error_of(response)
                raise SpApiError(f"{method} {path} HTTP {response.status_code} {code}: {message}", status=response.status_code, code=code)
            return response.json() if response.content else {}
        raise SpApiError(f"{method} {path} gave up", code="gave_up")

    # ---------- 报表 ----------

    def create_report(self, report_type: str, *, start: date, end: date, options: dict[str, Any] | None = None, marketplace_ids: list[str] | None = None) -> str:
        body: dict[str, Any] = {
            "reportType": report_type,
            "marketplaceIds": marketplace_ids or [self.marketplace_id],
            "dataStartTime": start.isoformat(),
            "dataEndTime": end.isoformat(),
        }
        if options:
            body["reportOptions"] = options
        payload = self.request("POST", f"{REPORTS_PREFIX}/reports", json_body=body)
        report_id = str(payload.get("reportId") or "")
        if not report_id:
            raise SpApiError(f"createReport returned no reportId: {payload}", code="no_report_id")
        return report_id

    def get_report(self, report_id: str) -> dict[str, Any]:
        return self.request("GET", f"{REPORTS_PREFIX}/reports/{report_id}")

    def get_document(self, document_id: str) -> dict[str, Any]:
        return self.request("GET", f"{REPORTS_PREFIX}/documents/{document_id}")

    def download(self, document: dict[str, Any]) -> bytes:
        response = self._http.get(str(document["url"]), headers={"User-Agent": self.user_agent})
        response.raise_for_status()
        raw = response.content
        if str(document.get("compressionAlgorithm") or "").upper() == "GZIP":
            raw = gzip.decompress(raw)
        return raw

    def wait_report(self, report_id: str, *, poll_seconds: float = 15.0, max_wait: float = 1800.0) -> dict[str, Any]:
        deadline = self._clock() + max_wait
        while True:
            status = self.get_report(report_id)
            state = str(status.get("processingStatus") or "")
            if state in TERMINAL_STATUSES:
                return status
            if self._clock() >= deadline:
                raise SpApiError(f"report {report_id} still {state} after {max_wait:.0f}s", code="report_timeout")
            self._sleep(poll_seconds)

    def run_report(self, report_type: str, *, start: date, end: date, options: dict[str, Any] | None = None, poll_seconds: float = 15.0, max_wait: float = 1800.0) -> tuple[str, Any]:
        """创建 → 等 → 下载 → 解析 JSON。FATAL/CANCELLED 时把亚马逊的 errorDetails 抛出来(它藏在文档里)。"""
        report_id = self.create_report(report_type, start=start, end=end, options=options)
        status = self.wait_report(report_id, poll_seconds=poll_seconds, max_wait=max_wait)
        state = str(status.get("processingStatus"))
        document_id = str(status.get("reportDocumentId") or "")
        raw = self.download(self.get_document(document_id)) if document_id else b""
        if state != "DONE":
            details = ""
            try:
                details = str(json.loads(raw or b"{}").get("errorDetails") or "")
            except (TypeError, ValueError):
                details = raw[:300].decode("utf-8", errors="replace")
            raise SpApiReportFailed(report_type, state, details or "(no details)")
        try:
            return report_id, json.loads(raw)
        except ValueError:
            return report_id, raw.decode("utf-8", errors="replace")


def _error_of(response: httpx.Response) -> tuple[str, str]:
    try:
        errors = response.json().get("errors") or []
    except ValueError:
        return "http_error", response.text[:200]
    if errors and isinstance(errors[0], dict):
        return str(errors[0].get("code") or "http_error"), str(errors[0].get("message") or "")[:200]
    return "http_error", response.text[:200]


__all__ = [
    "HOSTS_BY_REGION",
    "SpApiClient",
    "SpApiCredentials",
    "SpApiError",
    "SpApiReportFailed",
    "default_user_agent",
    "egress_ip_for",
    "has_credentials",
    "load_credentials",
]
