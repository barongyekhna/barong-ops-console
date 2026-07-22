"""Narrow WordPress bridge used by the H site-health control surface.

This module is the only backend location that resolves or sends WordPress
credentials.  Its public functions return a stable ``reachable`` envelope for
network/configuration failures so operator pages can degrade without a 500.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
import urllib.request

from r_system_v2.core.secret_manager import SecretManager


WP_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
ALLOWED_OPTIONS = frozenset({"barong_redirect_map"})

PING_QUERIES: dict[str, tuple[str, bool]] = {
    "redirects": ("by-rd-ping", True),
    "email-brand": ("by-eb-ping", True),
    "perf": ("by-pf-ping", True),
    "related": ("by-rg-ping", True),
    "track": ("by-track-ping", True),
    "email-verify": ("by-ev-ping", False),
}


@dataclass(frozen=True, repr=False)
class _WordPressCredentials:
    base_url: str
    user: str
    app_password: str


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        del req, fp, code, msg, headers, newurl
        return None


def _option_name(name: str) -> str:
    normalized = str(name or "").strip()
    if normalized not in ALLOWED_OPTIONS:
        raise ValueError(f"wordpress_option_not_allowed:{normalized}")
    return normalized


def _normalized_base_url(value: object) -> str | None:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _credentials_from_mapping(payload: object) -> _WordPressCredentials | None:
    if not isinstance(payload, dict):
        return None
    base_url = _normalized_base_url(payload.get("base_url"))
    user = str(payload.get("user") or "").strip()
    app_password = str(payload.get("app_password") or "").strip()
    if not base_url or not user or not app_password:
        return None
    return _WordPressCredentials(base_url, user, app_password)


def _resolve_credentials(
    *,
    db: Any | None = None,
    org_id: str | None = None,
) -> _WordPressCredentials | None:
    normalized_org_id = str(org_id or "").strip()
    if normalized_org_id:
        try:
            raw_secret = SecretManager(db_session=db).get_key(
                "wordpress",
                normalized_org_id,
            )
            secret_payload = json.loads(raw_secret)
            credentials = _credentials_from_mapping(secret_payload)
            if credentials is not None:
                return credentials
        except Exception:  # noqa: BLE001 - DB/secret outages must reach env fallback
            # Transition fallback: production moves to the binding without an
            # outage, while existing env credentials remain usable.
            pass

    return _credentials_from_mapping(
        {
            "base_url": os.getenv("WP_BASE_URL"),
            "user": os.getenv("WP_APP_USER"),
            "app_password": os.getenv("WP_APP_PASSWORD"),
        }
    )


def _unreachable(error: str = "wordpress_unreachable", **extra: Any) -> dict[str, Any]:
    return {"reachable": False, "error": error, **extra}


def _basic_authorization(credentials: _WordPressCredentials) -> str:
    token = base64.b64encode(
        f"{credentials.user}:{credentials.app_password}".encode("utf-8")
    ).decode("ascii")
    return f"Basic {token}"


def _read_json_response(response: Any) -> Any:
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("wordpress_response_too_large")
    if not raw:
        return {}
    text = raw.decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 诊断口不全是 JSON:email-verify 的 by-ev-ping 回纯文本版本行。
        # HTTP 已成功就不该记 unreachable,原文交给 _ping_summary 的文本兜底。
        return text.strip()


def _request_json(
    url: str,
    *,
    credentials: _WordPressCredentials | None = None,
    authenticated: bool = False,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "BarongOps-WPBridge/1.0"}
    if authenticated:
        if credentials is None:
            return _unreachable("wordpress_credentials_unavailable")
        headers["Authorization"] = _basic_authorization(credentials)
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(  # noqa: S310 - URL is credential-configured/fixed
            request,
            timeout=WP_TIMEOUT_SECONDS,
        ) as response:
            return {"reachable": True, "data": _read_json_response(response)}
    except HTTPError as exc:
        return _unreachable("wordpress_http_error", status=int(exc.code))
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return _unreachable()


def _api_url(credentials: _WordPressCredentials, path: str) -> str:
    return f"{credentials.base_url.rstrip('/')}/wp-json/wp/v2/{path.lstrip('/')}"


def _public_query_url(
    credentials: _WordPressCredentials,
    query_name: str,
    query_value: str | None = None,
) -> str:
    separator = "&" if "?" in credentials.base_url else "?"
    if query_value is None:
        query = query_name
    else:
        query = urlencode({query_name: query_value})
    return f"{credentials.base_url.rstrip('/')}/{separator}{query}"


def get_option(
    name: str,
    *,
    db: Any | None = None,
    org_id: str | None = None,
    _credentials: _WordPressCredentials | None = None,
) -> dict[str, Any]:
    option_name = _option_name(name)
    credentials = _credentials or _resolve_credentials(db=db, org_id=org_id)
    if credentials is None:
        return _unreachable("wordpress_credentials_unavailable", value=None)
    result = _request_json(
        _api_url(credentials, "settings"),
        credentials=credentials,
        authenticated=True,
    )
    if not result["reachable"]:
        return {**result, "value": None}
    data = result.get("data")
    value = data.get(option_name) if isinstance(data, dict) else None
    return {"reachable": True, "value": value}


def set_option(
    name: str,
    value: Any,
    *,
    db: Any | None = None,
    org_id: str | None = None,
    _credentials: _WordPressCredentials | None = None,
) -> dict[str, Any]:
    option_name = _option_name(name)
    credentials = _credentials or _resolve_credentials(db=db, org_id=org_id)
    if credentials is None:
        return _unreachable("wordpress_credentials_unavailable")
    result = _request_json(
        _api_url(credentials, "settings"),
        credentials=credentials,
        authenticated=True,
        method="POST",
        payload={option_name: value},
    )
    if not result["reachable"]:
        return result
    return {"reachable": True}


def fetch_plugins(
    *,
    db: Any | None = None,
    org_id: str | None = None,
    _credentials: _WordPressCredentials | None = None,
) -> dict[str, Any]:
    credentials = _credentials or _resolve_credentials(db=db, org_id=org_id)
    if credentials is None:
        return _unreachable("wordpress_credentials_unavailable", plugins=[])
    result = _request_json(
        _api_url(credentials, "plugins?per_page=100"),
        credentials=credentials,
        authenticated=True,
    )
    if not result["reachable"]:
        return {**result, "plugins": []}
    rows = result.get("data")
    if not isinstance(rows, list):
        rows = []
    plugins = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        plugins.append(
            {
                "plugin": str(row.get("plugin") or ""),
                "name": str(row.get("name") or row.get("plugin") or ""),
                "status": str(row.get("status") or "unknown"),
                "version": str(row.get("version") or ""),
            }
        )
    return {"reachable": True, "plugins": plugins}


def fetch_ping(
    slug: str,
    *,
    db: Any | None = None,
    org_id: str | None = None,
    _credentials: _WordPressCredentials | None = None,
) -> dict[str, Any]:
    if slug not in PING_QUERIES:
        raise ValueError(f"wordpress_ping_not_allowed:{slug}")
    credentials = _credentials or _resolve_credentials(db=db, org_id=org_id)
    if credentials is None:
        return _unreachable("wordpress_credentials_unavailable", slug=slug)
    query_name, requires_key = PING_QUERIES[slug]
    query_value = (os.getenv("CS_INBOUND_KEY") or "").strip() if requires_key else None
    if requires_key and not query_value:
        return _unreachable("wordpress_ping_key_unavailable", slug=slug)
    result = _request_json(_public_query_url(credentials, query_name, query_value))
    return {**result, "slug": slug}


def fetch_maillog(
    *,
    db: Any | None = None,
    org_id: str | None = None,
    _credentials: _WordPressCredentials | None = None,
) -> dict[str, Any]:
    credentials = _credentials or _resolve_credentials(db=db, org_id=org_id)
    if credentials is None:
        return _unreachable("wordpress_credentials_unavailable")
    return _request_json(_public_query_url(credentials, "by-ev-maillog"))


def _payload_dict(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data")
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return data if isinstance(data, dict) else {}


def _ping_summary(slug: str, result: dict[str, Any]) -> dict[str, Any]:
    payload = _payload_dict(result)
    explicit_ok = payload.get("ok")
    if isinstance(explicit_ok, bool):
        ok = bool(result.get("reachable")) and explicit_ok
    else:
        status_value = str(payload.get("status") or "").strip().lower()
        ok = bool(result.get("reachable")) and status_value not in {
            "error",
            "failed",
            "failure",
            "down",
        }
    version = payload.get("version") or payload.get("ver") or payload.get("plugin_version")
    if version is None and not payload and isinstance(result.get("data"), str):
        version = result["data"]
    return {"slug": slug, "ok": ok, "version": str(version or "")}


def _mail_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data")
    if isinstance(data, dict):
        for key in ("logs", "items", "mail", "entries"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def sentinel_snapshot(
    *,
    db: Any | None = None,
    org_id: str | None = None,
) -> dict[str, Any]:
    credentials = _resolve_credentials(db=db, org_id=org_id)
    if credentials is None:
        return _unreachable(
            "wordpress_credentials_unavailable",
            plugins=[],
            pings=[{"slug": slug, "ok": False, "version": ""} for slug in PING_QUERIES],
            mail={"items": [], "recent_failures": 0},
        )

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="wp-sentinel") as executor:
        plugins_future = executor.submit(fetch_plugins, _credentials=credentials)
        ping_futures = {
            slug: executor.submit(fetch_ping, slug, _credentials=credentials)
            for slug in PING_QUERIES
        }
        mail_future = executor.submit(fetch_maillog, _credentials=credentials)
        plugins_result = plugins_future.result()
        ping_results = {slug: future.result() for slug, future in ping_futures.items()}
        mail_result = mail_future.result()

    rows = _mail_rows(mail_result)
    recent = [
        {
            "time": str(row.get("time") or row.get("date") or row.get("sent_at") or ""),
            "to": str(row.get("to") or ""),
            "subject": str(row.get("subject") or ""),
        }
        for row in rows[:5]
    ]
    reachable = bool(plugins_result.get("reachable")) or bool(
        mail_result.get("reachable")
    ) or any(bool(result.get("reachable")) for result in ping_results.values())
    response = {
        "reachable": reachable,
        "plugins": plugins_result.get("plugins", []),
        "pings": [
            _ping_summary(slug, ping_results[slug]) for slug in PING_QUERIES
        ],
        "mail": {
            "items": recent,
            "recent_failures": sum(
                1 for row in rows if str(row.get("to") or "") == "FAILED"
            ),
        },
    }
    if not reachable:
        response["error"] = "wordpress_unreachable"
    return response


def smtp_check(
    *,
    db: Any | None = None,
    org_id: str | None = None,
) -> dict[str, Any]:
    credentials = _resolve_credentials(db=db, org_id=org_id)
    if credentials is None:
        return _unreachable("wordpress_credentials_unavailable")
    key = (os.getenv("CS_INBOUND_KEY") or "").strip()
    if not key:
        return _unreachable("wordpress_ping_key_unavailable")
    result = _request_json(_public_query_url(credentials, "by-ev-smtpdiag", key))
    if not result.get("reachable"):
        return result
    payload = _payload_dict(result)
    return {
        "reachable": True,
        "probe": payload.get("probe"),
        "verdict_line": payload.get("verdict_line"),
        "host": payload.get("host"),
        "username": payload.get("username"),
    }


def _site_url_for_path(base_url: str, path: str) -> str:
    base = urlsplit(base_url)
    # Concatenating onto the configured origin (instead of urljoin) means even
    # a scheme-relative ``//host`` body value cannot replace the trusted host.
    return urlunsplit((base.scheme, base.netloc, path, "", ""))


def verify_redirect(
    path: str,
    *,
    db: Any | None = None,
    org_id: str | None = None,
) -> dict[str, Any]:
    credentials = _resolve_credentials(db=db, org_id=org_id)
    if credentials is None:
        return _unreachable(
            "wordpress_credentials_unavailable",
            status=None,
            location=None,
        )
    url = _site_url_for_path(credentials.base_url, path)
    request = urllib.request.Request(
        url,
        headers={"Accept": "*/*", "User-Agent": "BarongOps-WPBridge/1.0"},
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=WP_TIMEOUT_SECONDS) as response:
            return {
                "status": int(response.status),
                "location": response.headers.get("Location"),
            }
    except HTTPError as exc:
        # A refused redirect is surfaced by urllib as HTTPError; it is still
        # the exact status/location the operator asked to inspect.
        return {"status": int(exc.code), "location": exc.headers.get("Location")}
    except (URLError, TimeoutError, OSError):
        return _unreachable("wordpress_unreachable", status=None, location=None)
