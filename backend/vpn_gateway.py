from __future__ import annotations

import argparse
import json
import logging
import os
import re
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


VERSION = "0.3.0"
AUTH_URL = "http://127.0.0.1:8000/api/public/auth/me"
VPN_AGENT_HEALTH_URL = "http://127.0.0.1:18765/health"
VPN_AGENT_STATUS_URL = "http://127.0.0.1:18765/v1/status"
VPN_AGENT_DEVICES_URL = "http://127.0.0.1:18765/v1/devices"
BACKEND_HEALTH_URL = "http://127.0.0.1:8000/health"

STATUS_PATH = "/api/backend/vpn/status"
DEVICES_PATH = "/api/backend/vpn/devices"
NATIVE_ENROLL_PATH = f"{DEVICES_PATH}/enroll"
DEVICE_PATH_PREFIX = f"{DEVICES_PATH}/"
HEALTH_PATH = "/health"
MAX_COOKIE_BYTES = 8192
MAX_BODY_BYTES = 16_384
MAX_UPSTREAM_BYTES = 65_536
AUTH_TIMEOUT_SECONDS = 1.5
VPN_TIMEOUT_SECONDS = 5.0
PLATFORMS = {"windows", "macos", "ios", "android", "other"}
DEVICE_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
ADDRESS_PATTERN = re.compile(r"^10\.66\.66\.(?:[2-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-4])/32$")
KEY_PATTERN = re.compile(r"^[A-Za-z0-9+/]{43}=$")
AGENT_FIELD_PATTERN = re.compile(r"^[A-Za-z0-9._+-]{1,32}$")

LOGGER = logging.getLogger("barong_vpn_gateway")
_OPENER = build_opener(ProxyHandler({}))


class GatewayError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class UpstreamUnavailable(Exception):
    pass


FetchJson = Callable[
    [str, str, Mapping[str, str], Optional[object], float],
    tuple[int, object],
]


def _decode_json(raw: bytes) -> object:
    if len(raw) > MAX_UPSTREAM_BYTES:
        raise UpstreamUnavailable
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpstreamUnavailable from exc


def fetch_json(
    url: str,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    payload: object | None = None,
    timeout: float = VPN_TIMEOUT_SECONDS,
) -> tuple[int, object]:
    data = None
    request_headers = {
        "Accept": "application/json",
        "User-Agent": f"barong-vpn-gateway/{VERSION}",
        **dict(headers or {}),
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, method=method, headers=request_headers, data=data)
    try:
        response = _OPENER.open(request, timeout=timeout)
    except HTTPError as exc:
        status_code = int(exc.code)
        raw = exc.read(MAX_UPSTREAM_BYTES + 1)
        exc.close()
        if not raw:
            return status_code, None
        return status_code, _decode_json(raw)
    except (URLError, TimeoutError, OSError) as exc:
        raise UpstreamUnavailable from exc

    with response:
        status_code = int(response.status)
        raw = response.read(MAX_UPSTREAM_BYTES + 1)
    return status_code, _decode_json(raw)


def _safe_string(value: object, *, max_length: int = 256) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        return None
    return normalized


def _safe_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _safe_timestamp(value: object) -> str | None:
    return _safe_string(value, max_length=64)


def sanitize_vpn_status(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise GatewayError(503, "VPN status temporarily unavailable.")
    vpn = payload.get("vpn")
    if not isinstance(vpn, dict) or vpn.get("interface") != "awg0":
        raise GatewayError(503, "VPN status temporarily unavailable.")
    service = vpn.get("service")
    transfer = vpn.get("transfer")
    if not isinstance(service, dict) or not isinstance(transfer, dict):
        raise GatewayError(503, "VPN status temporarily unavailable.")
    warnings_value = payload.get("warnings")
    warnings: list[str] = []
    if isinstance(warnings_value, list):
        for item in warnings_value[:10]:
            safe_item = _safe_string(item, max_length=200)
            if safe_item is not None:
                warnings.append(safe_item)
    return {
        "status": "ok",
        "generated_at": _safe_timestamp(payload.get("generated_at")),
        "agent_version": _safe_string(payload.get("agent_version"), max_length=32),
        "vpn": {
            "interface": "awg0",
            "service": {
                "active_state": _safe_string(service.get("active_state"), max_length=32),
                "sub_state": _safe_string(service.get("sub_state"), max_length=32),
                "active_since": _safe_string(service.get("active_since"), max_length=96),
            },
            "address": _safe_string(vpn.get("address"), max_length=64),
            "listen_port": _safe_non_negative_int(vpn.get("listen_port")),
            "expected_listen_port": _safe_non_negative_int(vpn.get("expected_listen_port")),
            "peer_count": _safe_non_negative_int(vpn.get("peer_count")),
            "recently_active_peer_count": _safe_non_negative_int(
                vpn.get("recently_active_peer_count")
            ),
            "latest_handshake_at": _safe_timestamp(vpn.get("latest_handshake_at")),
            "transfer": {
                "received_bytes": _safe_non_negative_int(transfer.get("received_bytes")),
                "sent_bytes": _safe_non_negative_int(transfer.get("sent_bytes")),
            },
        },
        "warnings": warnings,
    }


def sanitize_device(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise GatewayError(503, "VPN device service temporarily unavailable.")
    device_id = _safe_string(payload.get("id"), max_length=36)
    name = _safe_string(payload.get("name"), max_length=64)
    platform = payload.get("platform")
    address = payload.get("address")
    enabled = payload.get("enabled")
    if (
        device_id is None
        or DEVICE_ID_PATTERN.fullmatch(device_id) is None
        or name is None
        or platform not in PLATFORMS
        or not isinstance(address, str)
        or ADDRESS_PATTERN.fullmatch(address) is None
        or not isinstance(enabled, bool)
    ):
        raise GatewayError(503, "VPN device service temporarily unavailable.")
    return {
        "id": device_id,
        "name": name,
        "platform": platform,
        "address": address,
        "enabled": enabled,
        "created_at": _safe_timestamp(payload.get("created_at")),
        "updated_at": _safe_timestamp(payload.get("updated_at")),
        "last_handshake_at": _safe_timestamp(payload.get("last_handshake_at")),
        "received_bytes": _safe_non_negative_int(payload.get("received_bytes")),
        "sent_bytes": _safe_non_negative_int(payload.get("sent_bytes")),
    }


def sanitize_device_list(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
        raise GatewayError(503, "VPN device service temporarily unavailable.")
    devices = payload["devices"]
    if len(devices) > 10:
        raise GatewayError(503, "VPN device service temporarily unavailable.")
    return {"devices": [sanitize_device(item) for item in devices]}


def sanitize_created_device(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or payload.get("one_time") is not True:
        raise GatewayError(503, "VPN device service temporarily unavailable.")
    configuration = payload.get("configuration")
    if not isinstance(configuration, str) or not 1 <= len(configuration) <= 8192:
        raise GatewayError(503, "VPN device service temporarily unavailable.")
    return {
        "device": sanitize_device(payload.get("device")),
        "configuration": configuration,
        "one_time": True,
    }


def sanitize_native_enrollment(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or payload.get("one_time") is not True:
        raise GatewayError(503, "VPN device service temporarily unavailable.")
    provisioning = payload.get("provisioning")
    if not isinstance(provisioning, dict):
        raise GatewayError(503, "VPN device service temporarily unavailable.")
    device_id = _safe_string(provisioning.get("device_id"), max_length=36)
    address = provisioning.get("address")
    preshared_key = provisioning.get("preshared_key")
    if (
        provisioning.get("schema_version") != 1
        or device_id is None
        or DEVICE_ID_PATTERN.fullmatch(device_id) is None
        or not isinstance(address, str)
        or ADDRESS_PATTERN.fullmatch(address) is None
        or not isinstance(preshared_key, str)
        or KEY_PATTERN.fullmatch(preshared_key) is None
    ):
        raise GatewayError(503, "VPN device service temporarily unavailable.")
    return {
        "device": sanitize_device(payload.get("device")),
        "provisioning": {
            "schema_version": 1,
            "device_id": device_id,
            "address": address,
            "preshared_key": preshared_key,
        },
        "one_time": True,
    }


def _authenticate(cookie: str | None, *, fetcher: FetchJson) -> str:
    if not cookie or len(cookie.encode("utf-8")) > MAX_COOKIE_BYTES:
        raise GatewayError(401, "Not authenticated.")
    try:
        auth_status, identity = fetcher(
            AUTH_URL,
            "GET",
            {"Cookie": cookie},
            None,
            AUTH_TIMEOUT_SECONDS,
        )
    except UpstreamUnavailable as exc:
        raise GatewayError(503, "Authentication service temporarily unavailable.") from exc
    if auth_status in {401, 403}:
        raise GatewayError(401, "Not authenticated.")
    identity_id = identity.get("id") if isinstance(identity, dict) else None
    if auth_status != 200 or not isinstance(identity_id, (str, int)):
        raise GatewayError(503, "Authentication service temporarily unavailable.")
    normalized = str(identity_id)
    if not normalized or len(normalized) > 128:
        raise GatewayError(503, "Authentication service temporarily unavailable.")
    return normalized


def _agent_headers(owner_id: str, agent_token: str) -> dict[str, str]:
    if not agent_token:
        raise GatewayError(503, "VPN device service temporarily unavailable.")
    return {
        "Authorization": f"Bearer {agent_token}",
        "X-Barong-User-ID": owner_id,
    }


def _agent_error(status_code: int) -> GatewayError:
    if status_code == 400:
        return GatewayError(400, "设备信息不正确。")
    if status_code == 404:
        return GatewayError(404, "没有找到这台设备。")
    if status_code == 409:
        return GatewayError(409, "设备数量或可用地址已达到上限。")
    return GatewayError(503, "VPN device service temporarily unavailable.")


def get_authenticated_vpn_status(
    cookie: str | None,
    *,
    fetcher: FetchJson = fetch_json,
) -> dict[str, object]:
    _authenticate(cookie, fetcher=fetcher)
    try:
        status_code, payload = fetcher(
            VPN_AGENT_STATUS_URL,
            "GET",
            {},
            None,
            VPN_TIMEOUT_SECONDS,
        )
    except UpstreamUnavailable as exc:
        raise GatewayError(503, "VPN status temporarily unavailable.") from exc
    if status_code != 200:
        raise GatewayError(503, "VPN status temporarily unavailable.")
    return sanitize_vpn_status(payload)


def get_authenticated_devices(
    cookie: str | None,
    *,
    agent_token: str,
    fetcher: FetchJson = fetch_json,
) -> dict[str, object]:
    owner_id = _authenticate(cookie, fetcher=fetcher)
    try:
        status_code, payload = fetcher(
            VPN_AGENT_DEVICES_URL,
            "GET",
            _agent_headers(owner_id, agent_token),
            None,
            VPN_TIMEOUT_SECONDS,
        )
    except UpstreamUnavailable as exc:
        raise GatewayError(503, "VPN device service temporarily unavailable.") from exc
    if status_code != 200:
        raise _agent_error(status_code)
    return sanitize_device_list(payload)


def create_authenticated_device(
    cookie: str | None,
    request_payload: object,
    *,
    agent_token: str,
    fetcher: FetchJson = fetch_json,
) -> dict[str, object]:
    owner_id = _authenticate(cookie, fetcher=fetcher)
    if not isinstance(request_payload, dict):
        raise GatewayError(400, "设备信息不正确。")
    name = _safe_string(request_payload.get("name"), max_length=64)
    platform = request_payload.get("platform")
    if name is None or platform not in PLATFORMS:
        raise GatewayError(400, "设备信息不正确。")
    try:
        status_code, payload = fetcher(
            VPN_AGENT_DEVICES_URL,
            "POST",
            _agent_headers(owner_id, agent_token),
            {"name": name, "platform": platform},
            VPN_TIMEOUT_SECONDS,
        )
    except UpstreamUnavailable as exc:
        raise GatewayError(503, "VPN device service temporarily unavailable.") from exc
    if status_code != 201:
        raise _agent_error(status_code)
    return sanitize_created_device(payload)


def enroll_authenticated_device(
    cookie: str | None,
    request_payload: object,
    *,
    agent_token: str,
    fetcher: FetchJson = fetch_json,
) -> dict[str, object]:
    owner_id = _authenticate(cookie, fetcher=fetcher)
    if not isinstance(request_payload, dict):
        raise GatewayError(400, "设备信息不正确。")
    name = _safe_string(request_payload.get("name"), max_length=64)
    platform = request_payload.get("platform")
    device_id = request_payload.get("device_id")
    public_key = request_payload.get("public_key")
    architecture = request_payload.get("architecture")
    agent_version = request_payload.get("agent_version")
    if (
        name is None
        or platform not in PLATFORMS
        or not isinstance(device_id, str)
        or DEVICE_ID_PATTERN.fullmatch(device_id) is None
        or not isinstance(public_key, str)
        or KEY_PATTERN.fullmatch(public_key) is None
        or not isinstance(architecture, str)
        or AGENT_FIELD_PATTERN.fullmatch(architecture) is None
        or not isinstance(agent_version, str)
        or AGENT_FIELD_PATTERN.fullmatch(agent_version) is None
    ):
        raise GatewayError(400, "设备信息不正确。")
    forwarded = {
        "name": name,
        "platform": platform,
        "device_id": device_id,
        "public_key": public_key,
        "architecture": architecture,
        "agent_version": agent_version,
    }
    try:
        status_code, payload = fetcher(
            f"{VPN_AGENT_DEVICES_URL}/enroll",
            "POST",
            _agent_headers(owner_id, agent_token),
            forwarded,
            VPN_TIMEOUT_SECONDS,
        )
    except UpstreamUnavailable as exc:
        raise GatewayError(503, "VPN device service temporarily unavailable.") from exc
    if status_code != 201:
        raise _agent_error(status_code)
    return sanitize_native_enrollment(payload)


def update_authenticated_device(
    cookie: str | None,
    device_id: str,
    request_payload: object,
    *,
    agent_token: str,
    fetcher: FetchJson = fetch_json,
) -> dict[str, object]:
    owner_id = _authenticate(cookie, fetcher=fetcher)
    if DEVICE_ID_PATTERN.fullmatch(device_id) is None:
        raise GatewayError(404, "没有找到这台设备。")
    enabled = request_payload.get("enabled") if isinstance(request_payload, dict) else None
    if not isinstance(enabled, bool):
        raise GatewayError(400, "设备状态不正确。")
    try:
        status_code, payload = fetcher(
            f"{VPN_AGENT_DEVICES_URL}/{device_id}",
            "PATCH",
            _agent_headers(owner_id, agent_token),
            {"enabled": enabled},
            VPN_TIMEOUT_SECONDS,
        )
    except UpstreamUnavailable as exc:
        raise GatewayError(503, "VPN device service temporarily unavailable.") from exc
    if status_code != 200:
        raise _agent_error(status_code)
    if not isinstance(payload, dict):
        raise GatewayError(503, "VPN device service temporarily unavailable.")
    return {"device": sanitize_device(payload.get("device"))}


def dependency_health(*, fetcher: FetchJson = fetch_json) -> tuple[int, dict[str, object]]:
    dependencies: dict[str, str] = {}
    for name, url in (
        ("console_backend", BACKEND_HEALTH_URL),
        ("vpn_agent", VPN_AGENT_HEALTH_URL),
    ):
        try:
            status_code, payload = fetcher(url, "GET", {}, None, VPN_TIMEOUT_SECONDS)
            healthy = (
                status_code == 200
                and isinstance(payload, dict)
                and payload.get("status") == "ok"
            )
        except UpstreamUnavailable:
            healthy = False
        dependencies[name] = "ok" if healthy else "unavailable"
    healthy = all(value == "ok" for value in dependencies.values())
    return (
        200 if healthy else 503,
        {
            "status": "ok" if healthy else "degraded",
            "service": "barong-vpn-gateway",
            "version": VERSION,
            "mode": "device_management",
            "dependencies": dependencies,
        },
    )


def load_agent_token(path: Path) -> str:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("agent token unavailable") from exc
    if len(token) < 32 or len(token) > 256 or any(character.isspace() for character in token):
        raise RuntimeError("invalid agent token")
    return token


def _credential_path() -> Path:
    credentials_directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if credentials_directory:
        return Path(credentials_directory) / "agent-token"
    return Path("/etc/barong-vpn-gateway/agent-token")


class VpnGatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        agent_token: str,
    ) -> None:
        super().__init__(server_address, handler)
        self.agent_token = agent_token


class VpnGatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "BarongVpnGateway"
    sys_version = ""

    @property
    def gateway_server(self) -> VpnGatewayServer:
        return self.server  # type: ignore[return-value]

    def _send_json(self, status_code: int, payload: object, *, head_only: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _read_json(self) -> dict[str, object]:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise GatewayError(415, "请求格式必须是 JSON。")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError as exc:
            raise GatewayError(400, "请求内容不正确。") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise GatewayError(400, "请求内容不正确。")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GatewayError(400, "请求内容不正确。") from exc
        if not isinstance(payload, dict):
            raise GatewayError(400, "请求内容不正确。")
        return payload

    def _send_gateway_error(self, error: GatewayError, *, head_only: bool = False) -> None:
        self._send_json(error.status_code, {"detail": error.detail}, head_only=head_only)

    def _handle_read(self, *, head_only: bool = False) -> None:
        path = urlsplit(self.path).path
        if path == HEALTH_PATH:
            status_code, payload = dependency_health()
            self._send_json(status_code, payload, head_only=head_only)
            return
        try:
            if path == STATUS_PATH:
                payload = get_authenticated_vpn_status(self.headers.get("Cookie"))
            elif path == DEVICES_PATH:
                payload = get_authenticated_devices(
                    self.headers.get("Cookie"),
                    agent_token=self.gateway_server.agent_token,
                )
            else:
                self._send_json(404, {"detail": "Not found."}, head_only=head_only)
                return
        except GatewayError as exc:
            self._send_gateway_error(exc, head_only=head_only)
            return
        self._send_json(200, payload, head_only=head_only)

    def do_GET(self) -> None:
        self._handle_read()

    def do_HEAD(self) -> None:
        self._handle_read(head_only=True)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path not in {DEVICES_PATH, NATIVE_ENROLL_PATH}:
            self._send_json(405, {"detail": "Method not allowed."})
            return
        try:
            request_payload = self._read_json()
            if path == NATIVE_ENROLL_PATH:
                payload = enroll_authenticated_device(
                    self.headers.get("Cookie"),
                    request_payload,
                    agent_token=self.gateway_server.agent_token,
                )
            else:
                payload = create_authenticated_device(
                    self.headers.get("Cookie"),
                    request_payload,
                    agent_token=self.gateway_server.agent_token,
                )
        except GatewayError as exc:
            self._send_gateway_error(exc)
            return
        self._send_json(201, payload)

    def do_PATCH(self) -> None:
        path = urlsplit(self.path).path
        if not path.startswith(DEVICE_PATH_PREFIX):
            self._send_json(405, {"detail": "Method not allowed."})
            return
        try:
            payload = update_authenticated_device(
                self.headers.get("Cookie"),
                path[len(DEVICE_PATH_PREFIX) :],
                self._read_json(),
                agent_token=self.gateway_server.agent_token,
            )
        except GatewayError as exc:
            self._send_gateway_error(exc)
            return
        self._send_json(200, payload)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, POST, PATCH, OPTIONS")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

    def _method_not_allowed(self) -> None:
        self._send_json(405, {"detail": "Method not allowed."})

    do_PUT = _method_not_allowed
    do_DELETE = _method_not_allowed

    def log_message(self, _format: str, *_args: Any) -> None:
        path = urlsplit(self.path).path
        route = "device" if path.startswith(DEVICE_PATH_PREFIX) else path
        LOGGER.info("request method=%s route=%s", self.command, route)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Barong authenticated VPN gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18766)
    parser.add_argument("--agent-token-file", type=Path)
    args = parser.parse_args()
    if args.host != "127.0.0.1":
        parser.error("the VPN gateway must bind to 127.0.0.1")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    return args


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    agent_token = load_agent_token(args.agent_token_file or _credential_path())
    server = VpnGatewayServer(
        (args.host, args.port),
        VpnGatewayHandler,
        agent_token=agent_token,
    )
    LOGGER.info("starting VPN gateway version=%s on loopback", VERSION)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
