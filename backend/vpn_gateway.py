from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


AUTH_URL = "http://127.0.0.1:8000/api/public/auth/me"
VPN_AGENT_HEALTH_URL = "http://127.0.0.1:18765/health"
VPN_AGENT_STATUS_URL = "http://127.0.0.1:18765/v1/status"
BACKEND_HEALTH_URL = "http://127.0.0.1:8000/health"

STATUS_PATH = "/api/backend/vpn/status"
HEALTH_PATH = "/health"
MAX_COOKIE_BYTES = 8192
MAX_UPSTREAM_BYTES = 65536
AUTH_TIMEOUT_SECONDS = 1.5
VPN_TIMEOUT_SECONDS = 2.5

LOGGER = logging.getLogger("barong_vpn_gateway")
_OPENER = build_opener(ProxyHandler({}))


class GatewayError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class UpstreamUnavailable(Exception):
    pass


FetchJson = Callable[[str, Mapping[str, str], float], tuple[int, object]]


def fetch_json(
    url: str,
    headers: Mapping[str, str] | None = None,
    timeout: float = VPN_TIMEOUT_SECONDS,
) -> tuple[int, object]:
    request = Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "barong-vpn-gateway/0.1.0",
            **dict(headers or {}),
        },
    )
    try:
        response = _OPENER.open(request, timeout=timeout)
    except HTTPError as exc:
        status_code = int(exc.code)
        exc.close()
        return status_code, None
    except (URLError, TimeoutError, OSError) as exc:
        raise UpstreamUnavailable from exc

    with response:
        status_code = int(response.status)
        raw = response.read(MAX_UPSTREAM_BYTES + 1)
    if len(raw) > MAX_UPSTREAM_BYTES:
        raise UpstreamUnavailable
    try:
        return status_code, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpstreamUnavailable from exc


def _safe_string(value: object, *, max_length: int = 256) -> str | None:
    if not isinstance(value, str) or len(value) > max_length:
        return None
    return value


def _safe_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


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
        "generated_at": _safe_string(payload.get("generated_at"), max_length=64),
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
            "expected_listen_port": _safe_non_negative_int(
                vpn.get("expected_listen_port")
            ),
            "peer_count": _safe_non_negative_int(vpn.get("peer_count")),
            "recently_active_peer_count": _safe_non_negative_int(
                vpn.get("recently_active_peer_count")
            ),
            "latest_handshake_at": _safe_string(
                vpn.get("latest_handshake_at"), max_length=64
            ),
            "transfer": {
                "received_bytes": _safe_non_negative_int(
                    transfer.get("received_bytes")
                ),
                "sent_bytes": _safe_non_negative_int(transfer.get("sent_bytes")),
            },
        },
        "warnings": warnings,
    }


def get_authenticated_vpn_status(
    cookie: str | None,
    *,
    fetcher: FetchJson = fetch_json,
) -> dict[str, object]:
    if not cookie or len(cookie.encode("utf-8")) > MAX_COOKIE_BYTES:
        raise GatewayError(401, "Not authenticated.")

    try:
        auth_status, identity = fetcher(
            AUTH_URL,
            {"Cookie": cookie},
            AUTH_TIMEOUT_SECONDS,
        )
    except UpstreamUnavailable as exc:
        raise GatewayError(503, "Authentication service temporarily unavailable.") from exc

    if auth_status in {401, 403}:
        raise GatewayError(401, "Not authenticated.")
    if auth_status != 200 or not isinstance(identity, dict) or not identity.get("id"):
        raise GatewayError(503, "Authentication service temporarily unavailable.")

    try:
        vpn_status_code, vpn_payload = fetcher(
            VPN_AGENT_STATUS_URL,
            {},
            VPN_TIMEOUT_SECONDS,
        )
    except UpstreamUnavailable as exc:
        raise GatewayError(503, "VPN status temporarily unavailable.") from exc
    if vpn_status_code != 200:
        raise GatewayError(503, "VPN status temporarily unavailable.")
    return sanitize_vpn_status(vpn_payload)


def dependency_health(*, fetcher: FetchJson = fetch_json) -> tuple[int, dict[str, object]]:
    dependencies: dict[str, str] = {}
    for name, url in (
        ("console_backend", BACKEND_HEALTH_URL),
        ("vpn_agent", VPN_AGENT_HEALTH_URL),
    ):
        try:
            status_code, payload = fetcher(url, {}, VPN_TIMEOUT_SECONDS)
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
            "version": "0.1.0",
            "mode": "read_only",
            "dependencies": dependencies,
        },
    )


class VpnGatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


class VpnGatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "BarongVpnGateway"
    sys_version = ""

    def _send_json(self, status_code: int, payload: object, *, head_only: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
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

    def _handle_read(self, *, head_only: bool = False) -> None:
        path = urlsplit(self.path).path
        if path == HEALTH_PATH:
            status_code, payload = dependency_health()
            self._send_json(status_code, payload, head_only=head_only)
            return
        if path != STATUS_PATH:
            self._send_json(404, {"detail": "Not found."}, head_only=head_only)
            return

        try:
            payload = get_authenticated_vpn_status(self.headers.get("Cookie"))
        except GatewayError as exc:
            self._send_json(
                exc.status_code,
                {"detail": exc.detail},
                head_only=head_only,
            )
            return
        self._send_json(200, payload, head_only=head_only)

    def do_GET(self) -> None:
        self._handle_read()

    def do_HEAD(self) -> None:
        self._handle_read(head_only=True)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

    def _method_not_allowed(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed

    def log_message(self, _format: str, *_args: Any) -> None:
        LOGGER.info("request method=%s path=%s", self.command, urlsplit(self.path).path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Barong read-only VPN status gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18766)
    args = parser.parse_args()
    if args.host != "127.0.0.1":
        parser.error("the VPN gateway must bind to 127.0.0.1")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    return args


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    server = VpnGatewayServer((args.host, args.port), VpnGatewayHandler)
    LOGGER.info("starting read-only gateway on %s:%s", args.host, args.port)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
